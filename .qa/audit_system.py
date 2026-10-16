"""Read-only application audit: reproduce edge cases in temporary databases."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import test_light
import test_workspace
from test_light import card,response,DETAIL
from jobapp import pipeline,server
from jobapp.models import Job,SearchTask,SearchRun

results=[]
def probe(name,fn):
    fixture=test_workspace.WorkspaceTests()
    fixture.setUp()
    try:
        result=fn(fixture)
        results.append(dict(probe=name,evidence=result))
    finally:
        fixture.tearDown()
        fixture.doCleanups()

def processing(f):
    with patch.object(pipeline,'process_raw',side_effect=RuntimeError('simulated database processing failure')):
        result,events,_=f.scrape([response(card(1)),response(DETAIL)],1)
    with f.factory() as session:
        task=session.query(SearchTask).one()
        return dict(job_rows=session.query(Job).count(),status=task.status,checkpoint=json.loads(task.checkpoint),skipped=result['skipped'])

def embedding(f):
    f.scrape([response(card(1)),response(DETAIL)],1)
    with f.factory() as session:
        session.query(Job).one().embedding='[0.1, 0.2]'
        session.commit()
    with patch('requests.Session.get',side_effect=[response(card(1)),response(DETAIL.replace('PyTorch','Accounting'))]):
        result=pipeline.run_scrape(['AI'],['Istanbul'],limit=1,refresh_details=True)
    with f.factory() as session:
        job=session.query(Job).one()
        return dict(updated=result['updated'],description_changed='Accounting' in job.description,embedding=job.embedding)

def cancelled(f):
    tasks=[dict(id='first',keyword='AI'),dict(id='second',keyword='Backend')]
    run_id=f.client.post('/api/queue',json={'tasks':tasks}).json['run_id']
    cancelled=f.client.post(f'/api/runs/{run_id}/tasks/first/cancel').status_code
    before=f.client.get('/api/runs/'+run_id).json['tasks'][0]['status']
    save=f.client.post('/api/queue',json={'run_id':run_id,'tasks':tasks}).status_code
    after=f.client.get('/api/runs/'+run_id).json['tasks'][0]['status']
    return dict(cancel_http=cancelled,status_before_autosave=before,autosave_http=save,status_after_autosave=after)

def export_stop(f):
    run=f.start_worker([dict(keyword='AI',location='Istanbul',limit=2)],
                       [response(card(1)+card(2)),response(DETAIL),response(status=429)])
    stop=f.client.post('/api/runs/'+run['id']+'/stop').status_code
    updated=f.client.get('/api/runs/'+run['id']).json
    folder=Path(test_light.config.ACCOUNTLESS_OUTPUT_DIR)/run['tasks'][0]['folder']
    metadata=json.loads((folder/'search.json').read_text(encoding='utf-8'))
    return dict(stop_http=stop,run_status=updated['status'],task_status=updated['tasks'][0]['status'],export_status=metadata['status'],export_reason=metadata.get('terminationReason'))

def export_limit(f):
    run=f.start_worker([dict(keyword='AI',location='Istanbul',limit=2)],
                       [response(card(1)+card(2)),response(DETAIL),response(status=429)])
    task=run['tasks'][0]
    edit=f.client.patch('/api/runs/'+run['id'],json={'tasks':[dict(id=task['id'],keyword='AI',location='Istanbul',limit=3)]}).status_code
    with f.engine.begin() as connection:
        connection.execute(text('UPDATE source_policy SET blocked_until=0'))
    with patch('requests.Session.get',side_effect=[response(card(1)+card(2)+card(3)),response(DETAIL),response(DETAIL)]):
        resume=f.client.post('/api/runs/'+run['id']+'/resume').status_code
        server.state.thread.join(10)
    updated=f.client.get('/api/runs/'+run['id']).json
    folder=Path(test_light.config.ACCOUNTLESS_OUTPUT_DIR)/task['folder']
    metadata=json.loads((folder/'search.json').read_text(encoding='utf-8'))
    return dict(edit_http=edit,resume_http=resume,task_limit=updated['tasks'][0]['limit'],export_limit=metadata['limit'],collected=updated['tasks'][0]['count'])

for name,fn in [('processing_checkpoint',processing),('stale_embedding',embedding),('cancelled_task_autosave',cancelled),('stopped_export',export_stop),('changed_limit_export',export_limit)]:
    probe(name,fn)
output=Path(__file__).with_name('audit_scan.json')
output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=True,indent=2))
