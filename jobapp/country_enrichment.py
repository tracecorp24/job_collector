"""Hourly AI enrichment for job postings with no known country."""
import json
import logging
import threading
import time

from sqlalchemy import func, or_

from . import config, groq_client
from .locations import normalize_country
from .models import Job, Setting

log = logging.getLogger("linko.country_enrichment")
KEY = "country_enrichment_state"
INTERVAL_SECONDS = 60 * 60
BATCH_SIZE = 20
_lock = threading.Lock()
_running = False
_last_check = 0.0


def _missing_country(query):
    return query.filter(or_(Job.location_country.is_(None),
                            func.trim(Job.location_country) == "",
                            func.lower(func.trim(Job.location_country)).like("belirtilmem%")))


def _job_payload(job):
    return {
        "id": job.id,
        "title": job.title or "",
        "company": job.company or "",
        "location": job.location or "",
        "search_location": job.search_location or "",
        "search_term": job.search_term or "",
        "description": (job.description or "")[:700],
    }


def _infer(jobs):
    """Make one bounded Groq request and return only recognized country values."""
    messages = [
        {"role": "system", "content": (
            "You identify the country where a job is located from job data. "
            "Use only direct evidence in location, search location, company, title, or description. "
            "Do not infer a country from the language of the text or the company's nationality. "
            "For worldwide/remote roles without a specific country, conflicting evidence, or weak evidence, use null. "
            "Return only JSON: {\"jobs\":[{\"id\": integer, \"country\": string|null}]}. "
            "Country must be a standard English country name. Include every input id exactly once."
        )},
        {"role": "user", "content": json.dumps(jobs, ensure_ascii=False)},
    ]
    result = groq_client.chat_json(messages, model=config.GROQ_CLASSIFY_MODEL,
                                   max_tokens=450, max_wait=12)
    inferred = {}
    rows = result.get("jobs", []) if isinstance(result, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            job_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        country = normalize_country(row.get("country"))
        if country:
            inferred[job_id] = country
    return inferred


def _run(server, ids, next_cursor, scheduled_at):
    global _running
    changed = 0
    try:
        with server.SessionLocal() as session:
            jobs = session.query(Job).filter(Job.id.in_(ids)).order_by(Job.id).all()
            payload = [_job_payload(job) for job in jobs]
        if not payload:
            inferred = {}
        else:
            inferred = _infer(payload)

        with server.SessionLocal() as session:
            for job_id, country in inferred.items():
                job = session.get(Job, job_id)
                current_country = (job.location_country or "").strip().casefold() if job else ""
                if job is None or (current_country and not current_country.startswith("belirtilmem")):
                    continue
                job.location_country = country
                changed += 1
            state = session.get(Setting, KEY)
            if state is None:
                state = Setting(key=KEY)
                session.add(state)
            try:
                saved = json.loads(state.value or "{}")
            except (ValueError, TypeError):
                saved = {}
            saved.update(cursor=next_cursor, last_finished_at=time.time(), last_updated=changed,
                         last_attempt_at=scheduled_at)
            state.value = json.dumps(saved, ensure_ascii=False)
            session.commit()
        log.info("Ülke zenginleştirme tamamlandı: aday=%d, güncellenen=%d", len(ids), changed)
    except groq_client.GroqError as exc:
        log.warning("Ülke zenginleştirme AI isteği başarısız oldu; sonraki saat tekrar denenecek: %s", exc)
    except Exception:
        log.exception("Ülke zenginleştirme servisi başarısız oldu; sonraki saat tekrar denenecek.")
    finally:
        with _lock:
            _running = False


def dispatch(server, now=None):
    """Start at most one hourly enrichment batch from the collector supervisor."""
    global _running, _last_check
    if not config.GROQ_API_KEY:
        return False
    now = time.time() if now is None else now
    with _lock:
        if _running or now - _last_check < 60:
            return False
        _last_check = now
    try:
        with server.SessionLocal() as session:
            state = session.get(Setting, KEY)
            try:
                saved = json.loads(state.value or "{}") if state else {}
            except (ValueError, TypeError):
                saved = {}
            if now < float(saved.get("next_run_at", 0) or 0):
                return False
            cursor = int(saved.get("cursor", 0) or 0)
            base = _missing_country(session.query(Job).filter(Job.deleted_at.is_(None)))
            candidates = base.filter(Job.id > cursor).order_by(Job.id).limit(BATCH_SIZE).all()
            if not candidates and cursor:
                candidates = base.order_by(Job.id).limit(BATCH_SIZE).all()
            if not candidates:
                return False
            ids = [job.id for job in candidates]
            next_cursor = ids[-1]
            scheduled_at = now
            saved.update(next_run_at=now + INTERVAL_SECONDS, last_started_at=now)
            if state is None:
                state = Setting(key=KEY)
                session.add(state)
            state.value = json.dumps(saved, ensure_ascii=False)
            session.commit()
        with _lock:
            _running = True
        thread = threading.Thread(target=_run, args=(server, ids, next_cursor, scheduled_at),
                                  name="country-enrichment", daemon=True)
        thread.start()
        return True
    except Exception:
        log.exception("Ülke zenginleştirme zamanlayıcısı çalıştırılamadı.")
        return False
