"""Workspace API for persistent runs, contextual search and reversible deletion."""
import json
import shutil
import re
from pathlib import Path
from datetime import datetime
from flask import jsonify, request, Response
from sqlalchemy import case, func, String
from werkzeug.datastructures import MultiDict

from . import config, runs, filters, audit, fit
from .models import Job, SearchRun, SearchTask, TaskJob, SearchEvent
from .search_export import _write_json
from .transport import Coordinator, SourcePaused


def scrape_options(body):
    mode = body.get("mode", "incremental")
    if mode not in ("incremental", "full"):
        raise ValueError("Geçersiz tarama yöntemi.")
    return {"mode":mode, "refresh_details":bool(body.get("refresh_details"))}


def safe_folder(name):
    root = Path(config.ACCOUNTLESS_OUTPUT_DIR).resolve()
    path = (root / name).resolve()
    if not name or path == root or not path.is_relative_to(root):
        raise ValueError("Geçersiz arama klasörü.")
    return path


def sync_exports(jobs, purge=False):
    """Apply visibility to every snapshot of a shared job, preserving history."""
    root = Path(config.ACCOUNTLESS_OUTPUT_DIR)
    for job in jobs:
        for file in root.glob(f"*/ilan_havuzu/ap-{job.source}-{job.external_id}.json"):
            if purge:
                file.unlink()
            else:
                data = json.loads(file.read_text(encoding="utf-8"))
                data["_deletedAt"] = job.deleted_at.isoformat() if job.deleted_at else None
                _write_json(file, data)


def task_data(body):
    raw = body.get("tasks")
    if raw is None:
        keywords = body.get("keywords") or []
        locations = body.get("locations") or [config.DEFAULT_LOCATION]
        raw = []
        for kw in keywords:
            item = kw if isinstance(kw, dict) else {"keyword": kw}
            for location in ([item["location"]] if item.get("location") else locations):
                raw.append(dict(item, location=location, limit=item.get("limit", body.get("limit"))))
    if not isinstance(raw, list) or not raw:
        raise ValueError("En az bir arama görevi ekleyin.")
    result = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Geçersiz görev.")
        keyword = str(item.get("keyword") or "").strip()
        location = str(item.get("location") or config.DEFAULT_LOCATION).strip()
        limit = item.get("limit")
        if limit not in (None, ""):
            try:
                n = int(limit)
                if isinstance(limit, bool) or str(n) != str(limit).strip() or n <= 0:
                    raise ValueError()
                limit = n
            except (ValueError, TypeError):
                raise ValueError("İlan limiti pozitif bir tam sayı olmalı.")
        else:
            limit = None
        if not keyword or len(keyword) > 512 or len(location) > 512:
            raise ValueError("Unvan ve konum 1–512 karakter olmalı.")
        identifier = str(item.get("id") or runs.identifier())
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", identifier):
            raise ValueError("Geçersiz görev kimliği.")
        package = re.sub(r"\s+", " ", str(item.get("package") or "")).strip()[:160]
        result.append({"id":identifier, "keyword": keyword, "location": location, "limit": limit, "package": package})
    if len({item["id"] for item in result}) != len(result):
        raise ValueError("Görev kimlikleri benzersiz olmalı.")
    return result


