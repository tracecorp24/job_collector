"""Summarize an existing collection DB without importing or starting the app.

python scripts/collection_diagnosis.py --db backup.db --output diagnosis.json
Only SELECT statements run against SQLite mode=ro. Times default to UTC+3.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3


def diagnose(path, offset=3):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    zone = timezone(timedelta(hours=offset))

    def rows(sql):
        return [dict(row) for row in db.execute(sql)]

    def epoch(value):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()

    def local_day(timestamp):
        return datetime.fromtimestamp(timestamp, zone).date().isoformat()

    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'jobs', 'search_events'}.issubset(tables):
            raise ValueError('jobs and search_events tables are required.')
        result = {'database': path.name, 'utc_offset_hours': offset,
            'counts': {name: db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                for name in ('jobs', 'search_events', 'app_logs', 'search_runs', 'repair_tasks') if name in tables}}
        times = rows('SELECT MIN(created_at) first, MAX(created_at) last FROM search_events')[0]
        result['event_range_utc'] = times
        result['source_policy_snapshot'] = rows('SELECT * FROM source_policy') if 'source_policy' in tables else []
        jobs = list(db.execute('SELECT created_at, description, raw FROM jobs ORDER BY created_at'))
        daily_jobs = Counter()
        pending = 0
        left = 0
        peak = 0
        stamps = []
        for row in jobs:
            stamp = epoch(row['created_at'])
            daily_jobs[local_day(stamp)] += 1
            pending += bool(json.loads(row['raw'] or '{}').get('detail_pending'))
            stamps.append(stamp)
            while stamps[left] < stamp - 3600:
                left += 1
            peak = max(peak, len(stamps) - left)
        result['jobs_by_local_day'] = dict(daily_jobs)
        result['peak_new_jobs_in_rolling_hour'] = peak
        result['pending_jobs_snapshot'] = pending
        result['empty_descriptions_snapshot'] = sum(not (row['description'] or '').strip() for row in jobs)
        daily = defaultdict(Counter)
        origins = defaultdict(Counter)
        stages = defaultdict(Counter)
        pauses = []
        gaps = []
        previous = None
        for row in db.execute('SELECT created_at, kind, data FROM search_events ORDER BY created_at, id'):
            data = json.loads(row['data'] or '{}')
            kind = row['kind']
            stamp = epoch(row['created_at'])
            bucket = daily[local_day(stamp)]
            if kind == 'request_finished':
                bucket['requests'] += 1
                bucket['list_requests' if data.get('params') else 'detail_requests'] += 1
                bucket['http_' + str(data.get('status'))] += 1
                bucket['http_seconds'] += data.get('duration_ms', 0) / 1000
                origins[data.get('source', 'search')][str(data.get('status'))] += 1
                if previous is not None:
                    gaps.append({'seconds': round(stamp-previous[0], 3),
                        'start_utc': previous[1], 'end_utc': row['created_at']})
                previous = stamp, row['created_at']
            elif kind == 'source_paused':
                bucket['source_pause_events'] += 1
                pauses.append((stamp, float(data.get('blocked_until') or stamp)))
            elif kind == 'shared_rate_wait_finished':
                bucket['shared_wait_seconds'] += data.get('seconds', 0)
            elif kind in ('priority_yield', 'repair_completed'):
                bucket[kind] += 1
            elif kind == 'processing_result':
                bucket['saved_' + str(data.get('outcome'))] += 1
            elif kind == 'processing_stage' and data.get('phase') == 'finished':
                stages[data.get('stage', 'unknown')]['events'] += 1
                stages[data.get('stage', 'unknown')]['seconds'] += data.get('duration_ms', 0) / 1000
        # Cut recorded pauses at the last search event; overlapping reports count once.
        # This is an observed-event horizon, not proof of uninterrupted collection.
        cutoff = epoch(times['last']) if times['last'] else 0
        merged = []
        for start, end in sorted(pauses):
            end = min(end, cutoff)
            if end <= start:
                continue
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(end, merged[-1][1])
            else:
                merged.append([start, end])
        for start, end in merged:
            while start < end:
                local = datetime.fromtimestamp(start, zone)
                midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                stop = min(end, midnight.timestamp())
                daily[local_day(start)]['recorded_source_block_seconds'] += stop-start
                start = stop
        result['events_by_local_day'] = {key: dict(value) for key, value in sorted(daily.items())}
        result['request_statuses_by_origin'] = {key: dict(value) for key, value in origins.items()}
        result['recorded_processing_stages'] = {key: dict(value) for key, value in stages.items()}
        result['longest_request_gaps'] = sorted(gaps, key=lambda item: -item['seconds'])[:5]
        if 'repair_tasks' in tables:
            result['repair_queue_snapshot'] = rows('SELECT status, stage, COUNT(*) count, MAX(attempts) max_attempts FROM repair_tasks GROUP BY status, stage')
            result['pending_jobs_with_done_repair'] = rows("SELECT j.id, j.external_id FROM jobs j JOIN repair_tasks r USING (source,external_id) WHERE json_extract(j.raw,'$.detail_pending')=1 AND r.status='done' AND j.deleted_at IS NULL")
        if 'settings' in tables:
            result['backlog_alarm_baseline'] = rows("SELECT value FROM settings WHERE key='problem_detail_backlog'")
        result['limitations'] = [
            'Daily creation counts include all stored jobs; no continuous activity is assumed.',
            'Card discovery and detail completion are different milestones.',
            'Repair enrichment and model calls may lack processing_stage events.',
            'Source waits are merged and clipped to the last search event; early logs may be incomplete.',
            'HTTP gap alone does not identify its cause.']
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timezone-offset-hours', type=int, default=3)
    args = parser.parse_args()
    # Never overwrite the source database with the output.
    if args.output and args.output.resolve() == args.db.resolve():
        parser.error('--output must differ from --db')
    result = diagnose(args.db, args.timezone_offset_hours)
    encoded = json.dumps(result, ensure_ascii=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n', encoding='utf-8')
        print(str(args.output))
    else:
        print(encoded)


if __name__ == '__main__':
    main()
