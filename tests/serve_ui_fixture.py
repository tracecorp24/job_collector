"""Isolated UI fixture; never opens the real job database or contacts LinkedIn."""
import json
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
folder = root / '.qa'
folder.mkdir(exist_ok=True)
os.environ['JOBAPP_DB_PATH'] = str(folder / 'ui.db')
os.environ['JOBAPP_ACCOUNTLESS_OUTPUT_DIR'] = str(folder / 'searches')
os.environ['JOBAPP_OPEN_BROWSER'] = '0'
os.environ['JOBAPP_REQUEST_INTERVAL'] = '0'
from datetime import datetime, timedelta
from flask import jsonify
from jobapp import server, db, embed, search_engine
from jobapp.locations import normalize as normalize_location
from jobapp.models import Job, SearchRun, SearchTask, TaskJob, SearchEvent, Watch

app = server.create_app()
# Search fallback is deterministic and never contacts a local model service.
embed.embed_text = lambda text: None
# UI testi çeviri hizmetlerinin erişilebilirliğine bağlı kalmasın.
search_engine.translate_query = lambda text, **kwargs: text
with db.SessionLocal() as session:
    for model in (TaskJob, SearchEvent, SearchTask, SearchRun, Job, Watch):
        session.query(model).delete()
    session.add(SearchRun(id='fixture-run', status='finished'))
    session.add(SearchTask(id='fixture-search', run_id='fixture-run', keyword='Python Developer', location='Istanbul', status='finished', limit=10, checkpoint='{"collected":10}'))
    session.add(SearchRun(id='fixture-repeat', status='finished', created_at=datetime(2026,1,1)))
    session.add(SearchTask(id='fixture-repeat-search', run_id='fixture-repeat', keyword='Repeated search', location='Istanbul', status='finished', checkpoint='{"collected":10}'))
    for status in ('paused','error','stopped','cancelled'):
        run=SearchRun(id='fixture-'+status,status=status,created_at=datetime(2025,1,1),
                      started_at=None if status=='cancelled' else datetime.utcnow()-timedelta(hours=2),
                      status_reason='Kaynak bekleme istedi.' if status=='paused' else 'Test durum açıklaması')
        session.add(run)
        session.add(SearchTask(id='fixture-task-'+status,run_id=run.id,keyword='Örnek '+status,location='Istanbul',
                               status=status,started_at=run.started_at,status_reason=run.status_reason,limit=None))
    for i in range(60):
        location=['Istanbul, Turkey','Ankara, Turkey','Berlin, Germany'][i%3]
        country,city=normalize_location(location)
        job=Job(external_id=str(10000+i),title=['Kıdemli Python Geliştirici','Veri Bilimci','Frontend Developer'][i%3],company=['Örnek Teknoloji','Nova Yazılım','Atlas Veri'][i%3],location=location,location_country=country,location_city=city,workplace_type=['Remote','Hybrid','Onsite'][i%3],category=['Engineering','Data','Design'][i%3],seniority=['Senior','Mid','Junior'][i%3],tags=json.dumps(['Python','SQL'] if i%3==0 else ['React','TypeScript']),description='Ekibimiz için deneyimli bir geliştirici arıyoruz.\n\nSorumluluklar\n• Ürün geliştirme\n• Ekip içi iş birliği',summary='Uzaktan çalışan ürün ekibinde Python servisleri geliştirme.',salary='100.000–140.000 TRY / ay' if i%3==0 else '',salary_min=100000 if i%3==0 else None,salary_max=140000 if i%3==0 else None,salary_currency='TRY' if i%3==0 else '',salary_period='month' if i%3==0 else '',posted_at=datetime.utcnow(),experience_years=i%6,url='https://www.linkedin.com/jobs/view/'+str(10000+i))
        session.add(job);session.flush()
        if i<10:
            session.add(TaskJob(task_id='fixture-search',job_id=job.id,is_new=i<6))
            session.add(TaskJob(task_id='fixture-repeat-search',job_id=job.id,is_new=False))
    session.commit()
app.view_functions['api_ollama_models'] = lambda: jsonify(ok=True, models=[], default='')
app.run(host='127.0.0.1', port=int(os.environ.get('LINKO_UI_PORT', '8027')), threaded=True, use_reloader=False)
