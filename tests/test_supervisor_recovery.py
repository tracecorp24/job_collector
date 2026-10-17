"""Supervisor recovery: transient errors, unstartable queue entries, retry streak reset."""
import json
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy.exc import OperationalError
import test_light
import test_workspace
from test_light import response, card, DETAIL
from jobapp import config, pipeline, server, service, runs
from jobapp.models import SearchRun, SearchTask, SearchEvent
from jobapp.transport import SourcePaused


class Alive:
    def is_alive(self):
        return True


class SupervisorRecoveryTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown
    start_worker = test_workspace.WorkspaceTests.start_worker

    def collection(self, key, **extra):
        with patch.object(config,'ADMIN_KEY','admin'):
            created=self.client.post('/api/v1/collections',headers={'Authorization':'Bearer admin','Idempotency-Key':key},
                json=dict({'tasks':[{'keyword':key}]},**extra))
        self.assertEqual(created.status_code,202,created.json)
        return created.json['run_id']

    def events(self, ident, kind):
        with self.factory() as session:
            return session.query(SearchEvent).filter_by(run_id=ident,kind=kind).count()

    def test_successful_turn_clears_transient_error_and_health(self):
        locked=OperationalError('SELECT 1',{},Exception('database is locked'))
        with patch.object(service,'supervisor',Alive()),patch.object(service,'last_error',''), \
                patch.object(service,'tick',side_effect=[locked,None,None]):
            service.step(server)
            self.assertIn('database is locked',service.last_error)
            self.assertGreater(service.last_error_at,0)
            self.assertEqual(self.client.get('/healthz').status_code,503)
            service.step(server)
            service.heartbeat=time.time()
            self.assertEqual(service.last_error,'')
            self.assertEqual(self.client.get('/healthz').status_code,200)

    def test_unstartable_run_is_closed_and_next_candidate_starts(self):
        blocked=self.collection('blocked')
        healthy=self.collection('healthy')
        with self.factory() as session:
            for task in session.query(SearchTask).filter_by(run_id=blocked):
                runs.transition(task,'cancelled')
            session.commit()
        original=runs.start
        with patch.object(runs,'start',side_effect=lambda s,i: original(s,i) if i==blocked else None) as start:
            service.tick(server)
            self.assertEqual([c.args[1] for c in start.call_args_list],[blocked,healthy])
        with self.factory() as session:
            run=session.get(SearchRun,blocked)
            options=json.loads(run.options)
            self.assertEqual(run.status,'stopped')
            self.assertIn('Devam ettirilecek sorgu kalmadı',run.status_reason)
            self.assertNotIn('service_managed',options)
            self.assertNotIn('auto_resume_at',options)
        self.assertEqual(self.events(blocked,'automatic_resume_failed'),1)
        with patch.object(runs,'start') as start:
            service.tick(server)
            start.assert_called_once_with(server,healthy)

    def test_source_pause_during_start_leaves_run_waiting(self):
        ident=self.collection('waiting')
        with patch.object(runs,'start',side_effect=SourcePaused({'message':'Kaynak beklemede.','paused':True})):
            service.tick(server)
        with self.factory() as session:
            run=session.get(SearchRun,ident)
            self.assertEqual(run.status,'queued')
            self.assertTrue(json.loads(run.options)['service_managed'])
        self.assertEqual(self.events(ident,'automatic_resume_failed'),0)

    def test_schedule_without_finished_tasks_creates_no_empty_round(self):
        ident=self.collection('empty',repeat_seconds=900)
        with self.factory() as session:
            run=session.get(SearchRun,ident)
            runs.transition(run,'finished')
            run.ended_at=datetime.utcnow()-timedelta(seconds=1000)
            runs.transition(session.query(SearchTask).filter_by(run_id=ident).one(),'cancelled')
            session.commit()
        service.tick(server)
        service.tick(server)
        with self.factory() as session:
            self.assertEqual(session.query(SearchRun).count(),1)
            options=json.loads(session.get(SearchRun,ident).options)
            self.assertFalse(options['schedule_enabled'])
            self.assertNotIn('schedule_dispatched',options)
        self.assertEqual(self.events(ident,'scheduled_run_skipped'),1)

    def test_error_retry_streak_resets_after_success(self):
        with patch.object(pipeline,'process_raw',side_effect=RuntimeError('model unavailable')):
            run=self.start_worker([dict(keyword='AI',location='Istanbul',limit=1)],[response(card(1)),response(DETAIL)])
        with self.factory() as session:
            item=session.get(SearchRun,run['id'])
            self.assertEqual(json.loads(item.options)['error_retry_streak'],1)
            item.options=json.dumps(dict(json.loads(item.options),error_retry_streak=5))
            session.commit()
        with patch('requests.Session.get',side_effect=[response(card(1)),response(DETAIL)]):
            self.assertEqual(self.client.post('/api/runs/'+run['id']+'/resume').status_code,200)
            server.state.thread.join(10)
        with self.factory() as session:
            item=session.get(SearchRun,run['id'])
            self.assertEqual(item.status,'finished')
            self.assertNotIn('error_retry_streak',json.loads(item.options))
            runs.transition(item,'error','Geçici hata')
            runs.schedule_error_retry(session,item)
            self.assertEqual(json.loads(item.options)['error_retry_streak'],1)
            self.assertLess(json.loads(item.options)['auto_resume_at'],time.time()+301)


if __name__ == '__main__':
    unittest.main()
