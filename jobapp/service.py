"""Single collector supervisor; all scheduling decisions are persisted in SQLite."""
import json
import logging
import threading
import time
from sqlalchemy import or_, and_, func
from . import config, runs, audit
from .models import SearchRun, SearchTask
from .transport import Coordinator

log = logging.getLogger(__name__)
heartbeat = 0.0
last_error = ""
supervisor = None


def tick(server, now=None):
    global heartbeat, last_error
    now = time.time() if now is None else now
    with runs.lock:
        heartbeat = time.time()
        if server.state.running:
            return
        source = Coordinator().state()
        with server.SessionLocal() as session:
            candidates = session.query(SearchRun).filter(SearchRun.deleted_at.is_(None), or_(
                SearchRun.status.in_(("queued", "paused", "error")),
                and_(SearchRun.status == "finished", func.json_extract(SearchRun.options, '$.schedule_enabled') == 1,
                    func.json_extract(SearchRun.options, '$.schedule_dispatched').is_(None)))).order_by(SearchRun.created_at).all()
            for run in candidates:
                options = json.loads(run.options or "{}")
                # Existing source-paused work is migrated without changing its deadline.
                tasks = session.query(SearchTask).filter_by(run_id=run.id).order_by(SearchTask.position).all()
                source_wait = any(json.loads(t.stats or "{}").get("termination_reason") == "source_paused" for t in tasks if t.status == "paused")
                eligible = (run.status == "queued" and options.get("service_managed")) or (
                    run.status in ("paused", "error") and not options.get("user_paused") and ("auto_resume_at" in options or source_wait))
                if eligible and now >= options.get("auto_resume_at", 0):
                    if options.get("kind", "scrape") == "scrape" and source["paused"]:
                        continue
                    audit.record(session, run.id, None, "automatic_resume", {"reason":"source_ready_or_service_queue", "source_state":source})
                    session.commit()
                    runs.start(server, run.id)
                    last_error = ""
                    return
                if run.status == "finished" and options.get("schedule_enabled") and not options.get("schedule_dispatched"):
                    due = (run.ended_at.timestamp() if run.ended_at else now) + options["repeat_seconds"]
                    # Naive DB datetimes contain UTC, independent of server timezone.
                    if run.ended_at:
                        from datetime import timezone
                        due = run.ended_at.replace(tzinfo=timezone.utc).timestamp() + options["repeat_seconds"]
                    if now < due:
                        continue
                    new_id = runs.identifier()
                    next_options = dict(options, service_managed=True, parent_run_id=run.id)
                    next_options.pop("schedule_dispatched", None)
                    session.add(SearchRun(id=new_id, options=json.dumps(next_options)))
                    for task in tasks:
                        if task.status == "finished":
                            session.add(SearchTask(id=runs.identifier(), run_id=new_id, position=task.position,
                                keyword=task.keyword, location=task.location, limit=task.limit))
                    options["schedule_dispatched"] = new_id
                    run.options = json.dumps(options)
                    audit.record(session, new_id, None, "scheduled_run_created", {"parent_run_id":run.id})
                    session.commit()
                    return


def start(server):
    global supervisor
    if supervisor and supervisor.is_alive():
        return
    def supervise():
        global last_error, heartbeat
        while True:
            try:
                tick(server)
            except Exception as exc:
                heartbeat = time.time()
                last_error = str(exc)
                log.exception("Collector supervisor failed; will retry")
            time.sleep(config.SERVICE_POLL_SECONDS)
    supervisor = threading.Thread(target=supervise, name="collector-supervisor", daemon=True)
    supervisor.start()
