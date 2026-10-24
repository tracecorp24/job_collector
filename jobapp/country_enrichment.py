"""Hourly AI enrichment for job postings with no known country."""
import json
import logging
import threading
import time

from sqlalchemy import and_, func, or_

from . import config, groq_client
from .locations import normalize, normalize_country
from .models import Job, Setting

log = logging.getLogger("linko.country_enrichment")
KEY = "country_enrichment_state"
INTERVAL_SECONDS = 60 * 60
BATCH_SIZE = 20
_lock = threading.Lock()
_running = False
_last_check = 0.0


def _missing_country(query):
    """Filter jobs with some location text but missing resolved country or city."""
    has_text = or_(
        and_(Job.location.isnot(None), func.trim(Job.location) != "", ~func.lower(func.trim(Job.location)).like("belirtilmem%")),
        and_(Job.search_location.isnot(None), func.trim(Job.search_location) != "", ~func.lower(func.trim(Job.search_location)).like("belirtilmem%")),
    )
    needs_enrichment = or_(
        Job.location_country.is_(None),
        func.trim(Job.location_country) == "",
        func.lower(func.trim(Job.location_country)).like("belirtilmem%"),
        Job.location_city.is_(None),
        func.trim(Job.location_city) == "",
        func.lower(func.trim(Job.location_city)).like("belirtilmem%"),
    )
    return query.filter(has_text, needs_enrichment)


_missing_location = _missing_country


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
    """Make one bounded Groq request and return recognized country and city values."""
    messages = [
        {"role": "system", "content": (
            "You identify the country and primary canonical city where a job is located from job data. "
            "Use only direct evidence in location, search location, company, title, or description. "
            "Do not infer location solely from the language of the text or the company's nationality. "
            "If a city is in Turkey (e.g. Istanbul, Ankara, Izmir, Gebze, Kocaeli, Bursa, etc.), country must be 'Türkiye'. "
            "For worldwide/fully remote roles without a specific country or city, conflicting evidence, weak evidence, or completely absent location, use null. "
            "Return only JSON: {\"jobs\":[{\"id\": integer, \"country\": string|null, \"city\": string|null}]}. "
            "Country must be a standard country name (e.g. 'Türkiye', 'Almanya', 'ABD', 'Hollanda', 'Birleşik Krallık'). "
            "City must be the primary canonical city name (e.g. 'İstanbul', 'Berlin', 'Londra', 'Amsterdam'). "
            "Include every input id exactly once."
        )},
        {"role": "user", "content": json.dumps(jobs, ensure_ascii=False)},
    ]
    result = groq_client.chat_json(messages, model=config.GROQ_CLASSIFY_MODEL,
                                   max_tokens=600, max_wait=15)
    inferred = {}
    rows = result.get("jobs", []) if isinstance(result, dict) else []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            job_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        raw_country = row.get("country")
        raw_city = row.get("city")
        country = normalize_country(raw_country) if raw_country else ""
        norm_country, norm_city = normalize(f"{raw_city or ''}, {raw_country or ''}".strip(", "))
        country = country or (norm_country if norm_country and norm_country != "Belirtilmemiş" else "")
        city = norm_city if norm_city and norm_city != "Belirtilmemiş" else (str(raw_city).strip() if raw_city else "")
        if country or city:
            inferred[job_id] = {"country": country, "city": city}
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
            for job_id, loc_val in inferred.items():
                job = session.get(Job, job_id)
                if job is None:
                    continue
                if isinstance(loc_val, dict):
                    country = loc_val.get("country")
                    city = loc_val.get("city")
                elif isinstance(loc_val, tuple):
                    country, city = loc_val
                else:
                    country, city = loc_val, None

                updated = False
                current_country = (job.location_country or "").strip().casefold()
                if country and (not current_country or current_country.startswith("belirtilmem")):
                    job.location_country = country
                    updated = True

                current_city = (job.location_city or "").strip().casefold()
                if city and (not current_city or current_city.startswith("belirtilmem") or current_city.startswith("greater ")):
                    job.location_city = city
                    updated = True

                if updated:
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
        log.info("Konum zenginleştirme tamamlandı: aday=%d, güncellenen=%d", len(ids), changed)
    except groq_client.GroqError as exc:
        log.warning("Konum zenginleştirme AI isteği başarısız oldu; sonraki saat tekrar denenecek: %s", exc)
    except Exception:
        log.exception("Konum zenginleştirme servisi başarısız oldu; sonraki saat tekrar denenecek.")
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
