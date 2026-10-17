"""Single collector supervisor; all scheduling decisions are persisted in SQLite."""
import json
import logging
import threading
import time
from sqlalchemy import or_, and_, func
from . import config, runs, audit, watches, maintenance, daily_summary
from .models import SearchRun, SearchTask
from .transport import Coordinator, SourcePaused

log = logging.getLogger(__name__)
heartbeat = 0.0
last_error = ""
last_error_at = 0.0
supervisor = None


def tick(server, now=None):
    global heartbeat, last_error
    now = time.time() if now is None else now
    with runs.lock:
        heartbeat = time.time()
        daily_summary.dispatch(server, now)
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
                    try:
                        runs.start(server, run.id)
                    except SourcePaused:
                        return  # Kaynak beklemesi olağan durumdur; koşu aynen bekler.
                    except ValueError as exc:
                        abandon(session, run, str(exc))
                        continue
                    return
                if run.status == "finished" and options.get("schedule_enabled") and not options.get("schedule_dispatched"):
                    due = (run.ended_at.timestamp() if run.ended_at else now) + options["repeat_seconds"]
                    # Naive DB datetimes contain UTC, independent of server timezone.
                    if run.ended_at:
                        from datetime import timezone
                        due = run.ended_at.replace(tzinfo=timezone.utc).timestamp() + options["repeat_seconds"]
                    if now < due:
                        continue
                    finished = [t for t in tasks if t.status == "finished"]
                    if not finished:
                        options.update(schedule_enabled=False, schedule_disabled_reason="no_finished_tasks")
                        run.options = json.dumps(options)
                        audit.record(session, run.id, None, "scheduled_run_skipped", {"reason":"no_finished_tasks",
                            "message":"Tamamlanmış sorgu olmadığı için tekrar turu oluşturulmadı; tekrar kapatıldı."}, "warning")
                        session.commit()
                        continue
                    new_id = runs.identifier()
                    next_options = dict(options, service_managed=True, parent_run_id=run.id)
                    next_options.pop("schedule_dispatched", None)
                    session.add(SearchRun(id=new_id, options=json.dumps(next_options)))
                    for task in finished:
                        session.add(SearchTask(id=runs.identifier(), run_id=new_id, position=task.position,
                            keyword=task.keyword, location=task.location, limit=task.limit))
                    options["schedule_dispatched"] = new_id
                    run.options = json.dumps(options)
                    audit.record(session, new_id, None, "scheduled_run_created", {"parent_run_id":run.id})
                    session.commit()
                    return
            if watches.dispatch(session, now, source):
                return
            if maintenance.due(session, now):
                maintenance.run(session, now)


def abandon(session, run, reason):
    """A run that cannot be resumed must not block the candidates behind it."""
    session.refresh(run)
    options = json.loads(run.options or "{}")
    for key in ("auto_resume_at", "service_managed"):
        options.pop(key, None)
    run.options = json.dumps(options)
    if run.status not in runs.TERMINAL:
        tasks = session.query(SearchTask).filter_by(run_id=run.id).all()
        done = any(t.status == "finished" for t in tasks)
        runs.transition(run, "finished" if done else "stopped", f"Otomatik devam başlatılamadı: {reason}")
    audit.record(session, run.id, None, "automatic_resume_failed", {"reason":reason, "status":run.status}, "warning")
    session.commit()


def step(server):
    """One supervisor turn; a successful turn clears the previous transient error."""
    global last_error, last_error_at, heartbeat
    try:
        tick(server)
        last_error = ""
    except Exception as exc:
        heartbeat = time.time()
        last_error, last_error_at = str(exc), time.time()
        log.exception("Collector supervisor failed; will retry")


def start(server):
    global supervisor
    if supervisor and supervisor.is_alive():
        return
    def supervise():
        while True:
            step(server)
            time.sleep(config.SERVICE_POLL_SECONDS)
    supervisor = threading.Thread(target=supervise, name="collector-supervisor", daemon=True)
    supervisor.start()
