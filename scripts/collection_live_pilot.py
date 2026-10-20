"""Small, sequential, opt-in public-source pilot. No production writes.

Run inside a dedicated runner with LINKO_URL and LINKO_LOG_KEY set. Both arms
share one durable Coordinator, keep at least 120 seconds between source requests,
and stop the ENTIRE pilot at the first access denial, challenge or bad response.
This is a smoke pilot, not a rate-limit benchmark or a production A/B result.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-seconds', type=int, default=1500)
    parser.add_argument('--after-job-id', type=int, default=1300)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root / '.qa'):
        parser.error('Output must be inside this checkout .qa directory.')
    output.mkdir(parents=True, exist_ok=False)
    if not 180 <= args.max_seconds <= 1800:
        parser.error('Wall-clock budget must be 180..1800 seconds.')
    # Configure an isolated DB before importing ANY application modules.
    os.environ['JOBAPP_DB_PATH'] = str(output / 'shared-source-policy.db')
    os.environ['JOBAPP_REQUEST_INTERVAL'] = '120'
    os.environ['JOBAPP_MIN_REQUEST_INTERVAL'] = '120'
    os.environ['JOBAPP_ACCOUNTLESS_OUTPUT_DIR'] = str(output / 'unused-searches')
    sys.path.insert(0, str(root))
    import requests
    from sqlalchemy import text
    from jobapp.scraper.accountless import AccountlessScraper
    from jobapp.transport import Coordinator, SourcePaused

    url = os.environ.get('LINKO_URL', 'https://job.ai-org.online').rstrip('/')
    key = os.environ.get('LINKO_LOG_KEY', '')
    if not key:
        parser.error('LINKO_LOG_KEY is required; it is never written to artifacts.')
    control = requests.Session()
    control.trust_env = False
    control.headers.update({'Authorization': 'Bearer ' + key, 'User-Agent': 'Linko-readonly-pilot/1'})
    started = time.time()
    deadline = started + args.max_seconds
    result = {'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'execution_environment': 'dedicated_runner', 'production_shared_lease': False,
        'arms_share_durable_gate': True, 'minimum_interval_seconds': 120,
        'plan': ['persistent','fresh','fresh','persistent','fresh','persistent','persistent','fresh'],
        'samples': [], 'status_observations': [], 'outcome': 'preparing',
        'limitations': ['Different execution environment from production VPS; source egress IP not measured.',
            'At most four requests per arm cannot determine a lowest-error mode.',
            'First refusal stops every arm; no restart/reset retry is attempted.',
            'Production source deadlines are honored but its request lease is not shared across different hosts.']}
    path = output / 'result.json'
    def save():
        path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding='utf-8')
    def get(pathname):
        response = control.get(url + pathname, timeout=30, allow_redirects=False)
        response.raise_for_status()
        return response.json()
    def safe_status(status):
        return {name:status[name] for name in ('source','queue_layers','completion_queue','version','logging') if name in status}
    coordinator = Coordinator(interval=120)
    scrapers = []
    persistent = None
    last_status_poll = 0
    last_source_send_monotonic = None

    def cancelled():
        return time.time() >= deadline

    def refresh_guard(force=False):
        nonlocal last_status_poll
        if cancelled():
            return False
        if not force and time.time()-last_status_poll < 15:
            return True
        status = get('/api/v1/status')
        last_status_poll = time.time()
        source = status['source']
        coordinator.interval = max(coordinator.interval, float(source.get('effective_interval',120)))
        result['status_observations'].append({'at_utc': datetime.now(timezone.utc).isoformat(),
            'paused': source['paused'], 'blocked_until': source['blocked_until'],
            'interval_floor': source['interval_floor'], 'status_code': source.get('status_code'),
            'production_version': status.get('version',{}).get('sha')})
        with coordinator.transaction() as conn:
            conn.execute(text('UPDATE source_policy SET blocked_until=MAX(blocked_until,:blocked), '
                'interval_floor=MAX(interval_floor,:floor) WHERE source=:source'),
                {'blocked': source['blocked_until'], 'floor': max(120,source['interval_floor']), 'source': 'linkedin'})
        save()
        return True

    try:
        refresh_guard(force=True)
        jobs = get('/api/v1/jobs?after_id=' + str(args.after_job_id) + '&limit=100')['items']
        # Completed, existing source records avoid choosing URLs already known to be retrying.
        eligible = [j for j in jobs if str(j.get('external_id','')).isdigit()
            and not j.get('detail_pending') and (j.get('description') or '').strip()]
        random.Random(20261020).shuffle(eligible)
        selected = eligible[:8]
        if len(selected) < 8:
            raise RuntimeError('Insufficient eligible existing postings for the predeclared pilot.')
        result['selected_external_ids'] = [j['external_id'] for j in selected]
        result['production_status_at_start'] = safe_status(get('/api/v1/status'))
        save()
        for index, (arm, job) in enumerate(zip(result['plan'], selected)):
            # A block from either arm ends all subsequent source traffic.
            while not cancelled():
                refresh_guard(force=True)
                state = coordinator.state()
                if not state['paused']:
                    break
                result['outcome'] = 'waiting_for_recorded_source_deadline'
                save()
                print(json.dumps({'event':'waiting_for_source','remaining_seconds':state['remaining_seconds']}),flush=True)
                time.sleep(min(20, max(1,state['remaining_seconds']), max(0.1,deadline-time.time())))
            if cancelled():
                result['outcome'] = 'budget_ended_while_waiting'
                break
            if arm == 'persistent' and persistent is not None:
                scraper, session_id = persistent
            else:
                scraper = AccountlessScraper(max_retries=0, should_stop=cancelled)
                session_id = uuid.uuid4().hex
                scrapers.append(scraper)
                if arm == 'persistent':
                    persistent = scraper, session_id
            sample = {'index':index, 'arm':arm, 'session_id':session_id,
                'external_id':job['external_id'], 'request_events':[], 'source_send_attempts':0,
                'session_cookies_before':len(scraper.session.cookies)}
            def emit(kind, data):
                if kind in ('request_started','request_finished','shared_rate_wait','shared_rate_wait_finished'):
                    sample['request_events'].append({'kind':kind,'data':data,'at_utc':datetime.now(timezone.utc).isoformat()})
                    if kind != 'request_started':
                        print(json.dumps({'event':kind,'arm':arm,'index':index,'status':data.get('status'),'seconds':data.get('seconds')}),flush=True)
            scraper.emit = emit
            # The scraper's own gate remains authoritative. An extra check immediately
            # before the actual socket send also catches production pauses during pacing.
            original_get = scraper.session.get
            def guarded_get(*get_args, **get_kwargs):
                nonlocal last_source_send_monotonic
                if not refresh_guard(force=True):
                    raise RuntimeError('Pilot wall-clock budget reached before source send.')
                # Reservation begins before control polling. Enforce the same minimum
                # on actual send times, so variable control latency cannot shorten it.
                if last_source_send_monotonic is not None:
                    send_after = last_source_send_monotonic + max(120,coordinator.interval)
                    while time.monotonic() < send_after and not cancelled():
                        coordinator.ensure_allowed()
                        time.sleep(min(10,send_after-time.monotonic(),max(0.1,deadline-time.time())))
                        if not refresh_guard():
                            raise RuntimeError('Pilot wall-clock budget reached while pacing.')
                if not refresh_guard(force=True):
                    raise RuntimeError('Pilot wall-clock budget reached after pacing.')
                coordinator.ensure_allowed()
                if cancelled() or sum(s['source_send_attempts'] for s in result['samples']) >= 8:
                    raise RuntimeError('Predeclared source request or time budget reached.')
                get_kwargs['timeout'] = min(float(get_kwargs.get('timeout',20)), max(0.1,deadline-time.time()))
                sample['source_send_attempts'] += 1
                last_source_send_monotonic = time.monotonic()
                sample.setdefault('source_send_times_utc',[]).append(datetime.now(timezone.utc).isoformat())
                return original_get(*get_args, **get_kwargs)
            scraper.session.get = guarded_get
            sample_started = time.time()
            result['samples'].append(sample)
            try:
                soup = scraper._get(scraper.detail_url({'external_id':job['external_id']}))
                box = soup.select_one('.show-more-less-html__markup, .description__text') if soup else None
                sample['description_chars'] = len(box.get_text('\n',strip=True)) if box else 0
                sample['semantic_outcome'] = 'description_available' if sample['description_chars'] else 'no_description'
            except SourcePaused as exc:
                sample['semantic_outcome'] = 'source_paused'
                sample['pause_state'] = exc.state
            except Exception as exc:
                sample['semantic_outcome'] = 'failed'
                sample['error_type'] = type(exc).__name__
            finally:
                scraper.session.get = original_get
                sample['elapsed_seconds'] = round(time.time()-sample_started,3)
                sample['session_cookies_after'] = len(scraper.session.cookies)
                if arm == 'fresh':
                    scraper.session.close()
                save()
            if sample['semantic_outcome'] != 'description_available':
                result['outcome'] = 'stopped_on_first_non_success'
                break
            result['outcome'] = 'completed' if index == 7 else 'running'
            save()
        result['production_status_at_end'] = safe_status(get('/api/v1/status'))
    except Exception as exc:
        result['outcome'] = 'control_or_setup_failed'
        result['error_type'] = type(exc).__name__
        print(json.dumps({'event':'stopped','error_type':type(exc).__name__}),flush=True)
    finally:
        for scraper in scrapers:
            scraper.session.close()
        control.close()
        result['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        result['elapsed_seconds'] = round(time.time()-started,3)
        result['source_requests'] = sum(sample['source_send_attempts'] for sample in result['samples'])
        result['all_successful'] = bool(len(result['samples'])==8 and all(s['semantic_outcome']=='description_available' for s in result['samples']))
        save()
        print(json.dumps({'outcome':result['outcome'],'source_requests':result['source_requests'],
            'samples':len(result['samples']),'all_successful':result['all_successful']}),flush=True)


if __name__ == '__main__':
    main()
