"""Persistent request policy, cache invalidation and safe resume behavior."""
import threading
import time
import unittest
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import patch
from sqlalchemy import text
import test_light
import test_workspace
from test_light import card, response, DETAIL
from jobapp import config, pipeline, server
from jobapp.models import Job, TaskJob
from jobapp.transport import Coordinator, Details, HTTPTransport, SourcePaused, retry_after_seconds
from jobapp.scraper.accountless import AccountlessScraper


class TransportTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    scrape = test_light.FullLightTests.scrape
    start_worker = test_workspace.WorkspaceTests.start_worker
    tearDown = test_workspace.WorkspaceTests.tearDown

    def test_retry_after_seconds_and_http_dates(self):
        now = 1700000000
        self.assertEqual(retry_after_seconds('120', now), 120)
        self.assertEqual(retry_after_seconds('0', now), 0)
        date = format_datetime(datetime.fromtimestamp(now+3600, timezone.utc), usegmt=True)
        self.assertEqual(retry_after_seconds(date, now), 3600)
        self.assertEqual(retry_after_seconds(date, now+7200), 0)
        for invalid in (None, '', '-1', '1.5', 'NaN', 'tomorrow'):
            self.assertIsNone(retry_after_seconds(invalid, now))

    def test_cache_survives_instances_and_expiry_and_card_changes(self):
        now = [1000.0]
        raw = dict(external_id='1', card_lines=['Developer','Company','City'])
        Details(clock=lambda:now[0]).put(raw, 'Description')
        cached = Details(clock=lambda:now[0]).get(raw)
        self.assertEqual(cached['description'], 'Description')
        self.assertIsNone(Details(clock=lambda:now[0]).get(raw, force=True))
        self.assertIsNone(Details(clock=lambda:now[0]).get(dict(raw, posted='2026-10-16')))
        now[0] += config.DETAIL_CACHE_TTL_SECONDS
        self.assertIsNone(Details(clock=lambda:now[0]).get(raw))

    def test_missing_details_have_short_cache(self):
        raw = dict(external_id='404', card_lines=[])
        Details(clock=lambda:100).put(raw, '', 404)
        self.assertEqual(Details(clock=lambda:101).get(raw)['status'],404)
        self.assertIsNone(Details(clock=lambda:100+config.DETAIL_MISSING_TTL_SECONDS).get(raw))

    def test_incremental_preserves_analysis_and_adds_search_provenance(self):
        self.scrape([response(card(1)),response(DETAIL)],1)
        with self.factory() as session:
            job = session.query(Job).one()
            original_created = job.created_at
            job.summary = 'Preserved analysis'
            job.embedding = '[1,0]'
            session.commit()
        with patch.object(pipeline,'process_raw',side_effect=AssertionError('must not reclassify')):
            result, events, get = self.scrape([response(card(1))],1)
        self.assertEqual(result['unchanged'],1)
        self.assertEqual(get.call_count,1)
        self.assertIn('cache_hit',[kind for kind,_ in events])
        with self.factory() as session:
            job = session.query(Job).one()
            self.assertEqual(job.summary,'Preserved analysis')
            self.assertEqual(job.created_at,original_created)
            self.assertEqual(session.query(TaskJob).count(),2)
            self.assertEqual(session.query(TaskJob).filter_by(outcome='unchanged').count(),1)

    def test_force_refresh_detects_description_changes(self):
        self.scrape([response(card(1)),response(DETAIL)],1)
        with patch('requests.Session.get',side_effect=[response(card(1)),response(DETAIL.replace('PyTorch','SQL'))]) as get:
            result = pipeline.run_scrape(['AI'],['Istanbul'],limit=1,refresh_details=True)
        self.assertEqual(result['updated'],1)
        self.assertEqual(get.call_count,2)

    def test_full_mode_reanalyzes_but_keeps_valid_detail_cache(self):
        self.scrape([response(card(1)),response(DETAIL)],1)
        with patch('requests.Session.get',side_effect=[response(card(1))]) as get:
            result = pipeline.run_scrape(['AI'],['Istanbul'],limit=1,mode='full')
        self.assertEqual(result['updated'],1)
        self.assertEqual(get.call_count,1)

    def test_shared_gate_and_cancelled_wait(self):
        now = [100.0]
        one = Coordinator(interval=5,clock=lambda:now[0],sleeper=lambda n:now.__setitem__(0,now[0]+n))
        two = Coordinator(interval=5,clock=lambda:now[0],sleeper=lambda n:now.__setitem__(0,now[0]+n))
        owner = one.acquire()
        one.release(owner)
        owner = two.acquire()
        self.assertGreaterEqual(now[0],105)
        two.release(owner)
        self.assertIsNone(one.acquire(should_stop=lambda:True))

    def test_borrowed_transport_keeps_session_identity_and_sequence(self):
        transport = HTTPTransport()
        events = []
        try:
            for external_id in ("501", "502"):
                scraper = AccountlessScraper(transport=transport, max_retries=0,
                    request_context={"task_id":external_id, "attempt_id":f"attempt-{external_id}",
                                     "queue_layer":"routine", "request_reason":"routine_search"},
                    emit=lambda kind, data: events.append((kind, data)))
                self.assertFalse(scraper.owns_transport)
                with patch("requests.Session.get", return_value=response(DETAIL)):
                    soup = scraper._get(scraper.detail_url({"external_id":external_id}))
                self.assertIsNotNone(soup)
            started = [data for kind,data in events if kind == "request_started"]
            finished = [data for kind,data in events if kind == "request_finished"]
            self.assertEqual([x["session_request_number"] for x in started], [1,2])
            self.assertEqual({x["transport_session_id"] for x in started}, {transport.session_id})
            self.assertEqual({x["process_id"] for x in started}, {transport.process_id})
            self.assertEqual([x["task_id"] for x in started], ["501","502"])
            self.assertEqual([x["semantic_outcome"] for x in finished], ["description_available"]*2)
            self.assertFalse(transport._closed)
        finally:
            transport.close()

    def test_http_200_challenge_is_not_semantic_success(self):
        events = []
        transport = HTTPTransport()
        scraper = AccountlessScraper(transport=transport, max_retries=0,
                                     emit=lambda kind,data:events.append((kind,data)))
        try:
            with patch("requests.Session.get", return_value=response("<html><title>Security verification</title></html>")):
                with self.assertRaises(SourcePaused):
                    scraper._get(scraper.detail_url({"external_id":"503"}))
            finished = [data for kind,data in events if kind == "request_finished"]
            self.assertEqual(len(finished),1)
            self.assertEqual(finished[0]["http_status"],200)
            self.assertEqual(finished[0]["semantic_outcome"],"security_challenge")
            self.assertEqual(finished[0]["cooldown_origin"],"local_fallback")
            self.assertEqual(scraper.access_denied_requests,1)
            self.assertTrue(Coordinator().state()["paused"])
        finally:
            transport.close()

    def test_lease_renewal_and_release_are_fenced_to_owner(self):
        coordinator = Coordinator()
        owner = coordinator.acquire()
        self.assertTrue(coordinator.renew(owner))
        with coordinator.transaction() as connection:
            connection.execute(text("UPDATE source_policy SET lease_owner='new-owner', lease_until=9999999999 WHERE source='linkedin'"))
        self.assertFalse(coordinator.renew(owner))
        coordinator.release(owner)
        with coordinator.transaction() as connection:
            self.assertEqual(coordinator.row(connection)["lease_owner"], "new-owner")

    def test_concurrent_clients_are_serialized(self):
        coordinator = Coordinator(interval=.05)
        timestamps, errors = [], []
        def request():
            try:
                owner=coordinator.acquire()
                timestamps.append(time.time())
                time.sleep(.08)
                coordinator.release(owner)
            except Exception as exc:
                errors.append(exc)
        threads=[threading.Thread(target=request) for _ in range(3)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertFalse(errors)
        self.assertEqual(len(timestamps),3)
        self.assertTrue(all(b-a >= .075 for a,b in zip(timestamps,timestamps[1:])))

    def test_hard_block_shared_across_instances_and_ack_cannot_shorten_wait(self):
        now=[100.0]
        one=Coordinator(clock=lambda:now[0])
        one.pause('Security challenge',403,hard=True)
        two=Coordinator(clock=lambda:now[0])
        with self.assertRaises(SourcePaused): two.acquire()
        with self.assertRaises(SourcePaused): two.acknowledge()
        now[0]+=config.ACCESS_PAUSE_SECONDS+1
        self.assertFalse(two.state()['paused'])
        self.assertFalse(two.state()['acknowledge_allowed'])
        self.assertTrue(two.state()['automatic_resume'])

    def test_repeated_429_escalates_and_http_date_is_persistent(self):
        now=[1000.0]
        coordinator=Coordinator(clock=lambda:now[0])
        date=format_datetime(datetime.fromtimestamp(1100,timezone.utc),usegmt=True)
        state=coordinator.pause('Rate limit',429,date)
        self.assertEqual(state['remaining_seconds'],100)
        for _ in range(config.ACCESS_FAILURE_THRESHOLD-1):
            now[0]+=101
            state=coordinator.pause('Rate limit',429,'1')
        self.assertFalse(state['manual_pause'])
        self.assertGreaterEqual(state['remaining_seconds'],config.ACCESS_PAUSE_SECONDS)

    def test_pause_evidence_persists_and_separates_local_from_reported_delay(self):
        coordinator = Coordinator(clock=lambda:1000)
        state = coordinator.pause('Rate limit', 429)
        self.assertEqual(state['cooldown_origin'], 'local_fallback')
        self.assertIsNone(state['reported_retry_after_seconds'])
        deadline = state['blocked_until']
        reread = Coordinator(clock=lambda:1001).state()
        self.assertEqual(reread['blocked_until'], deadline)
        self.assertEqual(reread['cooldown_origin'], 'local_fallback')
        state = coordinator.pause('Rate limit', 429, '7200')
        self.assertEqual(state['cooldown_origin'], 'retry_after')
        self.assertEqual(state['reported_retry_after_seconds'], 7200)
        self.assertEqual(state['applied_pause_seconds'], 7200)
        local = Coordinator(source='network-test', clock=lambda:1000).pause('Network retry',
            retry_after='30', violation=False, retry_after_is_local=True)
        self.assertEqual(local['applied_pause_seconds'], 30)
        self.assertIsNone(local['reported_retry_after_seconds'])
        self.assertEqual(local['cooldown_origin'], 'local_fallback')

    def test_escalated_reported_delay_and_legacy_wait_are_honest(self):
        coordinator = Coordinator(clock=lambda:1000)
        for _ in range(config.ACCESS_FAILURE_THRESHOLD):
            state = coordinator.pause('Rate limit', 429, '1')
        self.assertEqual(state['cooldown_origin'], 'retry_after_and_local_policy')
        self.assertGreater(state['applied_pause_seconds'], 1)
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM settings WHERE key='source_pause_evidence_linkedin'"))
        self.assertEqual(coordinator.state()['cooldown_origin'], 'legacy_unknown')

    def test_source_pause_keeps_pending_detail_and_resume_same_task(self):
        run=self.start_worker([dict(keyword='AI',location='Istanbul',limit=2)],
            [response(card(1)+card(2)),response(DETAIL),response(status=429,**{'Retry-After':'120'})])
        self.assertEqual(run['status'],'paused')
        task=run['tasks'][0]
        self.assertEqual(task['count'],1)
        with patch('requests.Session.get') as get:
            # Kaynak beklerken başlatma isteği sıraya alınır; hiçbir istek gönderilmez.
            blocked=self.client.post('/api/runs/'+run['id']+'/resume')
            self.assertEqual(blocked.status_code,200)
            self.assertTrue(blocked.json['scheduled'])
            self.assertEqual(self.client.post('/api/source/acknowledge').status_code,409)
            get.assert_not_called()
        # Advance persisted test-only deadline; production never bypasses it.
        with self.engine.begin() as connection:
            connection.execute(text('UPDATE source_policy SET blocked_until=0'))
        with patch('requests.Session.get',side_effect=[response(DETAIL)]) as get:
            self.assertEqual(self.client.post('/api/runs/'+run['id']+'/resume').status_code,200)
            server.state.thread.join(10)
        result=self.client.get('/api/runs/'+run['id']).json
        self.assertEqual(result['status'],'finished')
        self.assertEqual(result['tasks'][0]['id'],task['id'])
        self.assertEqual(result['tasks'][0]['folder'],task['folder'])
        self.assertEqual(result['tasks'][0]['count'],2)
        self.assertEqual(get.call_count,1)
        self.assertTrue(get.call_args.args[0].endswith('/jobs-guest/jobs/api/jobPosting/2'))

    def test_invalid_mode_rejected(self):
        result=self.client.post('/api/queue',json={'tasks':[{'keyword':'AI'}],'mode':'invalid'})
        self.assertEqual(result.status_code,400)
