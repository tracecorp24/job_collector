import io
import json
import unittest
from unittest.mock import patch
import test_light
import test_workspace
from test_light import response, card, DETAIL
from jobapp import audit, server, config, embed
from jobapp.models import SearchEvent, SearchTask, Job


class AuditTests(unittest.TestCase):
    setUp=test_light.FullLightTests.setUp
    tearDown=test_workspace.WorkspaceTests.tearDown
    seed=test_workspace.WorkspaceTests.seed
    start_worker=test_workspace.WorkspaceTests.start_worker

    def test_queue_ids_and_every_edit_remain_auditable(self):
        tasks=[{'id':'stable-task','keyword':'Python','location':'Ankara','limit':3}]
        created=self.client.post('/api/queue',json={'tasks':tasks})
        self.assertEqual(created.status_code,200,created.json)
        run_id=created.json['run_id']
        tasks[0]['location']='Berlin'
        changed=self.client.post('/api/queue',json={'run_id':run_id,'tasks':tasks})
        self.assertEqual(changed.status_code,200,changed.json)
        snap=self.client.get('/api/runs/'+run_id).json
        self.assertEqual(snap['status'],'queued')
        self.assertEqual(snap['tasks'][0]['id'],'stable-task')
        self.assertEqual(snap['tasks'][0]['location'],'Berlin')
        logs=self.client.get('/api/runs/'+run_id+'/logs').json['events']
        self.assertTrue(any(e['kind']=='queue_task_changed' and e['data']['before']['location']=='Ankara' for e in logs))
        removed=self.client.post('/api/queue',json={'run_id':run_id,'tasks':[]})
        self.assertIsNone(removed.json['run_id'])
        self.assertEqual(self.client.get('/api/runs/'+run_id).json['tasks'][0]['status'],'cancelled')
        self.assertEqual(self.client.get('/api/runs/'+run_id+'/logs?kind=queue_task_removed').json['events'][0]['search_id'],'stable-task')

    def test_duplicate_task_id_rejected_without_changing_first_queue(self):
        item={'id':'same','keyword':'AI','location':'Istanbul','limit':1}
        first=self.client.post('/api/queue',json={'tasks':[item]})
        second=self.client.post('/api/queue',json={'tasks':[item]})
        self.assertEqual(second.status_code,400)
        self.assertEqual(self.client.get('/api/runs/'+first.json['run_id']).json['tasks'][0]['id'],'same')

    def test_report_correlates_request_processing_and_limit(self):
        run=self.start_worker([{'keyword':'Python','location':'Ankara','limit':1}], [response(card(1)+card(2)),response(DETAIL)])
        report=self.client.get('/api/runs/'+run['id']+'/report').json
        self.assertEqual(report['metrics']['returned_cards'],2)
        self.assertEqual(report['metrics']['collected'],1)
        self.assertEqual(report['metrics']['not_processed'],1)
        self.assertEqual(report['metrics']['visible_jobs'],1)
        self.assertIn('target_reached',[f['code'] for f in report['findings']])
        events=self.client.get('/api/runs/'+run['id']+'/logs?kind=processing_stage').json['events']
        self.assertTrue(events)
        self.assertTrue(all(e['data'].get('attempt_id') for e in events))
        self.assertEqual({e['data']['stage'] for e in events},{'export','parse','classify','database'})
        requests=self.client.get('/api/runs/'+run['id']+'/logs?kind=request_finished').json['events']
        request_id=requests[0]['data']['request_id']
        matching=self.client.get('/api/runs/'+run['id']+'/logs?request_id='+request_id).json['events']
        self.assertEqual({e['kind'] for e in matching},{'request_started','request_finished'})
        self.assertEqual(self.client.get('/api/runs/'+run['id']+'/report?download=1').status_code,200)

    def test_rate_limit_report_keeps_partial_results_and_error_details(self):
        run=self.start_worker([{'keyword':'AI','location':'Istanbul','limit':2}], [response(card(1)+card(2)),response(DETAIL),response(status=429)])
        self.assertEqual(run['status'],'paused')
        result=self.client.get('/api/runs/'+run['id']+'/report').json
        self.assertIn('rate_limit',[f['code'] for f in result['findings']])
        self.assertEqual(result['metrics']['visible_jobs'],1)
        self.assertEqual(result['http_statuses']['429'],1)
        self.assertEqual(result['metrics']['source_pauses'],1)
        self.assertIn('source_paused',[f['code'] for f in result['findings']])

    def test_secret_redaction_in_nested_event_data(self):
        with patch.object(config,'ANTHROPIC_API_KEY','test-sensitive-key'),self.factory() as session:
            audit.record(session,'test-run','test-task','test',{'authorization':'Bearer secret','nested':{'api_key':'hidden'},'msg':'failure test-sensitive-key'})
            session.commit()
            event=session.query(SearchEvent).filter_by(kind='test').one()
            self.assertNotIn('test-sensitive-key',event.data)
            self.assertNotIn('Bearer secret',event.data)
            self.assertEqual(json.loads(event.data)['nested']['api_key'],'[gizlendi]')

    def test_maintenance_process_has_ids_logs_and_resumable_checkpoint(self):
        self.seed()
        def vector(*args,**kwargs):
            server.state.stop_flag=True
            return [1.0,0.0]
        with patch.object(embed,'embed_text',side_effect=vector):
            start=self.client.post('/api/embed',json={'force':True,'limit':2})
            self.assertEqual(start.status_code,200,start.json)
            server.state.thread.join(timeout=15)
        run_id=start.json['run_id']
        run=self.client.get('/api/runs/'+run_id).json
        self.assertEqual(run['kind'],'embed')
        self.assertEqual(run['status'],'paused')
        self.assertEqual(run['tasks'][0]['count'],1)
        with patch.object(embed,'embed_text',return_value=[1.0,0.0]) as get:
            self.assertEqual(self.client.post('/api/runs/'+run_id+'/resume').status_code,200)
            server.state.thread.join(timeout=15)
        self.assertEqual(get.call_count,1)
        run=self.client.get('/api/runs/'+run_id).json
        self.assertEqual(run['status'],'finished')
        self.assertEqual(run['stats']['embedded'],2)
        report=self.client.get('/api/runs/'+run_id+'/report').json
        self.assertEqual(report['metrics']['processed_jobs'],2)
        with self.factory() as session:
            self.assertTrue(session.query(SearchEvent).filter_by(run_id=run_id,kind='processing_result').count())
            self.assertTrue(all(not j.to_dict()['search_ids'] for j in session.query(Job)))


class LauncherTests(unittest.TestCase):
    def test_existing_application_opens_without_initializing_database(self):
        import run
        with patch.object(run.socket,'create_connection'),patch.object(run,'create_app') as create,patch.object(run.webbrowser,'open') as browser,patch.object(run.config,'OPEN_BROWSER',True),patch.object(run.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"running":true,"kind":"scrape"}')
            with patch('sys.stdout',new=io.StringIO()) as output:
                self.assertIsNone(run.main())
            self.assertIn('zaten çalışıyor',output.getvalue())
            create.assert_not_called()
            browser.assert_called_once()

    def test_unrelated_port_is_a_clear_error(self):
        import run
        with patch.object(run.socket,'create_connection'),patch.object(run,'create_app') as create,patch.object(run.webbrowser,'open') as browser,patch.object(run.urllib.request,'build_opener') as opener,patch('sys.stdout',new=io.StringIO()):
            opener.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"different":"app"}')
            self.assertEqual(run.main(),1)
            create.assert_not_called()
            browser.assert_not_called()