def install(server):
    app = server.app

    @app.errorhandler(SourcePaused)
    def source_blocked(exc):
        return jsonify(ok=False, error=str(exc), source_state=exc.state), 409

    @app.get("/api/source/status")
    def source_status():
        return jsonify(Coordinator().state())

    @app.post("/api/source/acknowledge")
    def source_acknowledge():
        state = Coordinator().acknowledge()
        with server.SessionLocal() as session:
            audit.record(session, None, None, "source_acknowledged", {"actor":"web", "source_state":state})
            session.commit()
        return jsonify(ok=True, source_state=state)

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(ok=False, error=str(exc)), 400

    def selection(session):
        """Semantic/profile ranking shares the same filters as navigation."""
        args = request.args
        q = filters.filtered(session, args)
        target, mode, fallback = None, "", False
        if args.get("search") and args.get("semantic") in ("1", "true"):
            from .embed import embed_text
            target = embed_text(args["search"])
            if target is None:
                copy = MultiDict(args)
                copy.pop("semantic", None)
                q = filters.filtered(session, copy)
                fallback = True
            else:
                mode = "semantic"
        elif args.get("sort") == "fit":
            saved = server._load_profile(session)
            current = fit.profile_hash(saved["text"])
            if current and q.filter(Job.fit_profile == current).first():
                # Groq puanları: güncel profil için puanlananlar puana göre önde, kalanlar en yeni önce.
                scored = Job.fit_profile == current
                ordered = q.order_by(case((scored, 0), else_=1), case((scored, Job.fit_score), else_=None).desc(),
                                     Job.scraped_at.desc(), Job.id.desc())
                return [row[0] for row in ordered.with_entities(Job.id).all()], {}, "fit", False
            target = saved["embedding"]
            mode = "fit" if target else ""
            fallback = not bool(target)
        if target is not None:
            ids, scores = server._rank_by_embedding(q, target)
            return ids, scores, mode, fallback
        return [row[0] for row in filters.ordered(q, args).with_entities(Job.id).all()], {}, mode, fallback

    def jobs():
        with server.SessionLocal() as session:
            ids, scores, mode, fallback = selection(session)
            page = max(1, filters.number(request.args, "page", True) or 1)
            size = min(100, max(1, filters.number(request.args, "per_page", True) or 24))
            pages = (len(ids) + size - 1) // size
            page = min(page, max(1, pages))
            subset = ids[(page - 1) * size:page * size]
            rows = {j.id: j for j in session.query(Job).filter(Job.id.in_(subset))}
            return jsonify(jobs=[dict(rows[i].to_dict(), **({"score": round(scores[i], 4)} if i in scores else {})) for i in subset],
                           total=len(ids), page=page, pages=pages, per_page=size, mode=mode, semantic_fallback=fallback)
    app.view_functions["api_jobs"] = jobs

    @app.get("/api/jobs/<int:job_id>/navigation")
    def navigation(job_id):
        with server.SessionLocal() as session:
            ids, _, _, _ = selection(session)
            if job_id not in ids:
                return jsonify(previous=None, next=None, position=0, total=len(ids))
            i = ids.index(job_id)
            return jsonify(previous=ids[i-1] if i else None, next=ids[i+1] if i+1 < len(ids) else None,
                           position=i+1, total=len(ids))

    def facets():
        with server.SessionLocal() as session:
            result = {}
            for key, column in filters.FIELDS.items():
                q = filters.filtered(session, request.args, omit=key)
                if key in ("search_term", "search_location"):
                    column = SearchTask.keyword if key == "search_term" else SearchTask.location
                    q = q.join(TaskJob, TaskJob.job_id == Job.id).join(SearchTask, SearchTask.id == TaskJob.task_id)
                count = func.count(func.distinct(Job.id))
                result[key] = [{"value": value or "__missing__", "count": n}
                               for value, n in q.with_entities(func.coalesce(column, ""), count).group_by(func.coalesce(column, "")).order_by(count.desc()).all()]
            counts = {}
            for row in filters.filtered(session, request.args, omit="skills").with_entities(Job.tags):
                for tag in set(json.loads(row[0] or "[]")):
                    counts[tag] = counts.get(tag, 0) + 1
            result["skills"] = [{"value": k, "count": v} for k, v in sorted(counts.items(), key=lambda i: (-i[1], i[0]))]
            base = filters.filtered(session, request.args)
            saved = server._load_profile(session)
            current = fit.profile_hash(saved["text"])
            result.update(total=base.count(), active_total=session.query(Job).filter(Job.deleted_at.is_(None), Job.quality_ok.is_(True)).count(),
                          missing_embeddings=base.filter(Job.embedding.is_(None)).count(),
                          not_locally_classified=base.filter(Job.classified_by != "local").count(),
                          not_groq_classified=base.filter(Job.classified_by != "groq").count(),
                          has_profile=bool(saved["embedding"]) or bool(current), profile_hash=current,
                          unscored_fit=base.filter((Job.fit_profile != current) | Job.fit_profile.is_(None) | Job.fit_score.is_(None)).count() if current else 0,
                          groq_available=bool(config.GROQ_API_KEY))
            return jsonify(result)
    app.view_functions["api_facets"] = facets

    def trash_jobs(ids=None, action="delete"):
        with server.SessionLocal() as session:
            q = session.query(Job)
            if ids is not None:
                q = q.filter(Job.id.in_(ids))
            else:
                q = filters.filtered(session, request.args)
            jobs = q.all()
            if action == "purge" and any(j.deleted_at is None for j in jobs):
                raise ValueError("Kalıcı silmeden önce kayıtları çöp kutusuna taşıyın.")
            for job in jobs:
                job.deleted_at = None if action == "restore" else datetime.utcnow()
            sync_exports(jobs, purge=action == "purge")
            affected = [j.id for j in jobs]
            if action == "purge":
                session.query(TaskJob).filter(TaskJob.job_id.in_(affected)).delete(synchronize_session=False)
                for job in jobs:
                    session.delete(job)
            session.commit()
            return jsonify(ok=True, count=len(affected), ids=affected)

    app.view_functions["api_job_delete"] = lambda job_id: trash_jobs([job_id])
    app.view_functions["api_jobs_delete_all"] = lambda: trash_jobs()

    @app.post("/api/trash/jobs")
    def manage_trash():
        body = request.get_json(silent=True) or {}
        ids = body.get("ids")
        if not isinstance(ids, list) or not ids or any(type(i) is not int for i in ids):
            raise ValueError("İşlem yapılacak ilanları seçin.")
        action = body.get("action")
        if action not in ("delete", "restore", "purge"):
            raise ValueError("Geçersiz işlem.")
        return trash_jobs(ids, action)

    def scrape():
        body = request.get_json(silent=True) or {}
        if body.get("require_login", False) is not False:
            raise ValueError("Bu uygulama yalnızca hesapsız taramayı destekler.")
        tasks = task_data(body)
        backend = body.get("classify_backend", "rules")
        if backend not in ("rules", "local", "claude", "groq"):
            raise ValueError("Geçersiz analiz yöntemi.")
        with runs.lock:
            if server.state.running:
                raise ValueError("Devam eden işlem var. Bitmesini bekleyin veya duraklatın.")
            run_id = runs.identifier()
            with server.SessionLocal() as session:
                options = {"kind":"scrape", "audit_version":audit.VERSION, "classify_backend": backend, "use_embeddings": bool(body.get("use_embeddings")), **scrape_options(body)}
                session.add(SearchRun(id=run_id, options=json.dumps(options)))
                audit.record(session, run_id, None, "run_created", {"actor":"web", "options":options})
                for i, item in enumerate(tasks):
                    if session.get(SearchTask, item["id"]):
                        raise ValueError("Bu görev kimliği zaten kullanımda.")
                    session.add(SearchTask(run_id=run_id, position=i, **item))
                    audit.record(session, run_id, item["id"], "task_queued", item)
                session.commit()
            runs.start(server, run_id)
        return jsonify(ok=True, run_id=run_id)
    app.view_functions["api_scrape"] = scrape

    @app.post("/api/queue")
    def save_queue():
        body = request.get_json(silent=True) or {}
        tasks = task_data(body) if body.get("tasks") else []
        with runs.lock, server.SessionLocal() as session:
            run = session.get(SearchRun, str(body.get("run_id"))) if body.get("run_id") else None
            if body.get("run_id") and (not run or run.status != "queued" or run.deleted_at):
                raise ValueError("Bu kuyruk zaten başlatılmış veya kaldırılmış. Yeni kuyruk oluşturun.")
            if not run:
                if not tasks:
                    return jsonify(ok=True, run_id=None)
                run = SearchRun(id=runs.identifier(), status="queued")
                session.add(run)
                audit.record(session, run.id, None, "run_created", {"actor":"queue_editor"})
            options = {"kind":"scrape", "audit_version":audit.VERSION, "classify_backend":body.get("classify_backend", "rules"), "use_embeddings":bool(body.get("use_embeddings")), **scrape_options(body)}
            if options["classify_backend"] not in ("rules", "local", "claude", "groq"):
                raise ValueError("Geçersiz analiz yöntemi.")
            if run.options != json.dumps(options):
                audit.record(session, run.id, None, "queue_options_changed", {"before":json.loads(run.options or "{}"), "after":options})
            run.options = json.dumps(options)
            old = {t.id:t for t in session.query(SearchTask).filter_by(run_id=run.id)}
            keep = {t["id"] for t in tasks}
            for identifier, task in old.items():
                if identifier not in keep and task.status != "cancelled":
                    task.status = "cancelled"
                    audit.record(session, run.id, identifier, "queue_task_removed", {"reason":"draft_edit"})
            for i, item in enumerate(tasks):
                task = old.get(item["id"])
                if not task:
                    if session.get(SearchTask, item["id"]):
                        raise ValueError("Bu görev başka sürece ait; yeni bir görev kimliği kullanın.")
                    task = SearchTask(run_id=run.id, position=i, **item)
                    session.add(task)
                    audit.record(session, run.id, task.id, "task_queued", dict(item, position=i))
                else:
                    if task.status in runs.TERMINAL:
                        continue  # A stale autosave must never resurrect history.
                    before = {k:getattr(task,k) for k in ("keyword","location","limit","position","status","package")}
                    after = dict(keyword=item["keyword"], location=item["location"], limit=item["limit"], position=i, status="queued", package=item["package"])
                    if before != after:
                        audit.record(session, run.id, task.id, "queue_task_changed", {"before":before, "after":after})
                    for key,value in after.items():
                        setattr(task,key,value)
            if not tasks:
                run.status = "cancelled"
                audit.record(session, run.id, None, "run_completed", {"status":"cancelled", "reason":"empty_queue"})
            run.updated_at = datetime.utcnow()
            session.commit()
            return jsonify(ok=True, run_id=run.id if tasks else None)

    @app.get("/api/runs")
    def list_runs():
        with server.SessionLocal() as session:
            q = session.query(SearchRun)
            q = q.filter(SearchRun.deleted_at.isnot(None) if request.args.get("trash") == "1" else SearchRun.deleted_at.is_(None))
            return jsonify(runs=[runs.snapshot(session, r) for r in q.order_by(SearchRun.created_at.desc())])

    @app.get("/api/runs/<run_id>")
    def get_run(run_id):
        with server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            if not run:
                return jsonify(error="Çalışma bulunamadı."), 404
            return jsonify(runs.snapshot(session, run))

    @app.get("/api/runs/<run_id>/report")
    def process_report(run_id):
        with server.SessionLocal() as session:
            data = audit.report(session, run_id, request.args.get("task_id"))
        if request.args.get("download") == "1":
            return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json",
                            headers={"Content-Disposition":'attachment; filename="surec-raporu.json"'})
        return jsonify(data)

    @app.get("/api/runs/<run_id>/logs")
    def run_logs(run_id):
        with server.SessionLocal() as session:
            if not session.get(SearchRun, run_id):
                return jsonify(error="Çalışma bulunamadı."), 404
            q = session.query(SearchEvent).filter_by(run_id=run_id)
            if request.args.get("task_id"):
                q = q.filter_by(task_id=request.args["task_id"])
            if request.args.get("kind"):
                q = q.filter_by(kind=request.args["kind"])
            if request.args.get("level"):
                q = q.filter_by(level=request.args["level"])
            if request.args.get("query"):
                q = q.filter(filters.contains(SearchEvent.data, request.args["query"]))
            for key in ("request_id", "job_id", "attempt_id"):
                if request.args.get(key):
                    q = q.filter(func.cast(func.json_extract(SearchEvent.data, "$." + key), String) == request.args[key])
            before = filters.number(request.args, "before", True)
            if before:
                q = q.filter(SearchEvent.id < before)
            rows = q.order_by(SearchEvent.id.desc()).limit(201).all()
            events = [{"id": e.id, "run_id":e.run_id, "search_id": e.task_id, "kind": e.kind, "level": e.level,
                       "ts": e.created_at.isoformat() + "Z", "data": json.loads(e.data)} for e in rows[:200]]
            reports = session.query(SearchEvent).filter_by(run_id=run_id, kind="page_result")
            if request.args.get("task_id"):
                reports = reports.filter_by(task_id=request.args["task_id"])
            totals = {"cards_returned": 0, "collected": 0, "duplicates": 0, "detail_failures": 0, "not_processed": 0, "invalid_cards": 0}
            for report in reports:
                data = json.loads(report.data)
                for key in totals:
                    totals[key] += data.get(key, 0)
            return jsonify(events=events, totals=totals, next_before=rows[199].id if len(rows) > 200 else None)

    @app.get("/api/runs/<run_id>/logs/download")
    def download_logs(run_id):
        with server.SessionLocal() as session:
            events = session.query(SearchEvent).filter_by(run_id=run_id).order_by(SearchEvent.id).all()
            text = "\n".join(json.dumps({"id": e.id, "ts": e.created_at.isoformat() + "Z", "search_id": e.task_id,
                                          "kind": e.kind, "level": e.level, "data": json.loads(e.data)}, ensure_ascii=False) for e in events)
        return Response(text, mimetype="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="arama-loglari.jsonl"'})

    @app.patch("/api/runs/<run_id>")
    def edit_run(run_id):
        body = request.get_json(silent=True) or {}
        with runs.lock, server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            if not run or run.deleted_at or run.status not in ("paused", "error"):
                raise ValueError("Düzenlemek için çalışmayı duraklatın.")
            tasks = session.query(SearchTask).filter_by(run_id=run_id).all()
            pending = {t.id: t for t in tasks if t.status not in runs.TERMINAL}
            submitted = body.get("tasks", [])
            if not submitted:
                raise ValueError("En az bir kalan görev bulunmalı.")
            submitted_ids = [t.get("id") for t in submitted]
            if len(set(submitted_ids)) != len(submitted_ids) or any(i not in pending for i in submitted_ids):
                raise ValueError("Geçersiz görev listesi.")
            for task in tasks:
                if task.id in pending and task.id not in submitted_ids:
                    # Keep historical links; cancellation removes it from the pending queue.
                    runs.transition(task, "stopped" if runs.has_started(task) else "cancelled", "Kullanıcı tarafından kuyruktan kaldırıldı.")
                    audit.record(session, run_id, task.id, "queue_task_removed", {"reason":"paused_queue_edit"})
            offset = len(tasks)
            for i, raw in enumerate(submitted):
                task = pending[raw["id"]]
                item = task_data({"tasks": [raw]})[0]
                if "package" not in raw:
                    item["package"] = task.package or ""  # Düzenleme paketi bilmiyorsa paket korunur.
                before = {k:getattr(task,k) for k in ("keyword","location","limit","position")}
                changed = task.keyword != item["keyword"] or task.location != item["location"]
                if changed and task.folder:
                    raise ValueError("Başlamış görevin unvanı/konumu değiştirilemez; yeni tarama oluşturun.")
                for key, value in item.items():
                    setattr(task, key, value)
                task.position = offset + i
                runs.sync_export(task)
                audit.record(session, run_id, task.id, "queue_task_changed", {"before":before, "after":dict(item, position=task.position)})
            session.commit()
            return jsonify(ok=True)

    @app.post("/api/queue/cancel-all")
    def cancel_all():
        """Toplu iptal: her şey devam ettirilebilir kalır ama hiçbiri kendiliğinden başlamaz."""
        from .models import Watch
        reason = "Toplu iptal: elle başlatılana kadar bekliyor."
        paused = schedules = 0
        with runs.lock, server.SessionLocal() as session:
            for run in session.query(SearchRun).filter(SearchRun.deleted_at.is_(None)):
                options = json.loads(run.options or "{}")
                previous = run.status
                active = server.state.running and getattr(server.state, "run_id", None) == run.id
                if run.status in ("finished", "stopped", "cancelled"):
                    if not options.get("schedule_enabled"):
                        continue
                    schedules += 1
                elif run.status == "queued" and not options.get("service_managed"):
                    continue  # Kullanıcının taslak kuyruğu zaten kendiliğinden başlamaz.
                elif active:
                    if run.status == "running":
                        runs.transition(run, "pausing", reason)
                        server.state.stop_flag = True
                    paused += 1
                elif run.status in ("paused", "error", "queued"):
                    runs.transition(run, "paused", reason)
                    paused += 1
                else:
                    continue
                options.pop("auto_resume_at", None)
                options.pop("service_managed", None)
                options["schedule_enabled"] = False
                if run.status not in runs.TERMINAL:
                    options["user_paused"] = True
                run.options = json.dumps(options)
                audit.record(session, run.id, None, "user_action", {"action":"cancel_all", "previous_status":previous})
            watches = session.query(Watch).filter(Watch.enabled.is_(True)).all()
            for watch in watches:
                watch.enabled = False
            session.commit()
        server.state.emit("task_control", {"action":"cancel_all"})
        return jsonify(ok=True, paused=paused, schedules_disabled=schedules, watches_disabled=len(watches))

    @app.post("/api/runs/<run_id>/<action>")
    def run_action(run_id, action):
        with runs.lock, server.SessionLocal() as session:
            run = session.get(SearchRun, run_id)
            if not run:
                return jsonify(error="Çalışma bulunamadı."), 404
            active = getattr(server.state, "run_id", None) == run_id and server.state.running
            if action != "purge":
                audit.record(session, run_id, None, "user_action", {"action":action, "previous_status":run.status})
            if action == "resume":
                options = json.loads(run.options or "{}")
                source_paused = options.get("kind", "scrape") == "scrape" and Coordinator().state()["paused"]
                if (server.state.running or source_paused) and not active and run.status in ("queued", "paused", "error"):
                    # Sistem meşgulken başlatma sıraya alınır; servis, kaynak ve sıra uygun olunca kendisi başlatır.
                    options.pop("user_paused", None)
                    if run.status == "queued":
                        options["service_managed"] = True
                    else:
                        options.setdefault("auto_resume_at", 0)
                    run.options = json.dumps(options)
                    audit.record(session, run_id, None, "queue_scheduled", {"reason":"source_paused" if source_paused else "busy"})
                    session.commit()
                    return jsonify(ok=True, scheduled=True)
                if server.state.running:
                    raise ValueError("Önce devam eden işlemi duraklatın.")
                session.commit()
                runs.start(server, run_id)
            elif action in ("pause", "stop", "cancel"):
                options = json.loads(run.options or "{}")
                options.pop("auto_resume_at", None)
                options["schedule_enabled"] = False
                options["user_paused"] = True
                run.options = json.dumps(options)
                tasks = session.query(SearchTask).filter_by(run_id=run_id).all()
                if action == "cancel":
                    if active or runs.has_started(run) or any(runs.has_started(t) for t in tasks) or run.status != "queued":
                        raise ValueError("Başlamış sorgular iptal edilemez. Duraklat veya durdur seçeneğini kullanın.")
                    runs.transition(run, "cancelled", "Kuyruk başlamadan kullanıcı tarafından iptal edildi.")
                    for task in tasks:
                        if task.status not in runs.TERMINAL:
                            runs.transition(task, "cancelled", run.status_reason)
                elif active:
                    if run.status != "running":
                        raise ValueError("Durum değişikliği tamamlanıyor; lütfen bekleyin.")
                    runs.transition(run, "pausing" if action == "pause" else "stopping",
                                    "Kullanıcı taramayı duraklattı." if action == "pause" else "Kullanıcı kuyruğu durdurdu.")
                    server.state.stop_flag = True
                elif action == "stop" and run.status in ("paused", "error"):
                    runs.transition(run, "stopped", "Kullanıcı kuyruğu durdurdu. Toplanan ilanlar korundu.")
                    for task in tasks:
                        if task.status not in runs.TERMINAL:
                            runs.transition(task, "stopped", run.status_reason)
                elif action == "pause" and run.status in ("paused", "error"):
                    runs.transition(run, "paused", "Kullanıcı otomatik devamı duraklattı.")
                else:
                    raise ValueError("Çalışma bu durumda duraklatılamaz veya durdurulamaz.")
                session.commit()
            elif action in ("delete", "restore", "purge"):
                if active:
                    raise ValueError("Aktif çalışmayı silmeden önce duraklatın.")
                if action == "purge" and not run.deleted_at:
                    raise ValueError("Önce çöp kutusuna taşıyın.")
                run.deleted_at = None if action == "restore" else datetime.utcnow()
                tasks = session.query(SearchTask).filter_by(run_id=run_id).all()
                for task in tasks:
                    if task.folder:
                        folder = safe_folder(task.folder)
                        if action == "purge":
                            if folder.exists():
                                shutil.rmtree(folder)
                        elif (folder / "search.json").exists():
                            meta = json.loads((folder / "search.json").read_text(encoding="utf-8"))
                            meta["deletedAt"] = run.deleted_at.isoformat() if run.deleted_at else None
                            _write_json(folder / "search.json", meta)
                    if action == "purge":
                        session.query(TaskJob).filter_by(task_id=task.id).delete()
                        session.delete(task)
                if action == "purge":
                    session.query(SearchEvent).filter_by(run_id=run_id).delete()
                    session.delete(run)
                session.commit()
            else:
                raise ValueError("Geçersiz işlem.")
        return jsonify(ok=True)

    @app.post("/api/runs/<run_id>/tasks/<task_id>/<action>")
    def task_action(run_id, task_id, action):
        with runs.lock, server.SessionLocal() as session:
            run, task = session.get(SearchRun, run_id), session.get(SearchTask, task_id)
            if not run or run.deleted_at or not task or task.run_id != run_id:
                raise ValueError("Sorgu bulunamadı.")
            if json.loads(run.options).get("kind", "scrape") != "scrape":
                raise ValueError("Yerel analiz işlemlerinde kuyruk kontrollerini kullanın.")
            if task.status in runs.TERMINAL or run.status in runs.TERMINAL:
                raise ValueError("Bu sorgunun işlemi sona ermiş. Yeni tarama oluşturabilirsiniz.")
            active = server.state.running and getattr(server.state, "run_id", None) == run_id
            if action == "cancel":
                if runs.has_started(task) or task.status != "queued":
                    raise ValueError("Yalnızca başlamamış sorgular iptal edilebilir.")
                runs.transition(task, "cancelled", "Sorgu başlamadan kullanıcı tarafından iptal edildi.")
            elif action == "pause":
                options = json.loads(run.options or "{}")
                options.pop("auto_resume_at", None)
                options["schedule_enabled"] = False
                options["user_paused"] = True
                run.options = json.dumps(options)
                if not active or task.status != "running" or run.status != "running":
                    raise ValueError("Yalnızca çalışan sorgu duraklatılabilir.")
                runs.transition(run, "pausing", "Kullanıcı çalışan sorguyu duraklattı; kuyruk bekliyor.")
                runs.transition(task, "pausing", run.status_reason)
                server.state.stop_flag = True
            elif action == "stop":
                if not runs.has_started(task) or task.status not in ("running", "paused", "error") or run.status not in ("running", "paused", "error"):
                    raise ValueError("Başlamamış sorguda iptal seçeneğini kullanın.")
                runs.transition(task, "stopping" if active and task.status == "running" else "stopped",
                                "Kullanıcı sorguyu durdurdu. Toplanan ilanlar korundu.")
                if task.status == "stopping":
                    server.state.task_stop_id = task_id
            elif action == "resume":
                if server.state.running or task.status not in ("paused", "error"):
                    raise ValueError("Önce devam eden işlemi duraklatın.")
                audit.record(session, run_id, task_id, "user_action", {"action":action, "scope":"task"})
                session.commit()
                runs.start(server, run_id)
                return jsonify(ok=True)
            else:
                raise ValueError("Geçersiz sorgu işlemi.")
            audit.record(session, run_id, task_id, "user_action", {"action":action, "scope":"task", "status":task.status, "reason":task.status_reason})
            session.flush()
            remaining = session.query(SearchTask).filter(SearchTask.run_id == run_id, ~SearchTask.status.in_(runs.TERMINAL)).count()
            if not active and not remaining:
                runs.transition(run, "stopped" if runs.has_started(run) else "cancelled", "Kalan sorgu yok; kuyruk kapatıldı.")
            session.commit()
        server.state.emit("task_control", {"run_id":run_id, "task_id":task_id, "action":action})
        return jsonify(ok=True)

    def status():
        data = {"running": server.state.running, "kind": server.state.kind, **server.state.last}
        data["source_state"] = Coordinator().state()
        ident = getattr(server.state, "run_id", None)
        if ident:
            with server.SessionLocal() as session:
                run = session.get(SearchRun, ident)
                if run:
                    data["run"] = runs.snapshot(session, run)
        if not ident:
            with server.SessionLocal() as session:
                pending = session.query(SearchRun).filter(SearchRun.status.in_(("paused", "error")), SearchRun.deleted_at.is_(None)).order_by(SearchRun.updated_at.desc()).all()
                run = next((r for r in pending if not json.loads(r.options or "{}").get("user_paused") and (
                    "auto_resume_at" in json.loads(r.options or "{}") or any(json.loads(t.stats or "{}").get("termination_reason") == "source_paused" for t in session.query(SearchTask).filter_by(run_id=r.id, status="paused")))), None)
                if run:
                    data["run"] = runs.snapshot(session, run)
        data["waiting"] = waiting_runs(data.get("run", {}).get("id"))
        return jsonify(data)

    def waiting_runs(exclude):
        """Kendiliğinden başlamayı bekleyen kuyrukların kısa özeti (eski sıradan yeniye)."""
        result = []
        with server.SessionLocal() as session:
            rows = session.query(SearchRun).filter(SearchRun.deleted_at.is_(None), SearchRun.status.in_(("queued", "paused", "error"))).order_by(SearchRun.created_at).all()
            for run in rows:
                options = json.loads(run.options or "{}")
                if run.id == exclude or options.get("user_paused") or options.get("kind", "scrape") != "scrape":
                    continue
                if not (run.status == "queued" and options.get("service_managed")) and "auto_resume_at" not in options:
                    continue
                tasks = session.query(SearchTask).filter(SearchTask.run_id == run.id, ~SearchTask.status.in_(runs.TERMINAL)).order_by(SearchTask.position).all()
                if not tasks:
                    continue
                result.append({"id":run.id, "status":run.status, "created_at":run.created_at.isoformat(),
                               "watch":bool(options.get("watch_id")),
                               "tasks":[{"id":t.id, "keyword":t.keyword, "location":t.location, "limit":t.limit, "package":t.package or ""} for t in tasks]})
        return result
    app.view_functions["api_scrape_status"] = status

    def search_delete(folder_name):
        safe_folder(folder_name)
        with server.SessionLocal() as session:
            task = session.query(SearchTask).filter_by(folder=folder_name).first()
            if not task:
                raise ValueError("Arama kaydı bulunamadı.")
            ident = task.run_id
        return run_action(ident, "delete")
    app.view_functions["api_search_delete"] = search_delete

    def start_maintenance(kind):
        body = request.get_json(silent=True) or {}
        options = dict(kind=kind, force=bool(body.get("force")), limit=filters.number(MultiDict(body), "limit", True),
                       backend=body.get("backend", "local"), model=body.get("model"), audit_version=audit.VERSION)
        if options["limit"] == 0:
            raise ValueError("İşlem limiti pozitif bir tam sayı olmalı.")
        if options["backend"] not in ("local", "claude", "groq"):
            raise ValueError("Geçersiz analiz yöntemi.")
        with runs.lock, server.SessionLocal() as session:
            if server.state.running:
                raise ValueError("Başka işlem sürüyor. Önce bitmesini bekleyin veya duraklatın.")
            run_id, task_id = runs.identifier(), runs.identifier()
            session.add(SearchRun(id=run_id, options=json.dumps(options)))
            session.add(SearchTask(id=task_id, run_id=run_id, limit=options["limit"], keyword={"embed": "Eşleştirme verilerini hazırla", "fit": "Profil uygunluğunu puanla"}.get(kind, "Kayıtlı ilanları analiz et")))
            audit.record(session, run_id, None, "run_created", {"actor":"web", "options":options})
            audit.record(session, run_id, task_id, "task_queued", {"kind":kind})
            session.commit()
            runs.start(server, run_id)
            return jsonify(ok=True, run_id=run_id, task_id=task_id)
    app.view_functions["api_embed"] = lambda: start_maintenance("embed")
    app.view_functions["api_classify"] = lambda: start_maintenance("classify")
    app.add_url_rule("/api/fit", "api_fit", lambda: start_maintenance("fit"), methods=["POST"])
