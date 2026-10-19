"""Behavioral tests for filters, discovery provenance, resume, logs and trash."""
import json
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text

import test_light
from test_light import card, response, DETAIL
from jobapp import db, pipeline, server, runs
from jobapp.models import Job, SearchRun, SearchTask, TaskJob, SearchEvent, Setting


class WorkspaceTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    scrape = test_light.FullLightTests.scrape

    def tearDown(self):
        if server.state.thread and server.state.thread.is_alive():
            server.state.stop_flag = True
            server.state.thread.join(timeout=5)
        server.state.run_id = None
        server.state.stop_flag = False

    def seed(self):
        with self.factory() as session:
            session.add_all([
                Job(source="linkedin", external_id="a", title="Kıdemli Python geliştirici", company="Örnek Şirket", location="Istanbul", category="Engineering", seniority="Senior", workplace_type="Remote", tags='["Python", "SQL"]', description="Python ve SQL, en az 5 yıl deneyim", experience_years=5, salary="100000 TRY aylık", salary_min=100000, salary_max=120000, salary_currency="TRY", salary_period="month", posted_at=datetime.utcnow()),
                Job(source="linkedin", external_id="b", title="Python Developer", company="Other", location="Ankara", category="Engineering", seniority="Mid", workplace_type="Hybrid", tags='["Python", "Java"]', experience_years=3, salary="120000 USD yıllık", salary_min=120000, salary_max=150000, salary_currency="USD", salary_period="year", description="Java Python satış", posted_at=datetime.utcnow()-timedelta(days=90)),
                Job(source="linkedin", external_id="c", title="Designer", company="Studio", location="Berlin", category="Design", seniority="Junior", workplace_type="Onsite", tags='["CSS"]', description="", flag="scam"),
            ])
            session.commit()

    def get_jobs(self, query=""):
        result = self.client.get('/api/jobs?'+query)
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def start_worker(self, tasks, replies):
        with patch('requests.Session.get', side_effect=replies):
            response_ = self.client.post('/api/scrape', json={'tasks':tasks})
            self.assertEqual(response_.status_code, 200, response_.json)
            server.state.thread.join(timeout=15)
            self.assertFalse(server.state.thread.is_alive())
        return self.client.get('/api/runs/'+response_.json['run_id']).json

    def test_layered_multi_filters_and_exact_skill_membership(self):
        self.seed()
        result = self.get_jobs('category=Engineering&location=Istanbul&location=Ankara&workplace=Remote&workplace=Hybrid&skills=Python&skills=SQL&skill_mode=all&experience_min=4&exclude=satış')
        self.assertEqual([j['external_id'] for j in result['jobs']], ['a'])
        self.assertEqual(self.get_jobs('skills=Py')['total'], 0)
        self.assertEqual(self.get_jobs('skills=Python&exclude_skills=Java')['total'], 1)
        self.assertEqual(self.get_jobs('search=KIDEMLI')['total'], 1)
        self.assertEqual(self.get_jobs('company_text=ornek')['total'], 1)
        self.assertEqual(self.get_jobs('location_text=istan')['total'], 1)
        self.assertEqual(self.get_jobs('location_text=ankara')['total'], 1)
        self.assertEqual(self.get_jobs('location_text=izmir')['total'], 0)

    def test_date_missing_content_and_salary_units(self):
        self.seed()
        today=datetime.utcnow().date().isoformat()
        self.assertEqual(self.get_jobs('posted_from='+today)['total'], 1)
        self.assertEqual(self.get_jobs('posted_missing=1')['total'], 1)
        self.assertEqual(self.get_jobs('has_description=0')['total'], 1)
        self.assertEqual(self.get_jobs('currency=TRY&period=month&salary_min=110000&sort=salary_high')['total'], 1)
        self.assertEqual(self.client.get('/api/jobs?sort=salary_high').status_code, 400)
        self.assertEqual(self.client.get('/api/jobs?experience_min=7&experience_max=3').status_code, 400)
        self.assertEqual(self.client.get('/api/jobs?salary_min=nan').status_code, 400)

    def test_facets_respect_other_filters_and_keep_own_alternatives(self):
        self.seed()
        result=self.client.get('/api/facets?category=Engineering&workplace=Remote').json
        self.assertEqual({i['value']:i['count'] for i in result['location']}, {'Istanbul':1})
        self.assertEqual({i['value'] for i in result['workplace']}, {'Remote','Hybrid'})
        self.assertEqual({i['value'] for i in result['skills']}, {'Python','SQL'})

    def test_discovery_ids_survive_later_searches(self):
        first,_,_=self.scrape([response(card(31)),response(DETAIL)],1)
        second,_,_=self.scrape([response(card(31)+card(32)),response(DETAIL),response(DETAIL)],2)
        a=json.loads((Path(first['output_folders'][0])/'search.json').read_text(encoding='utf-8'))
        b=json.loads((Path(second['output_folders'][0])/'search.json').read_text(encoding='utf-8'))
        self.assertNotEqual(a['searchId'],b['searchId'])
        original=self.get_jobs('task_id='+a['searchId']+'&discovery=new')
        self.assertEqual([j['external_id'] for j in original['jobs']],['31'])
        self.assertIn(a['searchId'],original['jobs'][0]['search_ids'])
        self.assertIn(b['searchId'],original['jobs'][0]['search_ids'])
        self.assertEqual(self.get_jobs('task_id='+b['searchId']+'&discovery=new')['total'],1)
        self.assertEqual(self.get_jobs('task_id='+b['searchId'])['total'],2)
        file=next((Path(second['output_folders'][0])/'ilan_havuzu').glob('*.json'))
        self.assertEqual(json.loads(file.read_text(encoding='utf-8'))['_collector']['searchId'], b['searchId'])
        facet=self.client.get('/api/facets').json
        self.assertTrue(any(i['value']=='AI Engineer' for i in facet['search_term']))

    def test_worker_preserves_locations_and_records_request_counts(self):
        run=self.start_worker([{'keyword':'AI Engineer','location':'Istanbul','limit':1},{'keyword':'Backend Developer','location':'Germany','limit':1}],
                              [response(card(1)+card(2)),response(DETAIL),response(card(3)),response(DETAIL)])
        self.assertEqual(run['status'],'finished')
        self.assertEqual([t['location'] for t in run['tasks']],['Istanbul','Germany'])
        self.assertEqual([t['count'] for t in run['tasks']],[1,1])
        self.assertEqual(run['stats']['new'],2)
        log=self.client.get(f"/api/runs/{run['id']}/logs?kind=page_result").json
        self.assertEqual(log['totals']['cards_returned'],3)
        self.assertEqual(log['totals']['collected'],2)
        self.assertEqual(log['totals']['not_processed'],1)
        self.assertTrue(all('request_id' in e['data'] and 'returned_ids' in e['data'] for e in log['events']))
        self.assertEqual(len(log['events']),2)
        response_log=self.client.get(f"/api/runs/{run['id']}/logs?kind=request_finished").json
        self.assertEqual(len(response_log['events']),4)
        self.assertTrue(all('duration_ms' in e['data'] for e in response_log['events']))
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}/logs/download").status_code,200)

    def test_pause_resume_same_folder_without_refetching_saved_detail(self):
        original=pipeline.process_raw
        def stop_after_job(*args,**kwargs):
            result=original(*args,**kwargs)
            server.state.stop_flag=True
            return result
        with patch.object(pipeline,'process_raw',side_effect=stop_after_job):
            run=self.start_worker([{'keyword':'AI','location':'Istanbul','limit':2}], [response(card(1)+card(2)),response(DETAIL)])
        self.assertEqual(run['status'],'paused')
        folder=run['tasks'][0]['folder']
        self.assertEqual(run['tasks'][0]['count'],1)
        with patch('requests.Session.get',side_effect=[response(DETAIL)]) as get:
            self.assertEqual(self.client.post(f"/api/runs/{run['id']}/resume").status_code,200)
            server.state.thread.join(timeout=15)
        resumed=self.client.get('/api/runs/'+run['id']).json
        self.assertEqual(resumed['status'],'finished')
        self.assertEqual(resumed['tasks'][0]['folder'],folder)
        self.assertEqual(resumed['tasks'][0]['count'],2)
        self.assertEqual(resumed['stats']['new'],2)
        self.assertEqual(get.call_count,1)
        self.assertEqual(self.get_jobs()['total'],2)

    def test_recovery_and_pending_task_reorder(self):
        with self.factory() as session:
            session.add(SearchRun(id='recovery',status='running'))
            session.add_all([SearchTask(id='a',run_id='recovery',position=0,keyword='Done',location='Berlin',status='finished'),SearchTask(id='b',run_id='recovery',position=1,keyword='B',location='Ankara',status='running'),SearchTask(id='c',run_id='recovery',position=2,keyword='C',location='Istanbul')])
            session.commit()
        runs.recover(self.factory)
        result=self.client.get('/api/runs/recovery').json
        self.assertEqual(result['status'],'paused')
        self.assertEqual(result['tasks'][1]['status'],'paused')
        changed=self.client.patch('/api/runs/recovery',json={'tasks':[{'id':'c','keyword':'C','location':'Istanbul','limit':5},{'id':'b','keyword':'B','location':'Ankara','limit':None}]})
        self.assertEqual(changed.status_code,200,changed.json)
        self.assertEqual([t['id'] for t in self.client.get('/api/runs/recovery').json['tasks']],['a','c','b'])

    def test_trash_restore_tombstone_and_shared_snapshots(self):
        first,_,_=self.scrape([response(card(9)),response(DETAIL)],1)
        id_=self.get_jobs()['jobs'][0]['id']
        self.assertEqual(self.client.delete('/api/jobs/'+str(id_)).status_code,200)
        self.assertEqual(self.get_jobs()['total'],0)
        self.assertEqual(self.get_jobs('visibility=trash')['total'],1)
        second,_,_=self.scrape([response(card(9)),response(DETAIL)],1)
        self.assertEqual(self.get_jobs()['total'],0)
        for result in (first,second):
            file=next((Path(result['output_folders'][0])/'ilan_havuzu').glob('*.json'))
            self.assertTrue(json.loads(file.read_text(encoding='utf-8'))['_deletedAt'])
        self.assertEqual(self.client.post('/api/trash/jobs',json={'ids':[id_],'action':'restore'}).status_code,200)
        self.assertEqual(self.get_jobs()['total'],1)
        for result in (first,second):
            file=next((Path(result['output_folders'][0])/'ilan_havuzu').glob('*.json'))
            self.assertIsNone(json.loads(file.read_text(encoding='utf-8'))['_deletedAt'])
        self.assertEqual(self.client.post('/api/trash/jobs',json={'ids':[id_],'action':'purge'}).status_code,400)

    def test_history_trash_keeps_shared_jobs_and_restore(self):
        result,_,_=self.scrape([response(card(88)),response(DETAIL)],1)
        meta=json.loads((Path(result['output_folders'][0])/'search.json').read_text(encoding='utf-8'))
        ident=meta['runId']
        self.assertEqual(self.client.post('/api/runs/'+ident+'/delete').status_code,200)
        self.assertEqual(len(self.client.get('/api/runs').json['runs']),0)
        self.assertEqual(self.get_jobs()['total'],1)
        self.assertEqual(len(self.client.get('/api/runs?trash=1').json['runs']),1)
        self.assertEqual(self.client.post('/api/runs/'+ident+'/restore').status_code,200)
        self.assertEqual(len(self.client.get('/api/runs').json['runs']),1)
        self.assertTrue(Path(result['output_folders'][0]).exists())

    def test_detail_navigation_uses_active_filter_and_sort(self):
        self.seed()
        jobs=self.get_jobs('category=Engineering&sort=title')['jobs']
        first=jobs[0]['id']
        result=self.client.get(f'/api/jobs/{first}/navigation?category=Engineering&sort=title').json
        self.assertIsNone(result['previous'])
        self.assertEqual(result['next'],jobs[1]['id'])
        self.assertEqual(result['total'],2)

    def test_publication_and_creation_dates_sort_independently(self):
        self.seed()
        now=datetime.utcnow()
        with self.factory() as session:
            for external_id,days in (('a',2),('b',3),('c',1)):
                job=session.query(Job).filter_by(external_id=external_id).one()
                job.created_at=now-timedelta(days=days)
                job.scraped_at=now+timedelta(days=days)
            session.commit()
        expected={'posted':['a','b','c'],'posted_oldest':['b','a','c'],
                  'created':['c','a','b'],'created_oldest':['b','a','c']}
        for sort,ids in expected.items():
            self.assertEqual([j['external_id'] for j in self.get_jobs('sort='+sort)['jobs']],ids)

    def test_repeated_run_has_results_even_without_first_added_jobs(self):
        self.seed()
        with self.factory() as session:
            job=session.query(Job).filter_by(external_id='a').one()
            session.add(SearchRun(id='repeat',status='finished'))
            session.add(SearchTask(id='repeat-task',run_id='repeat',keyword='Python',status='finished'))
            session.add(TaskJob(task_id='repeat-task',job_id=job.id,is_new=False))
            session.commit()
        self.assertEqual(self.get_jobs('run_id=repeat')['total'],1)
        self.assertEqual(self.get_jobs('task_id=repeat-task')['total'],1)
        self.assertEqual(self.get_jobs('run_id=repeat&discovery=new')['total'],0)

    def test_events_broadcast_to_two_subscribers(self):
        with server.state.condition:
            server.state.messages.clear()
            server.state.sequence=0
        server.state.emit('notice',{'msg':'two viewers'})
        first=self.client.get('/events',headers={'Last-Event-ID':'0'},buffered=False)
        second=self.client.get('/events',headers={'Last-Event-ID':'0'},buffered=False)
        try:
            self.assertIn(b'two viewers',next(first.response))
            self.assertIn(b'two viewers',next(second.response))
        finally:
            first.close();second.close()

    def test_final_event_does_not_release_worker_before_cleanup(self):
        server.state.running=True
        server.state.emit('finished',{'embedded':1})
        self.assertTrue(server.state.running)
        server.state.emit('error',{'msg':'test'})
        self.assertTrue(server.state.running)
        server.state.running=False

    def test_invalid_task_payload_does_not_create_a_run(self):
        for value in (0,-1,1.5,True,'oops'):
            result=self.client.post('/api/scrape',json={'tasks':[{'keyword':'AI','location':'Istanbul','limit':value}]})
            self.assertEqual(result.status_code,400)
        with self.factory() as session:
            self.assertEqual(session.query(SearchRun).count(),0)

    def test_legacy_upgrade_backs_up_and_rebuilds_discovery(self):
        import sqlite3
        started=datetime.utcnow()-timedelta(minutes=5)
        finished=datetime.utcnow()-timedelta(minutes=1)
        with self.factory() as session:
            session.add(Job(source='linkedin',external_id='old',title='Python Engineer',company='Legacy',description='3 yıl Python deneyimi',created_at=started+timedelta(seconds=20),raw=json.dumps({'posted':'2026-10-10'})))
            session.query(Setting).filter(Setting.key=='ux_schema_v2').delete()
            session.commit()
        pool=Path(self.tmp.name)/'searches'/'legacy-search'
        (pool/'ilan_havuzu').mkdir(parents=True)
        (pool/'search.json').write_text(json.dumps({'title':'Old search','location':'Ankara','limit':10,'count':1,'status':'finished','startedAt':started.isoformat(),'finishedAt':finished.isoformat()}),encoding='utf-8')
        (pool/'ilan_havuzu'/'ap-linkedin-old.json').write_text('{"title":"Python Engineer","_collector":{}}',encoding='utf-8')
        with self.engine.begin() as conn:
            conn.execute(text('DROP INDEX IF EXISTS ix_jobs_deleted_at'))
            conn.execute(text('DROP INDEX IF EXISTS ix_jobs_posted_at'))
            # Simulate a legacy DB, which predates service journal triggers.
            for trigger in ('jobs_journal_insert','jobs_journal_update','jobs_journal_delete','task_jobs_journal'):
                conn.execute(text('DROP TRIGGER IF EXISTS '+trigger))
            for column in ('posted_at','experience_years','deleted_at'):
                conn.execute(text('ALTER TABLE jobs DROP COLUMN '+column))
        db.init_db(force=True)
        backup=next(Path(self.tmp.name).glob('backup_before_ux_*'))
        self.assertTrue((backup/'accountless_searches'/'legacy-search'/'search.json').exists())
        with closing(sqlite3.connect(backup/'jobs.db')) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
            self.assertNotIn('deleted_at',[r[1] for r in connection.execute('PRAGMA table_info(jobs)')])
        result=self.get_jobs()['jobs'][0]
        self.assertEqual(result['experience_years'],3)
        self.assertTrue(result['search_ids'])
        self.assertTrue(result['discoveries'][0]['is_new'])
        run=self.client.get('/api/runs').json['runs'][0]
        self.assertEqual(run['tasks'][0]['count'],1)
        self.assertEqual(self.get_jobs('task_id='+result['search_ids'][0]+'&discovery=new')['total'],1)
        saved=json.loads((pool/'ilan_havuzu'/'ap-linkedin-old.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['_collector']['searchId'],result['search_ids'][0])


if __name__=='__main__':
    unittest.main()
