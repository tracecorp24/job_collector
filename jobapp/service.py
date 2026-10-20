"""Single collector supervisor; all scheduling decisions are persisted in SQLite."""
import json
import logging
import threading
import time
from sqlalchemy import or_, and_, func
from . import config, runs, audit, watches, maintenance, daily_summary, country_enrichment, repair, scheduling, routine_cities
from .models import SearchRun, SearchTask
from .transport import Coordinator, SourcePaused

log = logging.getLogger(__name__)
heartbeat = 0.0
last_error = ""
last_error_at = 0.0
supervisor = None
_supervisor_stop = threading.Event()
ROUTINE_IDLE_DELAY_SECONDS = 60
routine_idle_since = None


def _mark_routine_idle_start(now):
    global routine_idle_since
    routine_idle_since = now


def _routine_idle_ready(now):
    if routine_idle_since is None:
        _mark_routine_idle_start(now)
        return False
    return now - routine_idle_since >= ROUTINE_IDLE_DELAY_SECONDS


def _manual_pending(run):
    options = json.loads(run.options or "{}")
    return (run.status in ("queued", "paused", "error") and
            scheduling.layer(options) == "manual" and not options.get("user_paused") and
            (options.get("service_managed") or "auto_resume_at" in options))


def tick(server, now=None):
    global heartbeat, last_error, routine_idle_since
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
                    if any(_manual_pending(r) for r in pending) or repair.ready(session, now, source, "manual"):
                        _mark_routine_idle_start(now)
                        scheduling.yield_to(server, session, "manual")
                    elif current == "routine":
                        repair.discover(session)
                        if repair.ready(session, now, source) and not scheduling.routine_page_pending(session, server.state.run_id):
                            _mark_routine_idle_start(now)
                            scheduling.yield_to(server, session, "repair")
                session.commit()
                return
            candidates = session.query(SearchRun).filter(SearchRun.deleted_at.is_(None), or_(
                SearchRun.status.in_(("queued", "paused", "error")),
                and_(SearchRun.status == "finished", func.json_extract(SearchRun.options, '$.schedule_enabled') == 1,
                    func.json_extract(SearchRun.options, '$.schedule_dispatched').is_(None)))).order_by(SearchRun.created_at).all()
            candidates.sort(key=lambda run: bool(json.loads(run.options or "{}").get("during_source_wait")))
            routine = []
            manual_waiting = False
            for run in candidates:
                options = json.loads(run.options or "{}")
                if _manual_pending(run):
                    manual_waiting = True
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
                        if scheduling.layer(json.loads(run.options or "{}")) == "manual":
                            _mark_routine_idle_start(now)
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
            if manual_waiting:
                _mark_routine_idle_start(now)
                session.commit()
                return
            if repair.ready(session, now, source, "manual") and repair.dispatch(server, session, now, source, "manual"):
                _mark_routine_idle_start(now)
                return
            live_supervisor = bool(supervisor and supervisor.is_alive())
            # Due schedules must enter the queue even while detail work exists;
            # otherwise the fairness budget cannot see any routine candidate.
            if live_supervisor and not routine and not source["paused"] and _routine_idle_ready(now):
                if routine_cities.dispatch(session, now, source) or watches.dispatch(session, now, source):
                    return
            repair_budget = repair.source_request_budget(session, now) if routine and not source["paused"] else 0
            requests_since_routine = repair.source_request_count_since_routine(session)
            routine_turn_due = bool(live_supervisor and routine and not source["paused"] and
                                    _routine_idle_ready(now) and repair_budget and requests_since_routine >= repair_budget)
            if routine_turn_due:
                audit.record(session, None, None, "routine_fairness_yield", {
                    "repair_source_requests_since_routine":requests_since_routine,
                    "repair_source_request_budget":repair_budget,
                    "oldest_ready_detail_seconds":repair.summary(session).get("oldest_detail_seconds", 0)})
                session.commit()
            if not routine_turn_due and repair.dispatch(server, session, now, source):
                return
            # Automatic searches share the same 60-second quiet period. A
            # direct tick() remains useful for explicit queued work in tests/tools.
            if not live_supervisor or _routine_idle_ready(now):
                for run_id in routine:
                    try:
                        runs.start(server, run_id)
                        repair.reset_source_requests_since_routine(session)
                        session.commit()
                    except SourcePaused:
                        return
                    except ValueError as exc:
                        abandon(session, session.get(SearchRun, run_id), str(exc))
                        continue
                    return
                if live_supervisor and routine_cities.dispatch(session, now, source):
                    return
                if watches.dispatch(session, now, source):
                    return
            country_enrichment.dispatch(server, now)
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
    global supervisor, routine_idle_since
    if supervisor and supervisor.is_alive():
        return
    _supervisor_stop.clear()
    routine_idle_since = time.time()
    def supervise():
        while not _supervisor_stop.is_set():
            step(server)
            _supervisor_stop.wait(config.SERVICE_POLL_SECONDS)
    supervisor = threading.Thread(target=supervise, name="collector-supervisor", daemon=True)
    supervisor.start()


def stop(server, timeout=30.0):
    """Stop scheduling, let an active request observe cancellation, then close its owner."""
    global supervisor
    _supervisor_stop.set()
    server.state.stop_flag = True
    current = supervisor
    if current and current.is_alive() and current is not threading.current_thread():
        current.join(timeout=min(timeout, max(1.0, config.SERVICE_POLL_SECONDS+1)))
    worker = server.state.thread
    if worker and worker.is_alive() and worker is not threading.current_thread():
        worker.join(timeout=max(0.0, timeout))
    if worker and worker.is_alive():
        log.error("Collector worker did not stop within %.1f seconds; keeping its HTTP session open.", timeout)
        return False
    from .transport import close_shared_http_transport
    close_shared_http_transport(server.state)
    server.state.running = False
    return True
