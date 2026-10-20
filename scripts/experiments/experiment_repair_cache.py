"""Offline behavioral comparison of actual fill_one and repair discover/worker."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SANDBOX = ROOT / '.qa' / ('repair-cache-' + __import__('uuid').uuid4().hex[:10])
SANDBOX.mkdir(parents=True)
os.environ['JOBAPP_DB_PATH'] = str(SANDBOX / 'unused-global.db')
os.environ['JOBAPP_ACCOUNTLESS_OUTPUT_DIR'] = str(SANDBOX / 'exports')
os.environ['JOBAPP_SPOOL_DIR'] = str(SANDBOX / 'spool')
os.environ['JOBAPP_REQUEST_INTERVAL'] = '10'
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jobapp import config, db, details, pipeline, repair
from jobapp.models import Base, Job, RepairTask
from jobapp.scraper.accountless import AccountlessScraper
from jobapp.transport import Details


def forbid_network(*args, **kwargs):
    raise AssertionError('All network connections forbidden in cache experiment')


def fake_response():
    response = requests.Response()
    response.status_code = 200
    response._content = b'<div class="show-more-less-html__markup">NEW NETWORK Python description</div>'
    response._content_consumed = True
    response.encoding = 'utf-8'
    return response


def experiment(scenario, route):
    directory = SANDBOX / (scenario + '--' + route)
    directory.mkdir()
    engine = create_engine('sqlite:///' + str(directory / 'jobs.db'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    events = []
    server = SimpleNamespace(SessionLocal=factory, state=SimpleNamespace(
        running=False, stop_flag=False, last={}, emit=lambda kind, value: events.append((kind, value))))
    raw = {'external_id': '123', 'url': 'https://www.linkedin.com/jobs/view/123',
           'card_lines': ['Python Engineer', 'Fixture Company', 'Istanbul'],
           'card_layout': 'guest', 'detail_pending': True}
    cache_raw = dict(raw)
    description = ''
    if scenario == 'changed_card_existing_description':
        cache_raw['card_lines'] = ['Old Python Engineer', 'Fixture Company', 'Istanbul']
        description = 'OLD CACHED Python description'
    elif scenario == 'fresh_cache_existing_job':
        description = 'OLD CACHED Python description'
    with patch.object(db, 'engine', engine), patch.object(pipeline, 'SessionLocal', factory), \
         patch.object(config, 'ACCOUNTLESS_OUTPUT_DIR', str(directory / 'exports')), \
         patch.object(config, 'MIN_REQUEST_INTERVAL', 0), patch.object(AccountlessScraper, 'REQUEST_INTERVAL', 0), \
         patch('socket.socket.connect', side_effect=forbid_network), \
         patch('socket.socket.connect_ex', side_effect=forbid_network):
        with factory() as session:
            job = Job(source='linkedin', external_id='123', title=raw['card_lines'][0],
                      company=raw['card_lines'][1], location=raw['card_lines'][2],
                      description=description, raw=json.dumps(raw), tags='[]')
            session.add(job)
            session.commit()
            job_id = job.id
        Details().put(cache_raw, 'OLD CACHED Python description')
        before_lookup = Details().lookup(raw)
        with patch('requests.Session.get', side_effect=lambda *a, **k: fake_response()) as get:
            if route == 'legacy_fill_one':
                scraper = AccountlessScraper(max_retries=0)
                try:
                    processed = details.fill_one(server, scraper, target_job_id=job_id)
                    assert processed
                finally:
                    scraper.session.close()
                force = None
                stage = 'legacy_complete'
                attempts = None
            elif route == 'manual_force':
                with factory() as session:
                    job = session.get(Job, job_id)
                    raw.update(description=description, _repair_existing_job_id=job_id,
                        _repair_fields=['description'], _repair_force=True, _repair_values={},
                        _queue_layer='manual', _repair_revision=repair.revision(job),
                        _repair_card_fingerprint=repair.card_fingerprint(job))
                    repair.enqueue(session, raw, 'Offline explicit force check.',
                        replace=True, force_refresh=True)
                    session.commit()
                force = True
            else:
                with factory() as session:
                    repair.discover(session)
                    session.commit()
                    task = session.get(RepairTask, ('linkedin', '123'))
                    task_raw = json.loads(task.raw)
                force = task_raw.get('_repair_force_requested', False)
            if route in ('repair_current', 'manual_force'):
                # First worker performs actual detail stage; second local enrich.
                repair.worker(server, ('linkedin', '123'))
                with factory() as session:
                    task = session.get(RepairTask, ('linkedin', '123'))
                    stage_after_detail = task.stage
                if stage_after_detail == 'enrich':
                    repair.worker(server, ('linkedin', '123'))
                with factory() as session:
                    task = session.get(RepairTask, ('linkedin', '123'))
                    stage, attempts = task.status, task.attempts
                    if task.status != 'done':
                        raise AssertionError(task.last_error)
            with factory() as session:
                job = session.get(Job, job_id)
                result = {'scenario': scenario, 'route': route,
                          'initial_cache_reason': before_lookup['reason'],
                          'initial_cache_reusable': before_lookup['value'] is not None,
                          'discover_force_flag': force, 'http_calls': get.call_count,
                          'final_description': job.description,
                          'final_detail_pending': bool(json.loads(job.raw).get('detail_pending')),
                          'status': stage, 'attempts': attempts}
    engine.dispose()
    return result


rows = [experiment(scenario, route)
        for scenario, routes in (
            ('fresh_cache_empty_job', ('legacy_fill_one', 'repair_current')),
            ('changed_card_existing_description', ('legacy_fill_one', 'repair_current')),
            ('fresh_cache_existing_job', ('manual_force',)),
        )
        for route in routes]
by_key = {(row['scenario'], row['route']): row for row in rows}
checks = {
    'valid_cache_legacy_skips_http': by_key['fresh_cache_empty_job', 'legacy_fill_one']['http_calls'] == 0,
    'valid_cache_current_repair_skips_http': by_key['fresh_cache_empty_job', 'repair_current']['http_calls'] == 0,
    'changed_card_legacy_fetches_http': by_key['changed_card_existing_description', 'legacy_fill_one']['http_calls'] == 1,
    'changed_card_current_repair_fetches_http': by_key['changed_card_existing_description', 'repair_current']['http_calls'] == 1,
    'changed_card_never_keeps_stale_description': not by_key['changed_card_existing_description', 'repair_current']['final_description'].startswith('OLD CACHED'),
    'explicit_manual_force_bypasses_fresh_cache': by_key['fresh_cache_existing_job', 'manual_force']['http_calls'] == 1,
    'all_cases_finish_pending_state': all(not row['final_detail_pending'] for row in rows),
}
result = {'kind': 'offline_actual_repair_worker_and_legacy_fill_one_cache_experiment',
          'external_network_requests': 0, 'sandbox': str(SANDBOX), 'checks': checks,
          'all_checks_passed': all(checks.values()), 'cases': rows,
          'interpretation': 'Automatic repair reuses a fresh matching cache, changed cards fetch current content, and explicit user force bypasses that cache.'}
output = ROOT / '.local/performance-audit-20261020/repair-cache-experiment.json'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(result, indent=2, ensure_ascii=False))
if not result['all_checks_passed']:
    raise SystemExit(1)
