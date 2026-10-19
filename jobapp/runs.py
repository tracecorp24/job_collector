"""Durable sequential task runner. SQLite owns state; SSE is only a notification."""
import json
import threading
import uuid
import traceback
from datetime import datetime

from .models import SearchRun, SearchTask, TaskJob, SearchEvent
from sqlalchemy import func
from . import audit, config, professions, query_insights
from .transport import Coordinator

lock = threading.RLock()
TERMINAL = ("finished", "cancelled", "stopped")


def sync_export(task):
    from pathlib import Path
    from . import config
    from .search_export import _write_json
    folder = getattr(task, "folder", "")
    if not folder:
        return
    root = Path(config.ACCOUNTLESS_OUTPUT_DIR).resolve()
    target = (root / folder).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Geçersiz dışa aktarım klasörü.")
    path = target / "search.json"
    if path.exists():
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta.update(status=task.status, limit=task.limit, statusReason=task.status_reason or "")
        if task.status in ("stopped", "cancelled"):
            meta.update(terminationReason="stopped_by_user", terminationMessage=task.status_reason,
                        finishedAt=datetime.utcnow().isoformat()+"Z")
            meta.pop("pauseReason", None)
            meta.pop("error", None)
        _write_json(path, meta)


def has_started(item):
    return bool(item.started_at or getattr(item, "folder", "") or json.loads(getattr(item, "checkpoint", "{}") or "{}").get("collected"))


def transition(item, status, reason=""):
    now = datetime.utcnow()
    if item.resumed_at and status != "running":
        item.active_seconds = (item.active_seconds or 0) + max(0, (now-item.resumed_at).total_seconds())
        item.resumed_at = None
    if status == "running":
        item.started_at = item.started_at or now
        item.resumed_at = now
        item.ended_at = None
    elif status in TERMINAL:
        item.ended_at = now
    item.status = status
    item.status_reason = reason
    sync_export(item)


def timing(item):
    now = datetime.utcnow()
    active = (item.active_seconds or 0) + (max(0, (now-item.resumed_at).total_seconds()) if item.resumed_at else 0)
    elapsed = max(0, ((item.ended_at or now)-item.started_at).total_seconds()) if item.started_at and (item.status not in TERMINAL or item.ended_at) else None
    return dict(started_at=item.started_at.isoformat() if item.started_at else None,
                ended_at=item.ended_at.isoformat() if item.ended_at else None,
                elapsed_seconds=elapsed, active_seconds=active, status_reason=item.status_reason or "")


def identifier():
    return uuid.uuid4().hex


def snapshot(session, run):
    from .scheduling import layer
    tasks = session.query(SearchTask).filter_by(run_id=run.id).order_by(SearchTask.position).all()
    stats = json.loads(run.stats)
    links = session.query(TaskJob.is_new, TaskJob.outcome, func.count()).join(SearchTask, SearchTask.id == TaskJob.task_id).filter(SearchTask.run_id == run.id).group_by(TaskJob.is_new, TaskJob.outcome).all()
    counts = {"new":0, "updated":0, "unchanged":0}
    for is_new, outcome, count in links:
        counts[outcome if outcome in counts else "new" if is_new else "updated"] += count
    stats.update(counts)
    task_counts = {t.id:dict(new=0, updated=0, unchanged=0) for t in tasks}
    for task_id, is_new, outcome, count in session.query(TaskJob.task_id, TaskJob.is_new, TaskJob.outcome, func.count()).filter(TaskJob.task_id.in_(task_counts)).group_by(TaskJob.task_id, TaskJob.is_new, TaskJob.outcome):
        task_counts[task_id][outcome if outcome in counts else "new" if is_new else "updated"] += count
    return {"id": run.id, "kind":json.loads(run.options).get("kind", "scrape"), "queue_layer":layer(json.loads(run.options or "{}")), "status": run.status, "stats": stats,
            "next_attempt_at":json.loads(run.options or "{}").get("auto_resume_at"),
            "automatic_resume":run.status in ("paused", "error") and not json.loads(run.options or "{}").get("user_paused") and ("auto_resume_at" in json.loads(run.options or "{}") or any(json.loads(t.stats or "{}").get("termination_reason") == "source_paused" for t in tasks if t.status == "paused")),
            **timing(run), "has_started":has_started(run) or any(has_started(t) for t in tasks),
            "created_at": run.created_at.isoformat(), "deleted_at": run.deleted_at.isoformat() if run.deleted_at else None,
            "tasks": [{"id": t.id, "keyword": t.keyword, "location": t.location, "limit": t.limit, "package": t.package or "",
                       "keyword_language": t.keyword_language, "profession_group": t.profession_group,
                       "profession_code": t.profession_code,
                       "status": t.status, "folder": t.folder, "error": t.error,
                       "count": json.loads(t.checkpoint).get("collected", 0),
                       "stats":dict(json.loads(t.stats), **task_counts[t.id]), **timing(t), "has_started":has_started(t)} for t in tasks]}


