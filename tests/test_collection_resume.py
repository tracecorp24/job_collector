"""Lossless resume, cache decisions, actual pacing and source-wait analysis."""
import json
import time
import unittest
from unittest.mock import patch
from sqlalchemy import text

import test_light
import test_workspace
from test_light import card, response, DETAIL
from jobapp import config, details, pipeline, runs, server, service
from jobapp.models import Job, SearchTask, TaskJob
from jobapp.transport import Coordinator, Details


class CollectionResumeTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown
    start_worker = test_workspace.WorkspaceTests.start_worker
    scrape = test_light.FullLightTests.scrape

    def test_localized_query_is_persisted_and_reused_after_resume(self):
        plan = dict(keyword='Softwareentwickler', original_keyword='yazılım geliştirici',
                    location='Berlin, Germany', language='de', status='translated')
        def request_and_wait(path, replies, body=None, run_id=None):
            with patch('requests.Session.get', side_effect=replies):
                result = self.client.post(path, json=body)
                self.assertEqual(result.status_code, 200, result.json)
                thread = server.state.thread
                # SQLite commits can exceed the legacy helper's 15s on Windows.
                thread.join(180)
                timed_out = thread.is_alive()
                if timed_out:
                    server.state.stop_flag = True
                    thread.join(15)
                self.assertFalse(thread.is_alive(), 'collector worker did not stop')
                self.assertFalse(timed_out, 'collector worker exceeded the test deadline')
            run_id = run_id or result.json['run_id']
            return self.client.get('/api/runs/'+run_id).json

        # The shared HTTP transport uses the config interval, independently of
        # the scraper interval already patched by setUp. No real pacing here.
        with patch.object(config, 'REQUEST_INTERVAL', 0), patch.object(config, 'REQUEST_JITTER', 0), \
                patch.object(pipeline, 'run_scrape', wraps=pipeline.run_scrape) as scrape:
            with patch('jobapp.query_translation.plan', return_value=plan) as translate:
                original = request_and_wait('/api/scrape',
                    [response(card(1)+card(2)), response(DETAIL), response(status=429)],
                    body={'tasks':[dict(keyword='yazılım geliştirici', location='Berlin, Germany', limit=2)]})
                self.assertEqual(translate.call_count, 1)
            self.assertEqual(original['tasks'][0]['stats']['search_plan'], plan)
            self.assertEqual(original['tasks'][0]['keyword'], 'yazılım geliştirici')
            self.assertEqual(scrape.call_args.args[0][0]['keyword'], 'Softwareentwickler')
            self.clear_deadline()
            with patch('jobapp.query_translation.plan', side_effect=AssertionError('resume must reuse stored query')):
                final = request_and_wait('/api/runs/'+original['id']+'/resume',
                    [response(DETAIL)], run_id=original['id'])
            self.assertEqual(scrape.call_count, 2)
            self.assertEqual(scrape.call_args.args[0][0]['keyword'], 'Softwareentwickler')
        self.assertEqual(final['tasks'][0]['stats']['search_plan'], plan)
        self.assertEqual(final['tasks'][0]['count'], 2)
        self.assertEqual(final['tasks'][0]['keyword_language'], 'de')
        self.assertEqual(final['tasks'][0]['stats']['search_efficiency']['keyword_language'], 'de')

    def paused(self):
        return self.start_worker([dict(keyword='AI', location='Istanbul', limit=2)],
            [response(card(1)+card(2)), response(DETAIL), response(status=429)])

    def clear_deadline(self):
        with self.engine.begin() as connection:
            connection.execute(text('UPDATE source_policy SET blocked_until=0, next_request_at=0, interval_floor=0'))

    def resume(self, run, replies):
        with patch('requests.Session.get', side_effect=replies) as get:
            result = self.client.post('/api/runs/'+run['id']+'/resume')
            self.assertEqual(result.status_code, 200, result.json)
            server.state.thread.join(15)
            self.assertFalse(server.state.thread.is_alive())
        return self.client.get('/api/runs/'+run['id']).json, get

    def test_repeated_429_and_restart_keep_pending_card_without_listing(self):
        original = self.paused()
        self.clear_deadline()
        second, get = self.resume(original, [response(status=429)])
        self.assertEqual(get.call_count, 1)
        self.assertTrue(get.call_args.args[0].endswith('/jobs-guest/jobs/api/jobPosting/2'))
        self.assertEqual(second['tasks'][0]['count'], 1)
        # Simulate recovery after the worker has stopped; the durable snapshot survives.
        runs.recover(self.factory)
        self.clear_deadline()
        final, get = self.resume(original, [response(DETAIL)])
        self.assertEqual(final['status'], 'finished')
        self.assertEqual(final['tasks'][0]['count'], 2)
        self.assertEqual(final['tasks'][0]['folder'], original['tasks'][0]['folder'])
        self.assertEqual(get.call_count, 1)
        with self.factory() as session:
            self.assertEqual(session.query(Job).count(), 2)
            self.assertEqual(session.query(TaskJob).count(), 2)
        report = self.client.get('/api/runs/'+original['id']+'/report').json['metrics']
        self.assertEqual(report['search_requests'], 1)
        self.assertEqual(report['network_cards'], 2)
        self.assertEqual(report['unique_collected_ids'], 2)
        self.assertEqual(report['pending_unique_details'], 0)

    def test_legacy_checkpoint_refetches_listing_and_keeps_saved_job(self):
        original = self.paused()
        with self.factory() as session:
            task = session.get(SearchTask, original['tasks'][0]['id'])
            checkpoint = json.loads(task.checkpoint)
            checkpoint.pop('page_snapshot')
            task.checkpoint = json.dumps(checkpoint)
            session.commit()
        self.clear_deadline()
        final, get = self.resume(original, [response(card(1)+card(2)), response(DETAIL)])
        self.assertEqual(final['status'], 'finished')
        self.assertEqual(final['tasks'][0]['count'], 2)
        self.assertEqual(get.call_count, 2)

    def test_checkpoint_commits_with_job_before_job_notification(self):
        observed = []
        def after_commit(kind, data):
            if kind == 'processing_result' and data.get('status') == 'saved':
                with self.factory() as session:
                    task = session.query(SearchTask).one()
                    observed.append(json.loads(task.checkpoint))
                    self.assertEqual(session.query(TaskJob).count(), 1)
        with patch('requests.Session.get', side_effect=[response(card(1)), response(DETAIL)]):
            pipeline.run_scrape(['AI'], ['Istanbul'], limit=1, emit=after_commit)
        self.assertEqual(observed[0]['collected'], 1)
        self.assertEqual(observed[0]['seen'], ['1'])
        self.assertNotIn('_checkpoint_after_save', self.client.get('/api/jobs').json['jobs'][0])

    def test_cache_decisions_preserve_expiry_change_and_force(self):
        now = [100.0]
        details = Details(clock=lambda:now[0])
        raw = dict(external_id='123', card_lines=['AI', 'Company', 'Istanbul'])
        self.assertEqual(details.lookup(raw)['reason'], 'not_cached')
        details.put(raw, 'Original description')
        self.assertEqual(details.lookup(raw)['reason'], 'fresh')
        self.assertEqual(details.lookup(raw, force=True)['reason'], 'forced_refresh')
        self.assertEqual(details.lookup(dict(raw, posted='changed'))['reason'], 'card_changed')
        now[0] += config.DETAIL_CACHE_TTL_SECONDS
        self.assertEqual(details.lookup(raw)['reason'], 'expired')
        self.assertIsNone(details.get(raw))
        self.assertEqual(details.lookup(raw, allow_stale=True)['value']['description'], 'Original description')

    def test_actual_gate_interval_is_reported_without_changing_policy(self):
        now = [100.0]
        gate = Coordinator(interval=6, clock=lambda:now[0], sleeper=lambda seconds:now.__setitem__(0,now[0]+seconds))
        with gate.transaction() as connection:
            connection.execute(text('UPDATE source_policy SET interval_floor=120'))
        state = gate.state()
        self.assertEqual(state['effective_interval'], 120)
        self.assertAlmostEqual(state['interval_with_jitter_max'], 120*(1+config.REQUEST_JITTER))
        events = []
        with patch('jobapp.transport.random.uniform', return_value=0):
            gate.release(gate.acquire())
            gate.release(gate.acquire(emit=lambda kind,data:events.append((kind,data))))
        self.assertEqual(events[-1][0], 'shared_rate_wait_finished')
        self.assertEqual(events[-1][1]['seconds'], 120)
        self.assertEqual(gate.state()['interval_floor'], 120)

    def test_wait_analysis_is_deduplicated_and_runs_only_during_source_pause(self):
        body = dict(backend='groq', during_source_wait=True)
        created = self.client.post('/api/classify', json=body).json
        repeated = self.client.post('/api/classify', json=body).json
        self.assertEqual(created['run_id'], repeated['run_id'])
        with patch.object(runs, 'start') as start:
            service.tick(server)
            start.assert_not_called()
            Coordinator().pause('Source waiting', 429, '120')
            service.tick(server)
            start.assert_called_once_with(server, created['run_id'])

    def test_wait_analysis_yields_after_five_and_respects_user_pause(self):
        self.scrape([response(''.join(card(i) for i in range(6)))]+[response(DETAIL) for _ in range(6)], 6)
        Coordinator().pause('Source waiting', 429, '120')
        created = self.client.post('/api/classify', json=dict(backend='groq', during_source_wait=True)).json
        processed = []
        def analyze(**kwargs):
            for ident in range(1, 7):
                if kwargs['should_stop']():
                    return dict(termination_reason='stopped_by_user', classified=len(processed))
                processed.append(ident)
                kwargs['emit']('processing_result', dict(status='saved', job_id=ident))
            return dict(termination_reason='completed')
        with patch.object(pipeline, 'run_classify_backfill', side_effect=analyze), patch('requests.Session.get') as network:
            with runs.lock:
                runs.start(server, created['run_id'])
            server.state.thread.join(15)
            network.assert_not_called()
        result = self.client.get('/api/runs/'+created['run_id']).json
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(len(processed), 5)
        self.assertTrue(result['automatic_resume'])
        self.assertEqual(self.client.post('/api/runs/'+created['run_id']+'/pause').status_code, 200)
        with patch.object(runs, 'start') as start:
            service.tick(server)
            start.assert_not_called()

    def test_wait_analysis_stops_starting_jobs_at_deadline(self):
        created = self.client.post('/api/classify', json=dict(backend='groq', during_source_wait=True)).json
        Coordinator().pause('Source waiting', 429, '120')
        def analyze(**kwargs):
            self.assertFalse(kwargs['should_stop']())
            with patch('time.time', return_value=time.time()+121):
                self.assertTrue(kwargs['should_stop']())
            return dict(termination_reason='stopped_by_user')
        with patch.object(pipeline, 'run_classify_backfill', side_effect=analyze):
            with runs.lock:
                runs.start(server, created['run_id'])
            server.state.thread.join(15)
        self.assertEqual(self.client.get('/api/runs/'+created['run_id']).json['status'], 'paused')

    def test_variable_page_snapshot_resume_preserves_deferred_details_and_offset(self):
        stop = [False]
        def pause_after_first(kind, data):
            if kind == 'job':
                stop[0] = True
        with patch('requests.Session.get', side_effect=[response(''.join(card(i) for i in range(25)))]) as get:
            pipeline.run_scrape(['Python'], ['Istanbul'], search_options={'defer_details':True},
                                emit=pause_after_first, should_stop=lambda:stop[0])
            self.assertEqual(get.call_count, 1)
        with self.factory() as session:
            task = session.query(SearchTask).one()
            run_id, folder, task_id = task.run_id, task.folder, task.id
            snapshot = json.loads(task.checkpoint)
            self.assertEqual(len(snapshot['page_snapshot']['cards']), 25)
            self.assertEqual(snapshot['offset'], 0)
        with patch('requests.Session.get', side_effect=[response('')]) as get:
            pipeline.run_scrape(['Python'], ['Istanbul'], checkpoint=snapshot, search_id=task_id, run_id=run_id,
                resume_folder=folder, search_options={'defer_details':True})
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs['params']['start'], 25)
        with self.factory() as session:
            self.assertEqual(session.query(Job).count(), 25)
            self.assertEqual(session.query(TaskJob).count(), 25)
            self.assertEqual(details.pending_count(session), 25)

    def test_saved_card_still_refreshes_expired_or_forced_details(self):
        for forced in (False, True):
            with self.subTest(forced=forced):
                raw = dict(external_id='999', url='https://www.linkedin.com/jobs/view/999',
                           card_layout='guest', card_lines=['AI Engineer','Company','Istanbul'])
                Details(clock=lambda:1).put(raw, 'Old description')
                checkpoint = dict(page=0, offset=0, seen=[], collected=0, page_snapshot={
                    'identity':dict(keyword='Python',location='Istanbul',options={}),
                    'page':0, 'cards':[raw], 'known_ids':[], 'request_id':'old'})
                with patch('requests.Session.get', side_effect=[response(DETAIL)]) as get:
                    result = pipeline.run_scrape(['Python'], ['Istanbul'], limit=1, checkpoint=checkpoint,
                                                refresh_details=forced)
                self.assertEqual(get.call_count, 1)
                self.assertEqual(result['new']+result['updated']+result['unchanged'], 1)
                with self.factory() as session:
                    self.assertIn('PyTorch', session.query(Job).filter_by(external_id='999').one().description)

    def test_background_analysis_waits_for_deferred_description(self):
        with patch('requests.Session.get', side_effect=[response(card(1))]):
            pipeline.run_scrape(['AI'], ['Istanbul'], limit=1, search_options={'defer_details':True})
        with patch.object(pipeline, 'classify_job', side_effect=AssertionError('description still pending')):
            result = pipeline.run_classify_backfill(backend='groq', ready_only=True, patient=False)
        self.assertEqual(result['total'], 0)

    def test_wait_notification_failure_releases_acquired_network_lease(self):
        now = [100.0]
        gate = Coordinator(interval=6, clock=lambda:now[0], sleeper=lambda seconds:now.__setitem__(0,now[0]+seconds))
        def emit(kind, data):
            if kind == 'shared_rate_wait_finished':
                raise RuntimeError('notification unavailable')
        with patch('jobapp.transport.random.uniform', return_value=0):
            gate.release(gate.acquire())
            with self.assertRaisesRegex(RuntimeError, 'notification unavailable'):
                gate.acquire(emit=emit)
        with gate.transaction() as connection:
            self.assertEqual(gate.row(connection)['lease_owner'], '')
