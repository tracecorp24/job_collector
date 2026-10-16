"""Orchestrates a scrape run: scrape -> parse -> classify -> upsert.

Emits SSE-style events through an ``emit(event_type, data)`` callback (same
contract as the old control panel) so the UI can show live progress and append
new jobs as they land.
"""

import json
import time
import traceback
from datetime import datetime

from . import config, parse, salary, skills
from .classify import classify_job
from .db import SessionLocal, init_db, upsert_job, parse_date
from .models import Job, SearchRun, SearchTask, TaskJob, SearchEvent
from . import audit
from .transport import SourcePaused, fingerprint
from .runs import transition


def process_raw(session, raw: dict, classify_backend: str = "rules",
                 use_embeddings: bool = False, emit=None) -> tuple:
    """Parse + classify one raw scraped job and upsert it. Returns (job, created)."""
    def stage(name, phase, **data):
        if emit:
            emit("processing_stage", dict(stage=name, phase=phase, external_id=raw["external_id"], **data))
    started = time.monotonic()
    stage("parse", "started", card_lines=len(raw.get("card_lines", [])), description_chars=len(raw.get("description", "")))
    parser = parse.parse_guest_card if parse.is_guest_card(raw) else parse.parse_card
    parsed = parser(raw.get("card_lines", []), raw.get("description", ""))
    stage("parse", "finished", quality_ok=parsed.get("quality_ok"), duration_ms=round((time.monotonic()-started)*1000))
    description = raw.get("description", "")
    started = time.monotonic()
    stage("classify", "started", requested_backend=classify_backend)
    cls = classify_job(
        parsed["title"],
        description,
        workplace_type=parsed.get("workplace_type", ""),
        backend=classify_backend,
    )
    expected = "llm" if classify_backend == "claude" else classify_backend
    stage("classify", "finished", requested_backend=classify_backend, actual_backend=cls.get("classified_by"),
          classification_fallback=cls.get("classified_by") != expected, duration_ms=round((time.monotonic()-started)*1000))
    embedding = None
    if use_embeddings:
        started = time.monotonic()
        stage("embedding", "started", model=config.OLLAMA_EMBED_MODEL)
        from . import embed
        embedding = embed.embed_text(f"{parsed['title']}\n\n{description}")
        stage("embedding", "finished", available=embedding is not None, duration_ms=round((time.monotonic()-started)*1000))
    salary_parsed = salary.parse_salary(cls.get("salary", ""))
    record = {
        "posted_at": parse_date(raw.get("posted")),
        "experience_years": skills.extract_experience_years(parsed["title"] + " " + description),
        "source": config.SOURCE_LINKEDIN,
        "external_id": raw["external_id"],
        "url": raw.get("url", ""),
        "title": parsed["title"],
        "company": parsed["company"],
        "location": parsed["location"],
        "workplace_type": cls.get("workplace_type") or parsed.get("workplace_type", ""),
        "category": cls["category"],
        "seniority": cls["seniority"],
        "tags": cls["tags"],
        "summary": cls.get("summary", ""),
        "about_company": cls.get("about_company", ""),
        "offerings": cls.get("offerings", []),
        "salary": cls.get("salary", ""),
        "formatted_description": cls.get("formatted_description", ""),
        "salary_min": salary_parsed["min"],
        "salary_max": salary_parsed["max"],
        "salary_currency": salary_parsed["currency"],
        "salary_period": salary_parsed["period"],
        "flag": cls.get("flag", ""),
        "flag_reason": cls.get("flag_reason", ""),
        "classified_by": cls["classified_by"],
        "description": raw.get("description", ""),
        "search_term": raw.get("search_term", ""),
        "search_location": raw.get("search_location", ""),
        "quality_ok": parsed["quality_ok"],
        "raw": raw,
        "scraped_at": datetime.utcnow(),
    }
    if embedding is not None:
        record["embedding"] = embedding
    job, created = upsert_job(session, record)
    # A vector computed from previous content is no longer valid.
    if embedding is None:
        job.embedding = None
    return job, created