def recover(factory):
    with factory() as session:
        for run in session.query(SearchRun).filter(SearchRun.status.in_(["running", "pausing", "cancelling", "stopping"])):
            previous = run.status
            transition(run, "stopped" if run.status == "stopping" else "cancelled" if run.status == "cancelling" else "paused", "Sunucu yeniden başlatıldığı için süreç duraklatıldı.")
            audit.record(session, run.id, None, "process_recovered", {"previous_status":previous, "status":run.status, "reason":"server_restart"}, "warning")
            if previous == "running":
                options = json.loads(run.options or "{}")
                options["auto_resume_at"] = 0
                run.options = json.dumps(options)
            for task in session.query(SearchTask).filter(SearchTask.run_id == run.id, SearchTask.status.in_(["running", "pausing", "stopping"])):
                transition(task, "stopped" if task.status == "stopping" or run.status == "stopped" else "paused", run.status_reason)
        session.commit()


def start(server, run_id):
    """Caller holds lock, including the check that no other operation is active."""
    with server.SessionLocal() as session:
        run = session.get(SearchRun, run_id)
        if not run or run.deleted_at or run.status in TERMINAL:
            raise ValueError("Bu çalışma devam ettirilemez.")
        if json.loads(run.options).get("kind", "scrape") == "scrape":
            Coordinator().ensure_allowed()
        if not session.query(SearchTask).filter(SearchTask.run_id == run_id, ~SearchTask.status.in_(TERMINAL)).count():
            raise ValueError("Devam ettirilecek sorgu kalmadı.")
        transition(run, "running")
        options = json.loads(run.options or "{}")
        options.pop("auto_resume_at", None)
        options.pop("user_paused", None)
        options.pop("priority_yield", None)
        run.options = json.dumps(options)
        run.updated_at = datetime.utcnow()
        session.commit()
        kind = json.loads(run.options).get("kind", "scrape")
    server.state.running = True
    server.state.stop_flag = False
    server.state.task_stop_id = None
    server.state.kind = kind
    server.state.run_id = run_id
    server.state.last = {"state": "running"}
    server.state.thread = threading.Thread(target=worker if kind == "scrape" else maintenance_worker, args=(server, run_id), daemon=True)
    server.state.thread.start()


