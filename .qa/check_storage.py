import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jobapp import config
connection=sqlite3.connect(Path(config.DB_PATH).resolve().as_uri()+'?mode=ro',uri=True)
connection.row_factory=sqlite3.Row
result={
 'integrity':connection.execute('PRAGMA quick_check').fetchone()[0],
 'jobs':connection.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],
 'orphan_job_links':connection.execute('SELECT COUNT(*) FROM task_jobs t LEFT JOIN jobs j ON j.id=t.job_id WHERE j.id IS NULL').fetchone()[0],
 'orphan_task_links':connection.execute('SELECT COUNT(*) FROM task_jobs t LEFT JOIN search_tasks s ON s.id=t.task_id WHERE s.id IS NULL').fetchone()[0],
 'tasks_without_run':connection.execute('SELECT COUNT(*) FROM search_tasks t LEFT JOIN search_runs r ON r.id=t.run_id WHERE r.id IS NULL').fetchone()[0],
 'duplicate_jobs':connection.execute('SELECT COUNT(*) FROM (SELECT source, external_id,COUNT(*) n FROM jobs GROUP BY source,external_id HAVING n>1)').fetchone()[0],
 'invalid_job_json':connection.execute("SELECT COUNT(*) FROM jobs WHERE NOT json_valid(raw) OR NOT json_valid(tags)").fetchone()[0],
 'run_statuses':dict(connection.execute('SELECT status,COUNT(*) FROM search_runs GROUP BY status').fetchall()),
 'stored_error_events':connection.execute("SELECT COUNT(*) FROM search_events WHERE kind='error'").fetchone()[0],
}
result['recent_errors']=[dict(row) for row in connection.execute("SELECT kind,created_at,json_extract(data,'error_type') AS error_type,json_extract(data,'msg') AS msg FROM search_events WHERE kind IN ('error','job_skipped') ORDER BY id DESC LIMIT 5")]
connection.close()
print(json.dumps(result,ensure_ascii=True,indent=2))
