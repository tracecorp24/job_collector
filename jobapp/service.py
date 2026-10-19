"""Single collector supervisor; all scheduling decisions are persisted in SQLite."""
import json
import logging
import threading
import time
from sqlalchemy import or_, and_, func
from . import config, runs, audit, watches, maintenance, daily_summary, repair, scheduling, routine_cities
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
        source = Coordinator().state()
        with server.SessionLocal() as session:
            if server.state.running:
                current = scheduling.active_layer(server, session)
                if current != "manual":
                    pending = session.query(SearchRun).filter(SearchRun.deleted_at.is_(None),
                        SearchRun.status.in_(("queued", "paused", "error"))).order_by(SearchRun.created_at).all()
                    if any(scheduling.layer(json.loads(r.options or "{}")) == "manual" and
                           scheduling.eligible(session, r, now, source) for r in pending) or repair.ready(session, now, source, "manual"):
                        scheduling.yield_to(server, session, "manual")
                    elif current == "routine":
                        repair.discover(session)
                        if repair.ready(session, now, source):
                            scheduling.yield_to(server, session, "repair")
                    session.commit()
                return
            candidates = session.query(SearchRun).filter(SearchRun.deleted_at.is_(None), or_(
                SearchRun.status.in_(("queued", "paused", "error")),
                and_(SearchRun.status == "finished", func.json_extract(SearchRun.options, '$.schedule_enabled') == 1,
                    func.json_extract(SearchRun.options, '$.schedule_dispatched').is_(None)))).order_by(SearchRun.created_at).all()
            candidates.sort(key=lambda run: bool(json.loads(run.options or "{}").get("during_source_wait")))
            routine = []
            for run in candidates:
                options = json.loads(run.options or "{}")
                if options.get("routine_city") and routine_cities.is_paused(session):
                    continue
                # Existing source-paused work is migrated without changing its deadline.
                tasks = session.query(SearchTask).filter_by(run_id=run.id).order_by(SearchTask.position).all()
                if scheduling.eligible(session, run, now, source):
                    if scheduling.layer(options) == "routine":
                        routine.append(run.id)
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
                    next_options = dict(options, service_managed=True, parent_run_id=run.id, queue_layer="routine")
                    next_options.pop("schedule_dispatched", None)
                    next_options.pop("priority_yield", None)
                    session.add(SearchRun(id=new_id, options=json.dumps(next_options)))
                    for task in finished:
                        session.add(SearchTask(id=runs.identifier(), run_id=new_id, position=task.position,
                            keyword=task.keyword, location=task.location, limit=task.limit))
                    options["schedule_dispatched"] = new_id
                    run.options = json.dumps(options)
                    audit.record(session, new_id, None, "scheduled_run_created", {"parent_run_id":run.id})
                    session.commit()
            if repair.ready(session, now, source, "manual") and repair.dispatch(server, session, now, source, "manual"):
                return
            if repair.dispatch(server, session, now, source):
                return
            for run_id in routine:
                try:
                    runs.start(server, run_id)
                except SourcePaused:
                    return
                except ValueError as exc:
                    abandon(session, session.get(SearchRun, run_id), str(exc))
                    continue
                return
            # Periodic catalogue work belongs to the live supervisor loop; a
            # direct tick() call only advances explicitly requested work.
            if supervisor and supervisor.is_alive() and routine_cities.dispatch(session, now, source):
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