def worker(server, run_id):
    from .pipeline import run_scrape
    try:
        attempt_id = identifier()
        with server.SessionLocal() as session:
            options = json.loads(session.get(SearchRun, run_id).options)
            task_ids = [t.id for t in session.query(SearchTask).filter_by(run_id=run_id).order_by(SearchTask.position)]
            audit.record(session, run_id, None, "run_started", {"attempt_id":attempt_id, "options":options})
            session.commit()
        for task_id in task_ids:
            if server.state.stop_flag:
                break
            with lock, server.SessionLocal() as session:
                task = session.get(SearchTask, task_id)
                if task.status in TERMINAL:
                    continue
                transition(task, "running")
                task.error = ""
                query = professions.query_metadata(task.keyword, task.location)
                task.keyword_language = query["keyword_language"]
                task.profession_group = query["profession_group"]
                task.profession_code = query["profession_code"]
                task.location_key = query["location_key"]
                args = {"keyword": task.keyword, "location": task.location, "limit": task.limit}
                checkpoint, folder = json.loads(task.checkpoint), task.folder
                session.commit()
            failed = []

            def emit(kind, data):
                data = dict(data, attempt_id=attempt_id)
                with server.SessionLocal() as session:
                    task = session.get(SearchTask, task_id)
                    run = session.get(SearchRun, run_id)
                    if kind != "checkpoint":
                        audit.record(session, run_id, task_id, kind, data, data.get("level", "error" if kind == "error" else "info"))
                    if kind == "task_start":
                        task.folder = data.get("folder", task.folder)
                    elif kind == "checkpoint":
                        task.checkpoint = json.dumps(data)
                        audit.record(session, run_id, task_id, "checkpoint_saved", {"attempt_id":attempt_id, "page":data.get("page"), "collected":data.get("collected"), "seen_count":len(data.get("seen", []))})
                    elif kind in ("cache_hit", "cache_miss", "job_skipped"):
                        stats = json.loads(task.stats)
                        key = "cache_hits" if kind == "cache_hit" else "cache_misses" if kind == "cache_miss" else "skipped"
                        stats[key] = stats.get(key, 0) + 1
                        task.stats = json.dumps(stats)
                    elif kind == "page_result":
                        stats = json.loads(task.stats)
                        stats["detail_failures"] = stats.get("detail_failures", 0) + data.get("detail_failures", 0)
                        task.stats = json.dumps(stats)
                    elif kind == "job":
                        existing = session.get(TaskJob, (task_id, data["id"]))
                        if not existing:
                            session.add(TaskJob(task_id=task_id, job_id=data["id"], is_new=data.get("is_new", False)))
                        stats = json.loads(run.stats)
                        # Job events follow an upsert; pipeline's final stats carry exact counts.
                        stats["collected"] = stats.get("collected", 0) + 1
                        run.stats = json.dumps(stats)
                    elif kind == "task_done":
                        yielding = json.loads(run.options or "{}").get("priority_yield")
                        if yielding and server.state.stop_flag:
                            data["reason"] = "priority_yield"
                        task.stats = json.dumps({**json.loads(task.stats), **data.get("stats", {}), "termination_reason": data.get("reason")})
                        stopping = task.status == "stopping" or run.status == "stopping"
                        reason = (
                            "Kullanıcı sorguyu durdurdu. Toplanan ilanlar korundu." if stopping else
                            "Daha yüksek öncelikli görevler için sıra bırakıldı; devam noktası korundu." if yielding and server.state.stop_flag else
                            "Kullanıcı taramayı duraklattı." if server.state.stop_flag else
                            "Hedefe ulaşıldı." if data.get("reason") == "reached_limit" else
                            "Yeni ilan verimi eşik altına (%20) düştü; kota koruması için tamamlandı." if data.get("reason") == "low_yield_threshold" else
                            "Kaynağın döndürdüğü sonuçlar tamamlandı."
                        )
                        transition(task, "stopped" if stopping else "paused" if server.state.stop_flag else "finished", reason)
                        if data.get("reason") == "page_fetch_failed" and not server.state.stop_flag:
                            transition(task, "error", "Arama sayfası alınamadı; tekrar devam edebilirsiniz.")
                            task.error = "Arama sayfası alınamadı. Sonuçlar korundu; tekrar devam edebilirsiniz."
                            failed.append(task.error)
                        if task.status == "finished":
                            reset_error_streak(run)
                        session.flush()
                        if task.status in ("finished", "stopped", "error"):
                            query_insights.persist(session, task)
                    elif kind == "source_paused":
                        options = json.loads(run.options or "{}")
                        options["auto_resume_at"] = data.get("blocked_until", 0)
                        run.options = json.dumps(options)
                        task.status, task.error = "paused", data.get("message", "Kaynak beklemede.")
                        transition(task, "paused", task.error)
                        task.stats = json.dumps({**json.loads(task.stats), "source_state": data, "termination_reason": "source_paused"})
                    elif kind == "error":
                        task.error = data.get("msg", "Tarama tamamlanamadı.")
                        transition(task, "error", task.error)
                        session.flush()
                        query_insights.persist(session, task)
                        failed.append(task.error)
                    run.updated_at = datetime.utcnow()
                    session.commit()
                # Per-task finish/error must not release the shared worker or claim the whole run finished.
                if kind not in ("finished", "error", "checkpoint"):
                    server.state.emit(kind, dict(data, run_id=run_id, task_id=task_id))
                elif kind == "error":
                    server.state.emit("notice", {"msg": data.get("msg"), "level": "error"})

            result = run_scrape([args], [args["location"]], classify_backend=options.get("classify_backend", "rules"),
                                use_embeddings=options.get("use_embeddings", False), emit=emit,
                                should_stop=lambda: server.state.stop_flag or getattr(server.state, "task_stop_id", None) == task_id,
                                checkpoint=checkpoint, resume_folder=folder or None, search_id=task_id, run_id=run_id, attempt_id=attempt_id,
                                mode=options.get("mode", "incremental"), refresh_details=options.get("refresh_details", False),
                                search_options=dict({k:options[k] for k in ("posted_within", "sort_recent", "stop_when_known", "low_yield_threshold") if options.get(k) is not None},
                                    defer_details=options.get("defer_details", config.DEFER_DETAILS)))
            with server.SessionLocal() as session:
                run = session.get(SearchRun, run_id)
                stats = json.loads(run.stats)
                for key in ("new", "updated", "unchanged", "skipped"):
                    stats[key] = stats.get(key, 0) + result.get(key, 0)
                stats["errors"] = stats.get("errors", 0) + len(failed)
                run.stats = json.dumps(stats)
                task = session.get(SearchTask, task_id)
                if task.status == "stopping":
                    transition(task, "stopped", "Kullanıcı sorguyu durdurdu. Toplanan ilanlar korundu.")
                session.commit()
            server.state.task_stop_id = None
            if failed or result.get("paused"):
                break
        with server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            tasks = session.query(SearchTask).filter_by(run_id=run_id).all()
            if run.status == "stopping":
                transition(run, "stopped", "Kullanıcı kuyruğu durdurdu. Toplanan ilanlar korundu.")
                for task in tasks:
                    if task.status not in TERMINAL:
                        transition(task, "stopped", run.status_reason)
            elif run.status == "cancelling":
                run.status = "cancelled"
                for task in tasks:
                    if task.status != "finished":
                        task.status = "cancelled"
            elif server.state.stop_flag or any(t.status == "paused" for t in tasks):
                run.status = "paused"
            elif any(t.status == "error" for t in tasks):
                run.status = "error"
            else:
                run.status = "finished"
            if run.status == "paused" and json.loads(run.options or "{}").get("priority_yield"):
                run.status_reason = "Daha yüksek öncelikli görevler için sıra bırakıldı; otomatik devam edecek."
            transition(run, run.status, run.status_reason or next((t.status_reason for t in tasks if t.status in ("paused", "error")), ""))
            if run.status == "error":
                schedule_error_retry(session, run)
            elif run.status == "finished":
                reset_error_streak(run)
            run.updated_at = datetime.utcnow()
            audit.record(session, run_id, None, "run_completed", {"status":run.status, "stats":json.loads(run.stats), "attempt_id":attempt_id})
            session.commit()
            result = snapshot(session, run)
        server.state.emit("run_finished", result)
    except Exception as exc:
        with server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            transition(run, "error", str(exc))
            schedule_error_retry(session, run)
            audit.record(session, run_id, None, "error", {"msg":str(exc), "error_type":type(exc).__name__, "traceback":traceback.format_exc()}, "error")
            for task in session.query(SearchTask).filter_by(run_id=run_id, status="running"):
                transition(task, "error", str(exc))
                task.error = str(exc)
            session.commit()
        server.state.emit("notice", {"msg": "Çalışma durdu. Sonuçlar korundu; geçmişten devam edebilirsiniz.", "level": "error"})
    finally:
        with lock:
            server.state.running = False
            server.state.stop_flag = False
            server.state.run_id = None
            with server.SessionLocal() as session:
                final = session.get(SearchRun, run_id)
                server.state.last = {"state":final.status if final else "idle", "run_id":run_id}