def run_scrape(keywords, locations, limit=None, classify_backend="rules",
               use_embeddings=False, require_login=False, emit=None, should_stop=None,
               on_scraper_ready=None, output_dir=None, checkpoint=None, resume_folder=None, search_id=None, run_id=None, attempt_id=None,
               mode="incremental", refresh_details=False, search_options=None):
    """Full run driven by the web button.

    ``keywords``: [{"keyword": str, "limit": int|None}, ...] or [str, ...]
    ``locations``: [str, ...]
    """
    if require_login:
        raise ValueError("Light supports accountless search only.")
    init_db()

    exporter = None
    import uuid
    own_run = run_id is None
    run_id = run_id or uuid.uuid4().hex
    attempt_id = attempt_id or uuid.uuid4().hex
    active_search_id = search_id
    if not require_login:
        from .search_export import SearchExport
        exporter = SearchExport(root=output_dir)

    def _emit(kind, data=None):
        nonlocal active_search_id
        payload = data or {}
        payload = dict(payload, attempt_id=attempt_id)
        if exporter and kind == "task_start":
            active_search_id = search_id or uuid.uuid4().hex
            folder = exporter.resume(resume_folder) if resume_folder else exporter.begin(payload["keyword"], payload.get("location", ""), limit=payload.get("limit"))
            payload["folder"] = exporter.current.name
            exporter.metadata.update(searchId=active_search_id, runId=run_id)
            exporter.metadata["limit"] = payload.get("limit")
            from .search_export import _write_json
            _write_json(exporter.current / "search.json", exporter.metadata)
            if own_run:
                if not session.get(SearchRun, run_id):
                    session.add(SearchRun(id=run_id, status="running", options=json.dumps({"kind":"scrape", "audit_version":audit.VERSION, "classify_backend":classify_backend, "use_embeddings":use_embeddings, "mode":mode, "refresh_details":refresh_details})))
                    audit.record(session, run_id, None, "run_created", {"actor":"cli", "attempt_id":attempt_id})
                session.add(SearchTask(id=active_search_id, run_id=run_id, keyword=payload["keyword"], location=payload.get("location", ""),
                                       limit=payload.get("limit"), folder=exporter.current.name, status="running"))
                session.flush()
                transition(session.get(SearchRun, run_id), "running")
                transition(session.get(SearchTask, active_search_id), "running")
                session.commit()
            if emit:
                emit("log", {"msg": f"Search output: {folder}", "level": "info"})
        elif exporter and kind == "log" and exporter.current:
            exporter.log(payload.get("msg", ""), payload.get("level", "info"))
        elif exporter and kind == "task_done":
            status = "stopped" if (should_stop and should_stop()) else ("error" if payload.get("reason") == "page_fetch_failed" else "finished")
            exporter.event(kind, dict(payload, search_id=active_search_id, run_id=run_id))
            exporter.finish(
                status=status,
                reason=payload.get("reason"),
                stats=payload.get("stats"),
                error=payload.get("error"),
            )
            if own_run:
                transition(session.get(SearchTask, active_search_id), "paused" if status == "stopped" else status,
                           "Kullanıcı taramayı duraklattı." if status == "stopped" else payload.get("reason", ""))
                session.get(SearchTask, active_search_id).stats = json.dumps(payload.get("stats", {}))
                session.commit()
        if own_run and active_search_id:
            if kind == "checkpoint":
                session.get(SearchTask, active_search_id).checkpoint = json.dumps(payload)
            else:
                audit.record(session, run_id, active_search_id, kind, payload,
                             payload.get("level", "error" if kind == "error" else "info"))
            if kind == "error":
                session.get(SearchTask, active_search_id).status = "error"
                session.get(SearchTask, active_search_id).error = payload.get("msg", "")
            session.commit()
        if exporter and kind != "checkpoint":
            exporter.event(kind, dict(payload, search_id=active_search_id, run_id=run_id))
        if emit:
            emit(kind, payload)

    # Normalise keyword shapes.
    search_queue = []
    for kw in keywords:
        if isinstance(kw, dict):
            search_queue.append({
                "keyword": kw["keyword"],
                "location": kw.get("location"),
                "limit": kw.get("limit", limit),
            })
        else:
            search_queue.append({"keyword": str(kw), "limit": limit})

    locations = locations or [""]
    has_item_locations = any(item.get("location") for item in search_queue)
    total_planned = len(search_queue) if has_item_locations else (len(locations) * len(search_queue))
    _emit("queue_ready", {"total": total_planned})

    stats = {"new": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    session = SessionLocal()

    def on_job(raw):
        raw.update(search_id=active_search_id, run_id=run_id)
        last_stage = "export"
        def processing_event(kind, data):
            nonlocal last_stage
            last_stage = data.get("stage", last_stage)
            _emit(kind, data)
        processing_event("processing_stage", {"stage":"export", "phase":"started", "external_id":raw["external_id"]})
        # Persist each result immediately, independent of DB/model processing.
        if exporter:
            exported = exporter.save(raw)
            processing_event("processing_stage", {"stage":"export", "phase":"finished", "external_id":raw["external_id"], "saved":exported})
        try:
            existing = session.query(Job).filter_by(source=config.SOURCE_LINKEDIN, external_id=raw["external_id"]).first()
            unchanged = bool(mode == "incremental" and existing and existing.quality_ok
                and fingerprint(json.loads(existing.raw or "{}")) == fingerprint(raw)
                and existing.description == raw.get("description", ""))
            if unchanged:
                job, created = existing, False
                job.scraped_at = datetime.utcnow()
                job.raw = json.dumps(raw, ensure_ascii=False)
            else:
                job, created = process_raw(session, raw, classify_backend=classify_backend,
                    use_embeddings=use_embeddings, emit=processing_event)
            outcome = "new" if created else "unchanged" if unchanged else "updated"
            last_stage = "database"
            _emit("processing_stage", {"stage":"database", "phase":"started", "external_id":raw["external_id"]})
            session.flush()
            if active_search_id and not session.get(TaskJob, (active_search_id, job.id)):
                session.add(TaskJob(task_id=active_search_id, job_id=job.id, is_new=created, outcome=outcome))
            session.commit()
            if job.deleted_at and exporter and exporter.current:
                from .search_export import _write_json
                path = exporter.current / "ilan_havuzu" / f"ap-{job.source}-{job.external_id}.json"
                if path.exists():
                    snapshot = json.loads(path.read_text(encoding="utf-8"))
                    snapshot["_deletedAt"] = job.deleted_at.isoformat()
                    _write_json(path, snapshot)
        except Exception as e:  # never let one bad card kill the run
            session.rollback()
            _emit("job_skipped", {"reason":"processing_error", "stage":last_stage, "external_id":raw["external_id"],
                                  "error_type":type(e).__name__, "msg":str(e), "traceback":traceback.format_exc(), "level":"error"})
            _emit("log", {"msg": f"Skipped a job: {str(e)[:120]}", "level": "warning"})
            stats["skipped"] += 1
            return "failed"
        if not job.quality_ok:
            _emit("job_skipped", {"reason":"quality_rejected", "external_id":raw["external_id"], "job_id":job.id, "level":"warning"})
            stats["skipped"] += 1
            return "rejected"
        stats[outcome] += 1
        _emit("processing_result", {"status":"saved", "outcome":outcome, "external_id":raw["external_id"], "job_id":job.id,
                                    "is_new":created, "quality_ok":job.quality_ok, "deleted":bool(job.deleted_at),
                                    "requested_backend":classify_backend, "actual_backend":job.classified_by,
                                    "classification_fallback":job.classified_by != ("llm" if classify_backend == "claude" else classify_backend),
                                    "embedding_available":bool(job.embedding)})
        _emit("job", dict(job.to_dict(), is_new=created, outcome=outcome))
        return outcome

    try:
        from .scraper.accountless import AccountlessScraper
        scraper = AccountlessScraper(emit=_emit, should_stop=should_stop, mode=mode, refresh_details=refresh_details,
                                     search_options=search_options)
        scraper.resume_checkpoint = checkpoint or {}
        if on_scraper_ready:
            on_scraper_ready(scraper)
        scraper.scrape(search_queue, locations, on_job)
        if exporter:
            exporter.finish("stopped" if should_stop and should_stop() else "finished")
            stats["output_folders"] = exporter.folders
        _emit("finished", stats)
    except SourcePaused as e:
        stats.update(paused=True, pause_reason=str(e), source_state=e.state)
        _emit("source_paused", dict(e.state, level="warning"))
        if exporter:
            exporter.finish("paused", reason="source_paused", error=str(e))
        if own_run and active_search_id:
            task = session.get(SearchTask, active_search_id)
            transition(task, "paused", str(e))
            task.error = str(e)
            session.commit()
    except KeyboardInterrupt:
        if exporter:
            exporter.finish("stopped", reason="stopped_by_user")
        raise
    except Exception as e:
        _emit("error", {"msg": str(e), "error_type":type(e).__name__, "traceback":traceback.format_exc()})
        if exporter:
            exporter.finish("error", error=str(e), reason="error")
    finally:
        if exporter:
            stats["output_folders"] = exporter.folders
        if own_run:
            run = session.get(SearchRun, run_id)
            if run:
                run.status = "paused" if stats.get("paused") else "error" if any(t.status in ("running", "error") for t in session.query(SearchTask).filter_by(run_id=run_id)) else ("paused" if should_stop and should_stop() else "finished")
                transition(run, run.status, stats.get("pause_reason", ""))
                run.stats = json.dumps(stats)
                session.commit()
        session.close()

    return stats


def run_embed_backfill(limit=None, emit=None, should_stop=None, force=False, skip_ids=None) -> dict:
    """Compute embeddings for jobs already in the DB that don't have one yet
    — no re-scraping. Requires Ollama running locally (see embed.py).

    ``force``: recompute embeddings for every job, not just the ones missing one."""
    from . import embed

    should_stop = should_stop or (lambda: False)

    def _emit(kind, data=None):
        if emit:
            emit(kind, data or {})

    init_db()
    session = SessionLocal()
    stats = {"embedded": 0, "skipped": 0, "total": 0}
    try:
        q = session.query(Job).filter(Job.quality_ok.is_(True), Job.deleted_at.is_(None))
        if not force:
            q = q.filter(Job.embedding.is_(None))
        if skip_ids:
            q = q.filter(~Job.id.in_(skip_ids))
        q = q.order_by(Job.id)
        if limit:
            q = q.limit(limit)
        jobs = q.all()
        stats["total"] = len(jobs)
        _emit("queue_ready", {"total": len(jobs)})
        if not jobs:
            _emit("log", {"msg": "No jobs are missing embeddings.", "level": "warning"})

        consecutive_failures = 0
        for i, job in enumerate(jobs, start=1):
            if should_stop():
                _emit("log", {"msg": "Stopped by user.", "level": "warning"})
                break

            started = time.monotonic()
            _emit("processing_stage", {"stage":"embedding", "phase":"started", "job_id":job.id, "model":config.OLLAMA_EMBED_MODEL})
            vector = embed.embed_text(f"{job.title}\n\n{job.description}")
            if vector is None:
                _emit("processing_result", {"stage":"embedding", "status":"failed", "job_id":job.id,
                                            "reason":"model_unavailable_or_invalid_response", "duration_ms":round((time.monotonic()-started)*1000), "level":"error"})
                stats["skipped"] += 1
                consecutive_failures += 1
                # A single bad job wouldn't repeat 3x in a row — this many
                # failures back to back means Ollama itself is unreachable,
                # so stop hammering it instead of failing every remaining job.
                if consecutive_failures >= 3:
                    _emit("log", {
                        "msg": "Local embedding model unreachable (Ollama not running?) — stopping.",
                        "level": "error",
                    })
                    break
                continue

            consecutive_failures = 0
            job.embedding = json.dumps(vector)
            session.commit()
            stats["embedded"] += 1
            _emit("processing_result", {"stage":"embedding", "status":"saved", "job_id":job.id, "duration_ms":round((time.monotonic()-started)*1000)})
            _emit("task_done", {"done": i, "total": len(jobs), "pct": int(i / max(len(jobs), 1) * 100)})
            if i == 1 or i % 5 == 0:
                _emit("log", {"msg": f"...embedded {i}/{len(jobs)} job(s)."})

        stats["termination_reason"] = "stopped_by_user" if should_stop() else "model_unavailable" if consecutive_failures >= 3 else "completed"
        _emit("finished", stats)
    except Exception as e:
        _emit("error", {"msg": str(e)})
    finally:
        session.close()

    return stats


def run_classify_backfill(backend="local", limit=None, model=None, emit=None, should_stop=None, force=False, skip_ids=None) -> dict:
    """Re-classify jobs already in the DB that haven't been classified by
    ``backend`` yet — no re-scraping. ``backend`` is "local" (Ollama) or
    "claude"; both fall back to leaving the job's existing classification
    untouched on any error, same as during a normal scrape.

    ``force``: re-classify every job, not just the ones not yet classified by ``backend``."""
    should_stop = should_stop or (lambda: False)

    def _emit(kind, data=None):
        if emit:
            emit(kind, data or {})

    init_db()
    session = SessionLocal()
    stats = {"classified": 0, "skipped": 0, "total": 0}
    try:
        q = session.query(Job).filter(Job.quality_ok.is_(True), Job.deleted_at.is_(None))
        expected = "llm" if backend == "claude" else backend
        if not force:
            q = q.filter(Job.classified_by != expected)
        if skip_ids:
            q = q.filter(~Job.id.in_(skip_ids))
        q = q.order_by(Job.id)
        if limit:
            q = q.limit(limit)
        jobs = q.all()
        stats["total"] = len(jobs)
        _emit("queue_ready", {"total": len(jobs)})
        if not jobs:
            _emit("log", {"msg": f"No jobs are waiting on '{backend}' classification.", "level": "warning"})

        consecutive_failures = 0
        for i, job in enumerate(jobs, start=1):
            if should_stop():
                _emit("log", {"msg": "Stopped by user.", "level": "warning"})
                break

            started = time.monotonic()
            _emit("processing_stage", {"stage":"classify", "phase":"started", "job_id":job.id, "backend":backend, "model":config.GROQ_CLASSIFY_MODEL if backend == "groq" else model or config.OLLAMA_MODEL})
            cls = classify_job(
                job.title, job.description,
                workplace_type=job.workplace_type, backend=backend, model=model, patient=True,
            )
            if cls.get("classified_by") != expected:
                _emit("processing_result", {"stage":"classify", "status":"failed", "job_id":job.id,
                                            "classification_fallback":True, "actual_backend":cls.get("classified_by"),
                                            "duration_ms":round((time.monotonic()-started)*1000), "level":"error"})
                stats["skipped"] += 1
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    _emit("log", {
                        "msg": f"'{backend}' classifier unreachable — stopping.",
                        "level": "error",
                    })
                    break
                continue

            consecutive_failures = 0
            job.category = cls["category"]
            job.seniority = cls["seniority"]
            job.workplace_type = cls.get("workplace_type") or job.workplace_type
            job.tags = json.dumps(cls.get("tags", []), ensure_ascii=False)
            job.summary = cls.get("summary", "")
            job.about_company = cls.get("about_company", "")
            job.offerings = json.dumps(cls.get("offerings", []), ensure_ascii=False)
            job.salary = cls.get("salary", "")
            job.formatted_description = cls.get("formatted_description", "")
            salary_parsed = salary.parse_salary(job.salary)
            job.salary_min = salary_parsed["min"]
            job.salary_max = salary_parsed["max"]
            job.salary_currency = salary_parsed["currency"]
            job.salary_period = salary_parsed["period"]
            job.flag = cls.get("flag", "")
            job.flag_reason = cls.get("flag_reason", "")
            job.classified_by = cls["classified_by"]
            session.commit()
            stats["classified"] += 1
            _emit("processing_result", {"stage":"classify", "status":"saved", "job_id":job.id, "actual_backend":cls.get("classified_by"), "duration_ms":round((time.monotonic()-started)*1000)})
            _emit("task_done", {"done": i, "total": len(jobs), "pct": int(i / max(len(jobs), 1) * 100)})
            if i == 1 or i % 5 == 0:
                _emit("log", {"msg": f"...classified {i}/{len(jobs)} job(s)."})

        stats["termination_reason"] = "stopped_by_user" if should_stop() else "model_unavailable" if consecutive_failures >= 3 else "completed"
        _emit("finished", stats)
    except Exception as e:
        _emit("error", {"msg": str(e)})
    finally:
        session.close()

    return stats
