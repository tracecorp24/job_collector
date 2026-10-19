"""Queue controls, live outcome counts and recorded process times."""
import json
import threading
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy.orm import sessionmaker
import test_light
import test_workspace
from test_light import response, card, DETAIL
from jobapp import pipeline, runs, server
from jobapp.models import SearchRun, SearchTask, SearchEvent


class QueueControlTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown
    scrape = test_light.FullLightTests.scrape

    def seed_queue(self, started=False):
        with self.factory() as session:
            run=SearchRun(id='controls',status='paused' if started else 'queued',created_at=datetime.utcnow()-timedelta(days=1))
            task=SearchTask(id='first',run_id=run.id,keyword='AI',location='Istanbul',limit=None,status=run.status)
            if started:
                runs.transition(run,'running')
                runs.transition(task,'running')
                task.folder='existing-folder'
                runs.transition(run,'paused','Kullanıcı duraklattı.')
                runs.transition(task,'paused','Kullanıcı duraklattı.')
            session.add_all([run,task,SearchTask(id='second',run_id=run.id,keyword='Backend',location='Ankara',limit=1)])
            session.commit()

    def test_cancel_only_before_start_and_stop_preserves_history(self):
        self.seed_queue(started=True)
        self.assertEqual(self.client.post('/api/runs/controls/cancel').status_code,400)
        self.assertEqual(self.client.post('/api/runs/controls/tasks/first/cancel').status_code,400)
        self.assertEqual(self.client.post('/api/runs/controls/tasks/second/cancel').status_code,200)
        self.assertEqual(self.client.post('/api/runs/controls/tasks/first/stop').status_code,200)
        result=self.client.get('/api/runs/controls').json
        self.assertEqual(result['status'],'stopped')
        self.assertEqual([t['status'] for t in result['tasks']],['stopped','cancelled'])
        self.assertEqual(result['tasks'][0]['folder'],'existing-folder')
        self.assertEqual(self.client.post('/api/runs/controls/resume').status_code,400)

    def test_cancel_unstarted_queue_and_record_reason(self):
        self.seed_queue()
        self.assertEqual(self.client.post('/api/runs/controls/cancel').status_code,200)
        result=self.client.get('/api/runs/controls').json
        self.assertEqual(result['status'],'cancelled')
        self.assertFalse(result['has_started'])
        self.assertTrue(all(t['status']=='cancelled' for t in result['tasks']))
        self.assertIn('başlamadan',result['status_reason'])

    def test_live_counts_pause_and_resume_unlimited_query(self):
        self.scrape([response(card(1)),response(DETAIL)],1)
        entered,release=threading.Event(),threading.Event()
        def blocked_detail(*args,**kwargs):
            entered.set()
            self.assertTrue(release.wait(10))
            return response(DETAIL)
        replies=[response(card(1)+card(2)),blocked_detail]
        def get(*args,**kwargs):
            result=replies.pop(0)
            return result(*args,**kwargs) if callable(result) else result
        with patch('requests.Session.get',side_effect=get):
            start=self.client.post('/api/scrape',json={'tasks':[{'id':'live','keyword':'AI','location':'Istanbul','limit':None}]})
            run_id=start.json['run_id']
            try:
                self.assertTrue(entered.wait(10))
                live=self.client.get('/api/runs/'+run_id).json
                self.assertEqual(live['status'],'running')
                self.assertEqual(live['tasks'][0]['stats']['unchanged'],1)
                self.assertEqual(live['stats']['unchanged'],1)
                self.assertIsNotNone(live['started_at'])
                self.assertIsNotNone(live['tasks'][0]['started_at'])
                self.assertEqual(self.client.post('/api/runs/'+run_id+'/cancel').status_code,400)
                self.assertEqual(self.client.post('/api/runs/'+run_id+'/tasks/live/pause').status_code,200)
            finally:
                release.set()
                server.state.thread.join(10)
        paused=self.client.get('/api/runs/'+run_id).json
        self.assertEqual(paused['status'],'paused')
        self.assertIn('duraklat',paused['tasks'][0]['status_reason'])
        self.assertEqual(paused['tasks'][0]['count'],1)
        with patch('requests.Session.get',side_effect=[response(DETAIL),response('')]):
            self.assertEqual(self.client.post('/api/runs/'+run_id+'/tasks/live/resume').status_code,200)
            server.state.thread.join(10)
        finished=self.client.get('/api/runs/'+run_id).json
        self.assertEqual(finished['status'],'finished')
        self.assertEqual(finished['started_at'],paused['started_at'])
        self.assertEqual(finished['tasks'][0]['stats']['new'],1)
        self.assertEqual(finished['tasks'][0]['stats']['unchanged'],1)
        self.assertIsNotNone(finished['ended_at'])

    def test_stop_current_query_continues_next_and_cancel_waiting_query(self):
        entered,release=threading.Event(),threading.Event()
        def blocked(*args,**kwargs):
            entered.set()
            self.assertTrue(release.wait(10))
            return response(DETAIL)
        replies=[response(card(1)),blocked,response(card(2)),response(DETAIL)]
        def get(*args,**kwargs):
            result=replies.pop(0)
            return result(*args,**kwargs) if callable(result) else result
        with patch('requests.Session.get',side_effect=get):
            start=self.client.post('/api/scrape',json={'tasks':[{'id':'one','keyword':'AI','limit':None},{'id':'two','keyword':'Backend','limit':1},{'id':'three','keyword':'Cancelled','limit':1}]})
            run_id=start.json['run_id']
            try:
                self.assertTrue(entered.wait(10))
                self.assertEqual(self.client.post(f'/api/runs/{run_id}/tasks/three/cancel').status_code,200)
                self.assertEqual(self.client.post(f'/api/runs/{run_id}/tasks/one/stop').status_code,200)
            finally:
                release.set()
                server.state.thread.join(10)
        result=self.client.get('/api/runs/'+run_id).json
        self.assertEqual(result['status'],'finished')
        self.assertEqual([t['status'] for t in result['tasks']],['stopped','finished','cancelled'])
        self.assertEqual(result['stats']['new'],1)
        self.assertEqual(result['tasks'][1]['count'],1)

    def test_start_time_is_not_queue_creation_and_pause_reason_survives_restart(self):
        self.seed_queue(started=True)
        first=self.client.get('/api/runs/controls').json
        self.assertNotEqual(first['started_at'],first['created_at'])
        self.assertIn('duraklattı',first['status_reason'])
        self.assertGreaterEqual(first['elapsed_seconds'],first['active_seconds'])
        with self.factory() as session:
            run=session.get(SearchRun,'controls')
            runs.transition(run,'running')
            runs.transition(session.get(SearchTask,'first'),'running')
            session.commit()
        runs.recover(self.factory)
        recovered=self.client.get('/api/runs/controls').json
        self.assertEqual(recovered['status'],'paused')
        self.assertEqual(recovered['started_at'],first['started_at'])
        self.assertIn('yeniden başlatıldığı',recovered['status_reason'])

    def test_stop_paused_entire_queue(self):
        self.seed_queue(started=True)
        self.assertEqual(self.client.post('/api/runs/controls/stop').status_code,200)
        run=self.client.get('/api/runs/controls').json
        self.assertEqual(run['status'],'stopped')
        self.assertTrue(all(t['status']=='stopped' for t in run['tasks']))
        self.assertIsNotNone(run['ended_at'])

    def test_cli_records_start_and_end_with_production_session_settings(self):
        factory=sessionmaker(bind=self.engine,autoflush=False)
        with patch.object(pipeline,'SessionLocal',factory):
            result,events,_=self.scrape([response(card(5)),response(DETAIL)],1)
        self.assertEqual(result['new'],1)
        self.assertNotIn('error',[kind for kind,_ in events])
        with self.factory() as session:
            run=session.query(SearchRun).one()
            task=session.query(SearchTask).one()
            self.assertIsNotNone(run.started_at)
            self.assertIsNotNone(run.ended_at)
            self.assertIsNotNone(task.started_at)
            self.assertIsNotNone(task.ended_at)

    def test_start_while_busy_or_source_paused_schedules_instead_of_running(self):
        from jobapp import service
        from jobapp.transport import Coordinator
        self.seed_queue()
        with patch.object(server.state,'running',True), patch.object(runs,'start') as start:
            result=self.client.post('/api/runs/controls/resume')
            self.assertEqual(result.status_code,200)
            self.assertTrue(result.json['scheduled'])
            start.assert_not_called()
            waiting=self.client.get('/api/scrape/status').json['waiting']
        self.assertEqual([w['id'] for w in waiting],['controls'])
        self.assertEqual([t['keyword'] for t in waiting[0]['tasks']],['AI','Backend'])
        self.assertEqual(self.client.get('/api/runs/controls').json['status'],'queued')
        # Kaynak beklemesi sürerken servis sıradaki kuyruğu başlatmaz; sonra başlatır.
        Coordinator().pause('Kaynak erişimi sınırlandırdı (HTTP 429).',429,'600')
        with patch.object(runs,'start') as start:
            self.assertTrue(self.client.post('/api/runs/controls/resume').json['scheduled'])
            service.tick(server)
            start.assert_not_called()
        with patch.object(Coordinator,'state',return_value={'paused':False}), patch.object(runs,'start') as start:
            service.tick(server)
            start.assert_called_once_with(server,'controls')

    def test_start_scheduled_paused_run_resumes_automatically(self):
        self.seed_queue(started=True)
        with self.factory() as session:
            run=session.get(SearchRun,'controls')
            run.options=json.dumps({'user_paused':True})
            session.commit()
        with patch.object(server.state,'running',True):
            self.assertTrue(self.client.post('/api/runs/controls/resume').json['scheduled'])
        with self.factory() as session:
            options=json.loads(session.get(SearchRun,'controls').options)
        self.assertNotIn('user_paused',options)
        self.assertEqual(options['auto_resume_at'],0)