def reset_error_streak(run):
    options = json.loads(run.options or "{}")
    if options.pop("error_retry_streak", None) is not None:
        run.options = json.dumps(options)


def schedule_error_retry(session, run):
    import time
    from . import config
    options = json.loads(run.options or "{}")
    if options.get("user_paused"):
        return
    streak = options.get("error_retry_streak", 0) + 1
    delay = min(config.MAX_ACCESS_PAUSE_SECONDS, 300 * 2 ** min(streak-1, 16))
    options.update(error_retry_streak=streak, auto_resume_at=time.time()+delay)
    run.options = json.dumps(options)
    audit.record(session, run.id, None, "automatic_retry_scheduled", {"retry_at":options["auto_resume_at"], "seconds":delay, "attempt":streak, "reason":run.status_reason}, "warning")


def maintenance_worker(server, run_id):
    import time
    from .pipeline import run_embed_backfill, run_classify_backfill
    attempt_id = identifier()
    try:
        with server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            options = json.loads(run.options)
            task = session.query(SearchTask).filter_by(run_id=run_id).one()
            task_id = task.id
            checkpoint = json.loads(task.checkpoint)
            completed = set(checkpoint.get("processed_ids", []))
            transition(task, "running")
            task.error = ""
            audit.record(session, run_id, task_id, "run_started", {"attempt_id":attempt_id, "options":options})
            session.commit()

        def emit(kind, data):
            data = dict(data, attempt_id=attempt_id)
            with server.SessionLocal() as session:
                task = session.get(SearchTask, task_id)
                run = session.get(SearchRun, run_id)
                audit.record(session, run_id, task_id, kind, data, data.get("level", "error" if kind == "error" else "info"))
                if kind == "queue_ready":
                    checkpoint["target_total"] = len(completed) + data.get("total", 0)
                if kind == "processing_result":
                    stats = json.loads(run.stats)
                    if data.get("status") == "saved":
                        completed.add(data["job_id"])
                        key = {"embed": "embedded"}.get(options["kind"], "classified")
                        stats[key] = len(completed)
                    else:
                        stats["skipped"] = stats.get("skipped", 0) + 1
                    run.stats = json.dumps(stats)
                checkpoint.update(processed_ids=sorted(completed), collected=len(completed))
                task.checkpoint = json.dumps(checkpoint)
                if kind == "error":
                    task.error = data.get("msg", "İşlem tamamlanamadı.")
                session.commit()
            if kind not in ("finished", "error"):
                server.state.emit(kind, dict(data, run_id=run_id, task_id=task_id))

        remaining_limit = None if options.get("limit") is None else max(0, options["limit"] - len(completed))
        background = options.get("during_source_wait", False)
        deadline = Coordinator().state()["blocked_until"] - 5 if background else None
        completed_before = len(completed)
        def should_yield():
            return server.state.stop_flag or bool(background and (time.time() >= deadline or len(completed)-completed_before >= 5))
        common = dict(limit=remaining_limit, force=options.get("force", False), skip_ids=sorted(completed),
                      emit=emit, should_stop=should_yield, ready_only=background)
        if remaining_limit == 0:
            result = {"total":0, "termination_reason":"completed"}
        elif options["kind"] == "embed":
            result = run_embed_backfill(**common)
        else:
            result = run_classify_backfill(backend=options.get("backend", "local"), model=options.get("model"), patient=not background, **common)
        with server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            task = session.get(SearchTask, task_id)
            task.stats = json.dumps(result)
            if run.status == "stopping":
                run.status = "stopped"
            elif run.status == "cancelling":
                run.status = "cancelled"
            elif server.state.stop_flag:
                run.status = "paused"
            elif task.error or result.get("termination_reason") == "model_unavailable":
                run.status = "error"
            elif background and result.get("termination_reason") == "stopped_by_user":
                run.status = "paused"
            else:
                run.status = "finished"
            reason = "Kullanıcı işlemi durdurdu." if run.status == "stopped" else "Kullanıcı işlemi duraklattı." if run.status == "paused" else task.error or "Analiz modeli erişilemedi veya kotası doldu." if run.status == "error" else "İşlem tamamlandı."
            if background and run.status == "paused" and not server.state.stop_flag:
                reason = "Analiz grubu tamamlandı; kaynak beklemesinde kaldığı yerden devam edecek."
                current_options = json.loads(run.options or "{}")
                current_options["auto_resume_at"] = 0
                run.options = json.dumps(current_options)
            transition(run, run.status, reason)
            transition(task, run.status, reason)
            audit.record(session, run_id, task_id, "run_completed", {"attempt_id":attempt_id, "status":run.status, "stats":result})
            session.commit()
            response = snapshot(session, run)
        server.state.emit("run_finished", response)
    except Exception as exc:
        with server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            transition(run, "error", str(exc))
            for task in session.query(SearchTask).filter_by(run_id=run_id, status="running"):
                transition(task, "error", str(exc))
                task.error = str(exc)
            audit.record(session, run_id, None, "error", {"msg":str(exc), "error_type":type(exc).__name__, "traceback":traceback.format_exc()}, "error")
            session.commit()
        server.state.emit("notice", {"msg":"Yeniden işleme durdu; süreç raporundan ayrıntıları inceleyin.", "level":"error"})
    finally:
        with lock:
            server.state.running = False
            server.state.stop_flag = False
            server.state.run_id = None
