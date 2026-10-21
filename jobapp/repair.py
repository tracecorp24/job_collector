"""Second queue layer: repair source fields before routine searches.

Only the existing supervisor dispatches work. Each worker does one stage of one
posting, so newly queued searches take the next turn. No running claims are
persisted: an interrupted stage can safely be replayed after restart.
"""
import json
import hashlib
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, or_
from sqlalchemy.dialects.sqlite import insert

from . import config, runs, skills, audit
from .models import Job, RepairTask, TaskJob, SearchTask, Setting
from .transport import Coordinator, SourcePaused, fingerprint

SOURCE_FIELDS = ("description", "title", "company", "location")
DERIVED_FIELDS = ("tags", "experience_years", "workplace_type", "category", "seniority")
SOURCE_REQUEST_COUNTER = "repair_source_requests_since_routine"


def revision(job):
    return hashlib.sha256(json.dumps([job.title, job.company, job.location, job.description, job.raw],
        ensure_ascii=False).encode("utf-8")).hexdigest()


def card_fingerprint(job):
    try:
        raw = json.loads(job.raw or "{}")
    except (ValueError, TypeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw["card_lines"] = [job.title or "", job.company or "", job.location or ""]
    return fingerprint(raw)


def completion_paused(session):
    setting = session.get(Setting, "completion_paused")
    return bool(setting and setting.value == "1")


def enqueue(session, raw, reason="Açıklama eksik.", replace=False, force_refresh=False):
    external_id = str(raw.get("external_id") or "")
    if not external_id.isdigit():
        return
    # Do not reset attempts/deadlines when the same card is rediscovered.
    queued_raw = dict(raw)
    queued_raw["_repair_force_requested"] = bool(force_refresh)
    values = dict(source=config.SOURCE_LINKEDIN,
        external_id=external_id, raw=json.dumps(queued_raw, ensure_ascii=False),
        stage="enrich" if raw.get("_repair_fields") and not set(raw["_repair_fields"]) & set(SOURCE_FIELDS) else "detail",
        status="pending", attempts=0, next_attempt_at=0,
        last_error=reason, updated_at=datetime.utcnow())
    statement = insert(RepairTask).values(**values)
    if replace:
        statement = statement.on_conflict_do_update(index_elements=["source", "external_id"],
            set_={k:v for k,v in values.items() if k not in ("source", "external_id")})
    else:
        statement = statement.on_conflict_do_nothing()
    session.execute(statement)


def discover(session):
    """Find legacy missing descriptions in bounded, indexed batches."""
    rows = session.query(Job, RepairTask).outerjoin(RepairTask,
        (RepairTask.source == Job.source) & (RepairTask.external_id == Job.external_id)).filter(
        Job.source == config.SOURCE_LINKEDIN, Job.deleted_at.is_(None),
        or_(*[func.trim(func.coalesce(getattr(Job, field), "")) == "" for field in SOURCE_FIELDS],
            func.json_extract(Job.raw, '$.detail_pending') == 1),
        or_(RepairTask.external_id.is_(None), RepairTask.status.in_(("done", "unavailable")))
    ).order_by(Job.id).limit(100).all()
    for job, existing_task in rows:
        try:
            raw = json.loads(job.raw or "{}")
        except (ValueError, TypeError):
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        raw.update(external_id=job.external_id, url=f"https://www.linkedin.com/jobs/view/{job.external_id}",
                   card_layout="guest", card_lines=[job.title, job.company, job.location],
                   search_term=job.search_term, search_location=job.search_location, _repair_existing_job_id=job.id)
        raw["_repair_fields"] = [field for field in SOURCE_FIELDS if not (getattr(job, field) or "").strip()]
        missing_fields = list(raw["_repair_fields"])
        if raw.get("detail_pending") and "description" not in raw["_repair_fields"]:
            raw["_repair_fields"].append("description")
        # A pending revision requires current source content, but it does not by
        # itself authorize bypassing a valid same-card cache entry.
        raw.update(_queue_layer="repair", _repair_force=False,
                   _repair_force_requested=bool(raw.get("_repair_force_requested")), _repair_values={})
        raw["_repair_revision"] = revision(job)
        current_card_fingerprint = fingerprint(raw)
        raw["_repair_card_fingerprint"] = current_card_fingerprint

        if existing_task is None:
            enqueue(session, raw)
            continue

        try:
            prior_raw = json.loads(existing_task.raw or "{}")
        except (ValueError, TypeError):
            prior_raw = {}
        prior_card_fingerprint = prior_raw.get("_repair_card_fingerprint")
        if not prior_card_fingerprint and prior_raw.get("card_lines"):
            prior_card_fingerprint = fingerprint(prior_raw)
        same_card = bool(prior_card_fingerprint and prior_card_fingerprint == current_card_fingerprint)

        # A completed task can leave a stale detail_pending flag behind after
        # the exact same card revision has already supplied a usable description.
        # Reconcile that inconsistency locally instead of fetching it again.
        if (existing_task.status == "done" and same_card and raw.get("detail_pending")
                and (job.description or "").strip() and not missing_fields):
            try:
                current_raw = json.loads(job.raw or "{}")
            except (ValueError, TypeError):
                current_raw = {}
            if not isinstance(current_raw, dict):
                current_raw = {}
            current_raw.pop("detail_pending", None)
            job.raw = json.dumps(current_raw, ensure_ascii=False)
            audit.record(session, None, None, "repair_pending_reconciled", {
                "external_id":job.external_id, "reason":"same_card_revision_already_has_description"})
            continue

        # A removed-source task should stay quiet until the public card changes.
        if existing_task.status == "unavailable" and same_card:
            continue

        # Reopen only a completed/unavailable row selected above. Preserve
        # cumulative request history; a genuinely new card gets a fresh attempt
        # budget while a same-card consistency repair keeps its attempt count.
        for key in ("source_request_attempts", "access_denied_attempts", "network_error_attempts",
                    "http_status_counts", "first_source_attempt_at", "last_source_attempt_at",
                    "last_source_outcome", "last_attempt_id"):
            if key in prior_raw:
                raw[key] = prior_raw[key]
        stage = "enrich" if raw.get("_repair_fields") and not set(raw["_repair_fields"]) & set(SOURCE_FIELDS) else "detail"
        previous_status = existing_task.status
        existing_task.raw = json.dumps(raw, ensure_ascii=False)
        existing_task.stage = stage
        existing_task.status = "pending"
        if not same_card:
            existing_task.attempts = 0
        existing_task.next_attempt_at = 0
        existing_task.last_error = "Yeni ilan kartı revizyonu." if not same_card else "Eksik kaynak alanı yeniden sıraya alındı."
        existing_task.updated_at = datetime.utcnow()
        audit.record(session, None, None, "repair_reopened", {
            "external_id":job.external_id, "previous_status":previous_status,
            "card_changed":not same_card, "stage":stage})


def summary(session):
    counts = {status: count for status, count in session.query(RepairTask.status, func.count()).group_by(RepairTask.status)}
    stages = {stage: count for stage, count in session.query(RepairTask.stage, func.count()).filter(
        RepairTask.status.in_(("pending", "retry"))).group_by(RepairTask.stage)}
    next_at = session.query(func.min(RepairTask.next_attempt_at)).filter(RepairTask.status == "retry").scalar()
    now = time.time()
    oldest_detail = session.query(func.min(RepairTask.updated_at)).filter(
        RepairTask.status.in_(("pending", "retry")), RepairTask.stage == "detail",
        RepairTask.next_attempt_at <= now).scalar()
    oldest_seconds = max(0.0, now - oldest_detail.replace(tzinfo=timezone.utc).timestamp()) if oldest_detail else 0.0
    return dict(counts=counts, stages=stages, next_attempt_at=next_at,
                oldest_detail_seconds=round(oldest_seconds),
                paused=completion_paused(session),
                priority=["manual", "repair", "routine"])


def source_request_count_since_routine(session):
    setting = session.get(Setting, SOURCE_REQUEST_COUNTER)
    try:
        return max(0, int(setting.value)) if setting else 0
    except (TypeError, ValueError):
        return 0


def add_source_requests_since_routine(session, count):
    if count <= 0:
        return source_request_count_since_routine(session)
    setting = session.get(Setting, SOURCE_REQUEST_COUNTER)
    if setting is None:
        setting = Setting(key=SOURCE_REQUEST_COUNTER, value="0")
        session.add(setting)
    setting.value = str(source_request_count_since_routine(session) + int(count))
    return int(setting.value)


def reset_source_requests_since_routine(session):
    setting = session.get(Setting, SOURCE_REQUEST_COUNTER)
    if setting is None:
        session.add(Setting(key=SOURCE_REQUEST_COUNTER, value="0"))
    else:
        setting.value = "0"


def source_request_budget(session, now=None):
    """Bound repair traffic adaptively from ready detail count and oldest age."""
    now = time.time() if now is None else now
    count, oldest_value = session.query(func.count(RepairTask.external_id), func.min(RepairTask.updated_at)).filter(
        RepairTask.status.in_(("pending", "retry")), RepairTask.stage == "detail",
        RepairTask.next_attempt_at <= now).one()
    if not count or oldest_value is None:
        return 0
    oldest = oldest_value.replace(tzinfo=timezone.utc).timestamp()
    age_hours = max(0.0, (now-oldest)/3600.0)
    # One source request per routine turn for a fresh queue; increase gradually
    # as the oldest detail ages or the queue grows, with a strict ceiling.
    return min(8, max(1, 1 + int(age_hours // 6) + count//50))


def ready(session, now, source, layer="repair"):
    if layer == "repair" and completion_paused(session):
        return None
    query = session.query(RepairTask).filter(RepairTask.status.in_(("pending", "retry")), RepairTask.next_attempt_at <= now)
    query = query.filter(func.coalesce(func.json_extract(RepairTask.raw, '$._queue_layer'), "repair") == layer)
    if source["paused"]:
        query = query.filter(RepairTask.stage == "enrich")
    # Finish the last fetched posting before issuing more source requests.
    return query.order_by((RepairTask.stage != "enrich"), RepairTask.updated_at, RepairTask.external_id).first()


def dispatch(server, session, now, source, layer="repair"):
    if layer == "repair" and completion_paused(session):
        return False
    discover(session)
    session.commit()
    task = ready(session, now, source, layer)
    if not task:
        return False
    key = (task.source, task.external_id)
    server.state.running = True
    server.state.kind = "repair"
    server.state.run_id = None
    server.state.stop_flag = False
    server.state.last = {"state":"running", "external_id":task.external_id, "stage":task.stage, "queue_layer":layer}
    server.state.thread = threading.Thread(target=worker, args=(server, key), name="completion-worker", daemon=True)
    server.state.thread.start()
    return True


def sync_exports(session, job, raw):
    from .search_export import _write_json, SearchExport
    root = Path(config.ACCOUNTLESS_OUTPUT_DIR).resolve()
    search = session.get(SearchTask, raw.get("search_id")) if raw.get("search_id") else None
    if search and search.folder:
        folder = (root/search.folder).resolve()
        if folder.is_relative_to(root) and (folder/"search.json").is_file():
            exporter = SearchExport(root)
            exporter.current = folder
            exporter.metadata = json.loads((folder/"search.json").read_text(encoding="utf-8"))
            exporter.ids = {p.stem for p in (folder/"ilan_havuzu").glob("*.json")}
            path = folder/"ilan_havuzu"/f"ap-{job.source}-{job.external_id}.json"
            if not path.exists():
                exporter.save(raw)
    for path in root.glob(f"*/ilan_havuzu/ap-{job.source}-{job.external_id}.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(title=job.title, company=job.company, location=job.location,
                    desc=job.description, skills=json.loads(job.tags or "[]"))
        data["opportunityType"] = job.opportunity_type
        data["internshipDetails"] = json.loads(job.internship_details or "{}")
        data.setdefault("_collector", {}).update(descriptionAvailable=True, repairedAt=datetime.utcnow().isoformat()+"Z")
        _write_json(path, data)


def worker(server, key):
    scraper = None
    attempt_id = uuid.uuid4().hex
    try:
        with server.SessionLocal() as session:
            task = session.get(RepairTask, key)
            if task.status == "paused":
                return
            raw, stage = json.loads(task.raw), task.stage
            job = session.query(Job).filter_by(source=key[0], external_id=key[1]).first()
            if (job and job.deleted_at) or (not job and raw.get("_repair_existing_job_id")):
                task.status = "deleted"
                session.commit()
                return
            existing_description = job.description if job else ""
            job_id = job.id if job else None
            fields = raw.get("_repair_fields", ["description"])
        from .details import recorder
        audit_emit = recorder(server, raw, job_id)
        def emit(kind, data):
            context = dict(data, task_id=f"{key[0]}:{key[1]}", attempt_id=attempt_id,
                           queue_layer=raw.get("_queue_layer", "repair"))
            audit_emit(kind, context)
            server.state.emit(kind, context)
        if stage == "detail":
            from .scraper.accountless import AccountlessScraper
            from .transport import shared_http_transport
            scraper = AccountlessScraper(emit=emit, should_stop=lambda:server.state.stop_flag, max_retries=0,
                transport=shared_http_transport(server.state),
                request_context={"task_id":f"{key[0]}:{key[1]}", "attempt_id":attempt_id,
                    "queue_layer":raw.get("_queue_layer", "repair"),
                    "request_reason":"repair_detail_refresh" if raw.get("detail_pending") else "repair_missing_field"})
            # Always construct the public source URL; never follow URLs from legacy data.
            raw["url"] = f"https://www.linkedin.com/jobs/view/{key[1]}"
            force_refresh = bool(raw.get("_repair_force_requested"))
            cache_decision = scraper.details.lookup(raw, force=force_refresh)
            cached = cache_decision["value"]
            emit("cache_hit" if cached else "cache_miss", {"external_id":key[1],
                "reason":cache_decision["reason"], "fingerprint":fingerprint(raw),
                "force_refresh":force_refresh})
            description_stamp = raw.get("detail_fetched_at")
            pending_revision = bool(raw.get("detail_pending"))
            stale_description = pending_revision or cache_decision["reason"] == "card_changed"
            refresh_description = stale_description or (force_refresh and "description" in fields)
            description = ("" if refresh_description else
                           existing_description or raw.get("description") or "")
            if stale_description and "description" not in fields:
                fields = list(fields) + ["description"]
                raw["_repair_fields"] = fields
            if force_refresh and "description" in fields:
                description = ""
            if not description and cached and cached["status"] == 200:
                description = cached["description"] or ""
                description_stamp = cached["fetched_at"]
            need_source_fields = set(fields) & {"title", "company", "location"}
            if (not description.strip() or need_source_fields) and not (cached and cached["status"] in (404, 410)):
                soup = scraper._get(scraper.detail_url(raw))
                if server.state.stop_flag and soup is None:
                    return
                box = soup.select_one(".show-more-less-html__markup, .description__text") if soup else None
                if box and "description" in fields:
                    description = box.get_text("\n", strip=True)
                values = raw.get("_repair_values", {})
                selectors = {"title":".top-card-layout__title, .topcard__title",
                    "company":".topcard__org-name-link, .topcard__flavor a",
                    "location":".topcard__flavor--bullet"}
                for field in need_source_fields:
                    node = soup.select_one(selectors[field]) if soup else None
                    if node and node.get_text(strip=True):
                        values[field] = node.get_text(" ", strip=True)
                raw["_repair_values"] = values
                if box and "description" in fields and description.strip():
                    description_stamp = scraper.details.put(raw, description)["fetched_at"]
            raw.pop("_repair_force_requested", None)
            with server.SessionLocal() as session:
                task = session.get(RepairTask, key)
                missing = [f for f in need_source_fields if not raw.get("_repair_values", {}).get(f)]
                if description.strip() and not missing:
                    raw["description"] = description
                    if description_stamp is not None:
                        raw["detail_fetched_at"] = description_stamp
                    task.raw, task.stage = json.dumps(raw, ensure_ascii=False), "enrich"
                    task.status, task.next_attempt_at, task.last_error = "paused" if task.status == "paused" else "pending", 0, ""
                elif (cached and cached["status"] in (404, 410)) or getattr(scraper, "last_status", None) in (404, 410):
                    task.status, task.last_error = "unavailable", "Kaynak ilanı kaldırmış (404/410)."
                    existing = session.query(Job).filter_by(source=key[0], external_id=key[1]).first()
                    if existing:
                        current_raw = json.loads(existing.raw or "{}")
                        current_raw.pop("detail_pending", None)
                        current_raw["detail_missing"] = True
                        existing.raw = json.dumps(current_raw, ensure_ascii=False)
                else:
                    raise RuntimeError("Kaynak yanıtında gerekli alanlar bulunamadı: " + ", ".join(missing or ["description"]))
                task.updated_at = datetime.utcnow()
                session.commit()
        else:
            from .pipeline import process_raw
            with server.SessionLocal() as session:
                task = session.get(RepairTask, key)
                job = session.query(Job).filter_by(source=key[0], external_id=key[1]).first()
                if (job and job.deleted_at) or (not job and raw.get("_repair_existing_job_id")):
                    task.status = "deleted"
                    session.commit()
                    return
                created = job is None
                has_card_revision = bool(raw.get("_repair_card_fingerprint"))
                card_changed = (raw.get("_repair_card_fingerprint") != card_fingerprint(job)
                    if job and has_card_revision else
                    bool(job and raw.get("_repair_revision") and raw["_repair_revision"] != revision(job)))
                if job and card_changed:
                    # A newer scan owns the record. Rebase the requested fields instead of overwriting it.
                    current = json.loads(job.raw or "{}")
                    if not isinstance(current, dict):
                        current = {}
                    current.update(external_id=job.external_id, url=job.url, card_layout="guest",
                        card_lines=[job.title, job.company, job.location], description=job.description,
                        _repair_existing_job_id=job.id, _repair_revision=revision(job), _repair_values={},
                        _repair_card_fingerprint=card_fingerprint(job),
                        _repair_fields=fields, _queue_layer=raw.get("_queue_layer", "repair"),
                        _repair_force=raw.get("_repair_force", False))
                    task.raw, task.stage, task.status = json.dumps(current, ensure_ascii=False), "detail", "pending"
                    task.updated_at = datetime.utcnow()
                    session.commit()
                    return
                deferred = bool(raw.pop("detail_pending", False))
                raw.pop("detail_failed", None)
                raw.pop("detail_attempts", None)
                raw.pop("detail_missing", None)
                if created:
                    job, _ = process_raw(session, raw, emit=emit)
                    session.flush()
                elif deferred:
                    from .details import _backend
                    job, _ = process_raw(session, raw, classify_backend=_backend(session, raw), emit=emit)
                    session.flush()
                else:
                    from .classify.rules import classify
                    from .parse import detect_workplace
                    # Keep existing authored/LLM fields and discovery timestamps.
                    for field, value in raw.get("_repair_values", {}).items():
                        if field in fields and field in SOURCE_FIELDS and value:
                            setattr(job, field, value)
                    if "description" in fields or not (job.description or "").strip():
                        job.description = raw["description"]
                    raw["card_lines"] = [job.title, job.company, job.location]
                    raw["card_layout"] = "guest"
                    raw["description"] = job.description
                    job.raw = json.dumps(raw, ensure_ascii=False)
                    if set(fields) & {"title", "company"}:
                        from .parse import parse_guest_card
                        job.quality_ok = bool(job.company and parse_guest_card(raw["card_lines"], job.description)["quality_ok"])
                    try:
                        tags = json.loads(job.tags or "[]")
                    except (ValueError, TypeError):
                        tags = []
                    if not isinstance(tags, list):
                        tags = []
                    dependent = bool(set(fields) & {"title", "description"})
                    if dependent or "tags" in fields:
                        job.tags = json.dumps(list(dict.fromkeys(tags+skills.extract_skills(job.title, job.description))), ensure_ascii=False)
                    from .opportunities import refresh
                    refresh(job)
                    if dependent or "experience_years" in fields:
                        from .pipeline import experience_years
                        job.experience_years = experience_years(job.description, job.title)
                    classified = classify(job.title, job.description)
                    if "category" in fields or (dependent and (not job.category or job.category == "Other")):
                        job.category = classified["category"]
                    if "seniority" in fields or (dependent and (not job.seniority or job.seniority == "Unknown")):
                        job.seniority = classified["seniority"]
                    if "workplace_type" in fields or ((dependent or "location" in fields) and not job.workplace_type):
                        job.workplace_type = detect_workplace(job.description)
                    job.embedding = None
                search_id = raw.get("search_id")
                if search_id and session.get(SearchTask, search_id) and not session.get(TaskJob, (search_id, job.id)):
                    session.add(TaskJob(task_id=search_id, job_id=job.id, is_new=created, outcome="new" if created else "updated"))
                session.flush()
                sync_exports(session, job, raw)
                task.status, task.last_error, task.updated_at = "done", "", datetime.utcnow()
                audit.record(session, raw.get("run_id"), search_id, "repair_completed", {"external_id":key[1], "job_id":job.id})
                job_id = job.id
                session.commit()
            server.state.emit("job", {"id":job_id, "repaired":True})
    except Exception as exc:
        with server.SessionLocal() as session:
            task = session.get(RepairTask, key)
            if not isinstance(exc, SourcePaused):
                task.attempts += 1
            if task.status != "paused":
                task.status = "retry"
            delay = 0 if isinstance(exc, SourcePaused) else min(86400, 300 * 2 ** min(task.attempts-1, 9))
            task.next_attempt_at = max(time.time()+delay, exc.state["blocked_until"] if isinstance(exc, SourcePaused) else 0)
            task.last_error, task.updated_at = str(exc), datetime.utcnow()
            session.commit()
        if isinstance(exc, SourcePaused):
            from .details import record
            record(server, raw, "source_paused", dict(exc.state, job_id=job_id), "warning")
        server.state.emit("repair_retry", {"external_id":key[1], "reason":str(exc)})
    finally:
        if scraper:
            with server.SessionLocal() as session:
                task = session.get(RepairTask, key)
                if task:
                    try:
                        task_raw = json.loads(task.raw or "{}")
                    except (ValueError, TypeError):
                        task_raw = {}
                    task_raw["last_attempt_id"] = attempt_id
                    task_raw["source_request_attempts"] = task_raw.get("source_request_attempts", 0) + scraper.requests
                    task_raw["access_denied_attempts"] = task_raw.get("access_denied_attempts", 0) + scraper.access_denied_requests
                    task_raw["network_error_attempts"] = task_raw.get("network_error_attempts", 0) + scraper.network_errors
                    status_counts = task_raw.get("http_status_counts", {})
                    for status, count in scraper.http_status_counts.items():
                        status_counts[status] = status_counts.get(status, 0) + count
                    task_raw["http_status_counts"] = status_counts
                    if scraper.requests:
                        task_raw.setdefault("first_source_attempt_at", time.time())
                        task_raw["last_source_attempt_at"] = time.time()
                        task_raw["last_source_outcome"] = scraper.last_semantic_outcome or "request_finished"
                    task.raw = json.dumps(task_raw, ensure_ascii=False)
                if raw.get("_queue_layer", "repair") == "repair":
                    add_source_requests_since_routine(session, scraper.requests)
                session.commit()
        if scraper and scraper.owns_transport:
            scraper.transport.close()
        with runs.lock:
            server.state.running = False
            server.state.stop_flag = False
            server.state.last = {"state":"idle"}
