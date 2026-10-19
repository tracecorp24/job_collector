"""Audit regressions and autonomous service integration, no external HTTP."""
import json
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text
import test_light
import test_workspace
from test_light import response, card, DETAIL
from jobapp import config, db, pipeline, server, service, runs
from jobapp.models import Job, SearchRun, SearchTask
from jobapp.transport import Coordinator


class ServiceTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown
    scrape = test_light.FullLightTests.scrape
    start_worker = test_workspace.WorkspaceTests.start_worker

    def test_stale_autosave_preserves_cancelled_task(self):
        tasks = [dict(id='first',keyword='AI'),dict(id='second',keyword='Backend')]
        ident = self.client.post('/api/queue',json={'tasks':tasks}).json['run_id']
        self.assertEqual(self.client.post(f'/api/runs/{ident}/tasks/first/cancel').status_code,200)
        self.assertEqual(self.client.post('/api/queue',json={'run_id':ident,'tasks':tasks}).status_code,200)
        self.assertEqual(self.client.get('/api/runs/'+ident).json['tasks'][0]['status'],'cancelled')

    def test_processing_failure_preserves_pending_job_for_resume(self):
        with patch.object(pipeline,'process_raw',side_effect=RuntimeError('processing failure')):
            result, events, _ = self.scrape([response(card(1)),response(DETAIL)],1)
        with self.factory() as session:
            task = session.query(SearchTask).one()
            ident = task.run_id
            checkpoint = json.loads(task.checkpoint)
            self.assertEqual(checkpoint['collected'],0)
            self.assertNotIn('1',checkpoint['seen'])
            self.assertEqual(session.query(Job).count(),0)
            self.assertEqual(task.status,'error')
        with patch('requests.Session.get',side_effect=AssertionError('valid cached detail must be reused')) as get:
            self.assertEqual(self.client.post('/api/runs/'+ident+'/resume').status_code,200)
            server.state.thread.join(10)
        get.assert_not_called()
        self.assertEqual(self.client.get('/api/runs/'+ident).json['tasks'][0]['count'],1)

    def test_changed_content_invalidates_embedding(self):
        self.scrape([response(card(1)),response(DETAIL)],1)
        with self.factory() as session:
            session.query(Job).one().embedding='[1,0]'
            session.commit()
        with patch('requests.Session.get',side_effect=[response(card(1)),response(DETAIL.replace('PyTorch','Accounting'))]):
            pipeline.run_scrape(['AI'],['Istanbul'],limit=1,refresh_details=True)
        with self.factory() as session:
            self.assertIsNone(session.query(Job).one().embedding)

    def paused(self):
        return self.start_worker([dict(keyword='AI',location='Istanbul',limit=2)],
            [response(card(1)+card(2)),response(DETAIL),response(status=429,**{'Retry-After':'120'})])

    def meta(self, task):
        return json.loads((Path(config.ACCOUNTLESS_OUTPUT_DIR)/task['folder']/'search.json').read_text(encoding='utf-8'))

    def test_stop_syncs_export_and_disables_auto_resume(self):
        run=self.paused()
        self.assertEqual(self.client.post('/api/runs/'+run['id']+'/stop').status_code,200)
        meta=self.meta(run['tasks'][0])
        self.assertEqual(meta['status'],'stopped')
        self.assertEqual(meta['terminationReason'],'stopped_by_user')
        with patch.object(runs,'start') as start:
            service.tick(server,now=time.time()+1000)
            start.assert_not_called()

    def test_limit_edit_syncs_immediately_and_on_resume(self):
        run=self.paused(); task=run['tasks'][0]
        self.assertEqual(self.client.patch('/api/runs/'+run['id'],json={'tasks':[dict(id=task['id'],keyword='AI',location='Istanbul',limit=3)]}).status_code,200)
        self.assertEqual(self.meta(task)['limit'],3)
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE source_policy SET blocked_until=0'))
        with patch('requests.Session.get',side_effect=[response(DETAIL),response(card(3)),response(DETAIL)]):
            self.client.post('/api/runs/'+run['id']+'/resume')
            server.state.thread.join(10)
        self.assertEqual(self.meta(task)['limit'],3)

    def test_supervisor_waits_then_resumes_same_run(self):
        run=self.paused()
        with patch.object(runs,'start') as start:
            service.tick(server)
            start.assert_not_called()
            with self.engine.begin() as conn:
                conn.execute(text('UPDATE source_policy SET blocked_until=0,manual_pause=1'))
            service.tick(server,now=time.time()+1000)
            start.assert_called_once_with(server,run['id'])

    def test_user_pause_prevents_automatic_resume(self):
        run=self.paused()
        self.assertEqual(self.client.post('/api/runs/'+run['id']+'/pause').status_code,200)
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE source_policy SET blocked_until=0'))
        with patch.object(runs,'start') as start:
            service.tick(server,now=time.time()+1000)
            start.assert_not_called()

    def test_changes_auth_cursor_provenance_and_tombstones(self):
        self.assertEqual(self.client.get('/api/v1/jobs/changes').status_code,401)
        with patch.object(config,'API_KEY','reader'),patch.object(config,'ADMIN_KEY','admin'):
            headers={'Authorization':'Bearer reader'}
            self.scrape([response(card(1)),response(DETAIL)],1)
            first=self.client.get('/api/v1/jobs/changes?limit=1',headers=headers).json
            self.assertTrue(first['has_more'])
            second=self.client.get('/api/v1/jobs/changes?after='+str(first['next_cursor']),headers=headers).json
            self.assertTrue(second['items'][-1]['job']['search_ids'])
            cursor=second['next_cursor']
            with self.factory() as session:
                job=session.query(Job).one()
                job.title='rolled back'
                session.flush()
                session.rollback()
            self.assertEqual(self.client.get(f'/api/v1/jobs/changes?after={cursor}',headers=headers).json['items'],[])
            with self.factory() as session:
                job=session.query(Job).one()
                job.deleted_at=datetime.utcnow()
                session.commit()
            change=self.client.get(f'/api/v1/jobs/changes?after={cursor}',headers=headers).json['items'][0]
            self.assertEqual(change['operation'],'delete')
            self.assertIsNone(change['job'])
            self.assertEqual(self.client.get('/api/v1/jobs?limit=501',headers=headers).status_code,400)
            self.assertEqual(self.client.post('/api/v1/collections',headers=headers,json={'tasks':[{'keyword':'AI'}]}).status_code,401)

    def test_enqueue_idempotency_and_recurring_history(self):
        with patch.object(config,'ADMIN_KEY','admin'):
            headers={'Authorization':'Bearer admin','Idempotency-Key':'daily-ai'}
            body={'tasks':[{'keyword':'AI'}],'repeat_seconds':900}
            created=self.client.post('/api/v1/collections',headers=headers,json=body)
            self.assertEqual(created.status_code,202,created.json)
            ident=created.json['run_id']
            self.assertEqual(self.client.post('/api/v1/collections',headers=headers,json=body).json['run_id'],ident)
            self.assertEqual(self.client.post('/api/v1/collections',headers=headers,json=dict(body,repeat_seconds=1000)).status_code,409)
            with patch.object(runs,'start') as start:
                service.tick(server)
                start.assert_called_once_with(server,ident)
            with self.factory() as session:
                run=session.get(SearchRun,ident)
                runs.transition(run,'finished')
                run.ended_at=datetime.utcnow()-timedelta(seconds=1000)
                task=session.query(SearchTask).filter_by(run_id=ident).one()
                runs.transition(task,'finished')
                session.commit()
            service.tick(server)
            with self.factory() as session:
                self.assertEqual(session.query(SearchRun).count(),2)
                successor=json.loads(session.get(SearchRun,ident).options)['schedule_dispatched']
                self.assertNotEqual(successor,ident)
            with patch.object(runs,'start'):
                service.tick(server)
            with self.factory() as session:
                self.assertEqual(session.query(SearchRun).count(),2)
            disabled=self.client.post('/api/v1/collections/'+ident+'/disable-schedule',headers=headers)
            self.assertEqual(disabled.status_code,200)
            with self.factory() as session:
                self.assertEqual(session.get(SearchRun,successor).status,'cancelled')
                self.assertFalse(json.loads(session.get(SearchRun,ident).options)['schedule_enabled'])

    def test_error_retry_is_durable_and_respects_user_pause(self):
        with patch.object(pipeline,'process_raw',side_effect=RuntimeError('model unavailable')):
            run=self.start_worker([dict(keyword='AI',location='Istanbul',limit=1)], [response(card(1)),response(DETAIL)])
        self.assertEqual(run['status'],'error')
        self.assertTrue(run['automatic_resume'])
        self.assertGreater(run['next_attempt_at'],time.time())
        with patch.object(runs,'start') as start:
            service.tick(server)
            start.assert_not_called()
            service.tick(server,now=time.time()+301)
            start.assert_called_once_with(server,run['id'])
        self.assertEqual(self.client.post('/api/runs/'+run['id']+'/pause').status_code,200)
        with patch.object(runs,'start') as start:
            service.tick(server,now=time.time()+1000)
            start.assert_not_called()

    def test_cancel_all_parks_everything_until_user_resumes(self):
        waiting=self.paused()
        draft=self.client.post('/api/queue',json={'tasks':[{'id':'draft','keyword':'Taslak'}]}).json['run_id']
        with patch.object(config,'ADMIN_KEY','admin'):
            service_run=self.client.post('/api/v1/collections',headers={'Authorization':'Bearer admin','Idempotency-Key':'servis'},
                json={'tasks':[{'keyword':'Servis'}],'repeat_seconds':900}).json['run_id']
        watch=self.client.post('/api/watches',json={'keywords':['AI'],'locations':['Istanbul']}).json['watch']['id']
        result=self.client.post('/api/queue/cancel-all')
        self.assertEqual(result.status_code,200)
        self.assertEqual((result.json['paused'],result.json['watches_disabled']),(2,1))
        with self.factory() as session:
            for ident in (waiting['id'],service_run):
                run=session.get(SearchRun,ident)
                options=json.loads(run.options)
                self.assertEqual(run.status,'paused')
                self.assertTrue(options['user_paused'])
                self.assertFalse(options['schedule_enabled'])
                self.assertNotIn('auto_resume_at',options)
            self.assertEqual(session.get(SearchRun,draft).status,'queued')
            count=session.query(SearchRun).count()
        self.assertFalse(self.client.get('/api/watches').json['watches'][0]['enabled'])
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE source_policy SET blocked_until=0'))
        with patch.object(runs,'start') as start:
            service.tick(server,now=time.time()+100000)
            start.assert_not_called()
        with self.factory() as session:
            self.assertEqual(session.query(SearchRun).count(),count)
        with patch.object(runs,'start') as start:
            self.assertEqual(self.client.post('/api/runs/'+waiting['id']+'/resume').status_code,200)
            start.assert_called_once_with(server,waiting['id'])

    def test_cross_origin_control_rejected(self):
        result=self.client.post('/api/queue',headers={'Origin':'https://unrelated.example'},json={'tasks':[{'keyword':'AI'}]})
        self.assertEqual(result.status_code,403)
