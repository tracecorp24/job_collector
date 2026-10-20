"""Persistent queue origins and the three shared collector priorities."""
import json
import time
from sqlalchemy import func
from .models import SearchRun, SearchTask, RepairTask, Watch, RoutineCitySchedule, Setting, SearchEvent
from . import audit

LAYERS = ("manual", "repair", "routine")
LABELS = {"manual":"Manuel görevler", "repair":"Eksik / hatalı ilanlar", "routine":"Rutin taramalar"}


def layer(options):
    # Legacy watches and scheduled successors retain their original low priority.
    explicit = options.get("queue_layer")
    if explicit in LAYERS:
        return explicit
    return "routine" if options.get("watch_id") or options.get("parent_run_id") else "manual"


def eligible(session, run, now, source):
    options = json.loads(run.options or "{}")
    if run.deleted_at or options.get("user_paused"):
        return False
    waiting = run.status in ("paused", "error")
    source_wait = waiting and any(json.loads(t.stats or "{}").get("termination_reason") == "source_paused"
        for t in session.query(SearchTask).filter_by(run_id=run.id, status="paused"))
    if not ((run.status == "queued" and options.get("service_managed")) or
            (waiting and ("auto_resume_at" in options or source_wait))):
        return False
    if now < options.get("auto_resume_at", 0):
        return False
    if options.get("kind", "scrape") == "scrape" and source["paused"]:
        return False
    if options.get("during_source_wait") and (not source["paused"] or source.get("remaining_seconds", 0) <= 5):
        return False
    return True


def active_layer(server, session):
    if not server.state.running:
        return None
    if server.state.kind == "repair":
        return server.state.last.get("queue_layer", "repair")
    run = session.get(SearchRun, server.state.run_id) if server.state.run_id else None
    return layer(json.loads(run.options or "{}")) if run else "manual"


def routine_page_pending(session, run_id):
    """Let a routine finish one saved page before automatic repair preempts it."""
    run = session.get(SearchRun, run_id) if run_id else None
    options = json.loads(run.options or "{}") if run else {}
    baseline = options.get("routine_turn_after_event_id")
    if baseline is None:
        return False  # Compatibility for already-running legacy work.
    return not session.query(SearchEvent.id).filter(
        SearchEvent.run_id == run_id, SearchEvent.id > baseline,
        SearchEvent.kind == "page_result",
        func.coalesce(func.json_extract(SearchEvent.data, '$.interrupted'), 0) == 0).first()


def yield_to(server, session, incoming):
    """Request a safe checkpoint; never interrupt or start a second worker."""
    from . import runs
    current = active_layer(server, session)
    if current is None or LAYERS.index(current) <= LAYERS.index(incoming):
        return False
    if server.state.run_id:
        run = session.get(SearchRun, server.state.run_id)
        options = json.loads(run.options or "{}")
        if options.get("user_paused") or run.status != "running":
            return False
        if not options.get("priority_yield"):
            options.update(priority_yield=incoming, auto_resume_at=0, service_managed=True)
            run.options = json.dumps(options)
            run.status_reason = f"{LABELS[incoming]} için güvenli noktada sıra bırakılıyor."
            audit.record(session, run.id, None, "priority_yield", {"from":current, "to":incoming})
    server.state.stop_flag = True
    return True


def submit(server, session, run):
    """An explicit user action promotes this run only; future repeats stay routine."""
    from . import runs
    if run.deleted_at or run.status in runs.TERMINAL or run.status in ("running", "pausing", "stopping", "cancelling"):
        raise ValueError("Bu çalışma devam ettirilemez.")
    if not session.query(SearchTask).filter(SearchTask.run_id == run.id, ~SearchTask.status.in_(runs.TERMINAL)).count():
        raise ValueError("Devam ettirilecek sorgu kalmadı.")
    options = json.loads(run.options or "{}")
    options.update(queue_layer="manual", service_managed=True, auto_resume_at=0)
    options.pop("user_paused", None)
    options.pop("priority_yield", None)
    run.options = json.dumps(options)
    yield_to(server, session, "manual")
    session.commit()
    # A source pause must leave the submitted work queued, rather than reject it.
    from .transport import Coordinator
    if not server.state.running and eligible(session, run, time.time(), Coordinator().state()):
        runs.start(server, run.id)
        return False
    return True


def summary(server, session, source, now=None):
    from .repair import completion_paused
    completion_stopped = completion_paused(session)
    now = time.time() if now is None else now
    counts = {name:dict(queued=0, ready=0, waiting=0, running=0, completed=0, draft=0) for name in LAYERS}
    for run in session.query(SearchRun).filter(SearchRun.deleted_at.is_(None)):
        options = json.loads(run.options or "{}")
        stats = counts[layer(options)]
        if run.status == "finished":
            stats["completed"] += 1
        elif run.status in ("running", "pausing", "stopping"):
            stats["running"] += 1
        elif run.status in ("queued", "paused", "error"):
            if run.status == "queued" and not options.get("service_managed"):
                stats["draft"] += 1
            elif eligible(session, run, now, source):
                stats["ready"] += 1
                stats["queued"] += 1
            else:
                stats["waiting"] += 1
    repair_layer = func.coalesce(func.json_extract(RepairTask.raw, '$._queue_layer'), "repair")
    for status, stage, deadline, origin, count in session.query(RepairTask.status, RepairTask.stage,
            RepairTask.next_attempt_at, repair_layer, func.count()).group_by(RepairTask.status, RepairTask.stage, RepairTask.next_attempt_at, repair_layer):
        target = counts[origin if origin in counts else "repair"]
        if status == "done":
            target["completed"] += count
        elif status in ("pending", "retry"):
            if deadline <= now and (stage == "enrich" or not source["paused"]) and not (origin == "repair" and completion_stopped):
                target["ready"] += count
                target["queued"] += count
            else:
                target["waiting"] += count
        elif status == "paused":
            target["waiting"] += count
    active = active_layer(server, session)
    if server.state.running and server.state.kind == "repair":
        counts[active]["running"] = 1
        # The durable row stays pending while a stage is in flight.
        for bucket in ("ready", "waiting"):
            if counts[active][bucket]:
                counts[active][bucket] -= 1
                if bucket == "ready":
                    counts[active]["queued"] -= 1
                break
    due = session.query(Watch).filter(Watch.enabled.is_(True), Watch.next_due_at <= now).count()
    city_paused = session.get(Setting, "routine_cities_paused")
    if not city_paused or city_paused.value != "1":
        due += session.query(RoutineCitySchedule).filter(RoutineCitySchedule.next_due_at <= now).count()
    return dict(order=list(LAYERS), active_layer=active, source_paused=source["paused"],
        routine_schedules_due=due, layers=[dict(key=name, label=LABELS[name], priority=i+1, **counts[name]) for i,name in enumerate(LAYERS)])
