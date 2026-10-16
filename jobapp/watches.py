"""Düzenli taramalar: kayıtlı unvan × konum kombinasyonları servis tarafından tekrar taranır.

Kaynağı yormamak için her tur yalnızca yakın zamanda yayınlanan ilanları, en yeniden eskiye
ister; veritabanında zaten bulunan ilanların detayını yeniden indirmez ve bir sayfanın
tamamı bilinen ilanlardan oluşuyorsa o kombinasyonu bitirir. Turlar arası süreye rastgele
pay eklenir; önceki tur bitmeden yenisi açılmaz, kaynak duraklatılmışsa tur ertelenir.
"""
import json
import random
import time
from datetime import datetime
import logging
from flask import jsonify, request
from . import audit, config, runs
from .models import SearchRun, SearchTask, Watch

INTERVALS = (3600, 3*3600, 6*3600, 12*3600, 24*3600, 3*86400, 7*86400)
POSTED_WITHIN = (0, 86400, 7*86400, 30*86400)
MAX_KEYWORDS, MAX_LOCATIONS, MAX_COMBINATIONS, MAX_LIMIT = 20, 10, 40, 200
JITTER = 0.1
log = logging.getLogger(__name__)


def _items(value, label, maximum, commas=False):
    if isinstance(value, str):
        # Konumlar "Istanbul, Turkey" gibi virgül içerir; yalnızca unvanlar virgülle bölünür.
        value = (value.replace(",", "\n") if commas else value).splitlines()
    if not isinstance(value, list):
        raise ValueError(f"{label} listesi geçersiz.")
    result = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > 200:
            raise ValueError(f"{label} en fazla 200 karakter olabilir.")
        if text.casefold() not in {r.casefold() for r in result}:
            result.append(text)
    if not result:
        raise ValueError(f"En az bir {label.lower()} girin.")
    if len(result) > maximum:
        raise ValueError(f"En fazla {maximum} {label.lower()} eklenebilir.")
    return result


def _integer(value, label, allowed=None, low=None, high=None):
    if isinstance(value, bool):
        raise ValueError(f"{label} geçersiz.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} tam sayı olmalı.")
    if allowed is not None and number not in allowed:
        raise ValueError(f"{label} için geçersiz seçim.")
    if low is not None and not low <= number <= high:
        raise ValueError(f"{label} {low}–{high} aralığında olmalı.")
    return number


def validate(body, current=None):
    if not isinstance(body, dict):
        raise ValueError("İstek gövdesi JSON nesnesi olmalı.")
    base = dict(current or {})
    base.update(body)
    keywords = _items(base.get("keywords"), "Unvan", MAX_KEYWORDS, commas=True)
    locations = _items(base.get("locations"), "Konum", MAX_LOCATIONS)
    if len(keywords) * len(locations) > MAX_COMBINATIONS:
        raise ValueError(f"Unvan × konum en fazla {MAX_COMBINATIONS} kombinasyon olabilir "
                         f"(şu an {len(keywords) * len(locations)}). Kaynağı yormamak için listeyi bölün.")
    return dict(
        name=str(base.get("name") or "").strip()[:200] or f"{keywords[0]} · {locations[0]}",
        keywords=keywords, locations=locations,
        interval_seconds=_integer(base.get("interval_seconds", 21600), "Tarama sıklığı", allowed=INTERVALS),
        limit=_integer(base.get("limit", 50), "Kombinasyon başına ilan hedefi", low=1, high=MAX_LIMIT),
        posted_within=_integer(base.get("posted_within", 86400), "Yayın tarihi aralığı", allowed=POSTED_WITHIN),
        enabled=bool(base.get("enabled", True)),
    )


def serialize(session, watch):
    keywords, locations = json.loads(watch.keywords), json.loads(watch.locations)
    last = session.get(SearchRun, watch.last_run_id) if watch.last_run_id else None
    last_info = None
    if last and not last.deleted_at:
        snap = runs.snapshot(session, last)
        last_info = dict(id=last.id, status=last.status, new=snap["stats"].get("new", 0),
                         updated=snap["stats"].get("updated", 0), created_at=last.created_at.isoformat(),
                         ended_at=last.ended_at.isoformat() if last.ended_at else None)
    return dict(id=watch.id, name=watch.name, keywords=keywords, locations=locations,
                combinations=len(keywords) * len(locations), interval_seconds=watch.interval_seconds,
                limit=watch.limit, posted_within=watch.posted_within, enabled=bool(watch.enabled),
                next_due_at=watch.next_due_at, last_dispatched_at=watch.last_dispatched_at, last_run=last_info,
                created_at=watch.created_at.isoformat() if watch.created_at else None)


def _busy(session, watch):
    if not watch.last_run_id:
        return False
    run = session.get(SearchRun, watch.last_run_id)
    return bool(run and not run.deleted_at and run.status not in runs.TERMINAL)


def dispatch(session, now, source):
    """Create at most one due watch run. Called by the supervisor with runs.lock held."""
    if source.get("paused"):
        return None
    for watch in session.query(Watch).filter(Watch.enabled.is_(True), Watch.next_due_at <= now).order_by(Watch.next_due_at):
        if _busy(session, watch):
            log.info("Düzenli tarama '%s' bekliyor: önceki tur (%s) henüz bitmedi.", watch.name, watch.last_run_id[:8])
            continue
        run_id = runs.identifier()
        options = dict(kind="scrape", service_managed=True, watch_id=watch.id, classify_backend="groq" if config.GROQ_API_KEY else "rules",
                       use_embeddings=False, mode="incremental", refresh_details=False,
                       posted_within=watch.posted_within, sort_recent=True, stop_when_known=True)
        session.add(SearchRun(id=run_id, options=json.dumps(options)))
        position = 0
        for location in json.loads(watch.locations):
            for keyword in json.loads(watch.keywords):
                task_id = runs.identifier()
                session.add(SearchTask(id=task_id, run_id=run_id, position=position, keyword=keyword,
                                       location=location, limit=watch.limit))
                audit.record(session, run_id, task_id, "task_queued", dict(keyword=keyword, location=location, limit=watch.limit))
                position += 1
        watch.last_run_id = run_id
        watch.last_dispatched_at = now
        watch.next_due_at = now + watch.interval_seconds * (1 + random.uniform(0, JITTER))
        audit.record(session, run_id, None, "watch_run_created", {"watch_id": watch.id, "name": watch.name, "options": options})
        session.commit()
        return run_id
    return None


def install(server):
    app = server.app

    @app.get("/api/watches")
    def list_watches():
        with server.SessionLocal() as session:
            rows = session.query(Watch).order_by(Watch.created_at).all()
            return jsonify(watches=[serialize(session, w) for w in rows], now=time.time(),
                           limits=dict(keywords=MAX_KEYWORDS, locations=MAX_LOCATIONS, combinations=MAX_COMBINATIONS, limit=MAX_LIMIT))

    @app.post("/api/watches")
    def create_watch():
        data = validate(request.get_json(silent=True))
        with runs.lock, server.SessionLocal() as session:
            watch = Watch(id=runs.identifier(), name=data["name"], keywords=json.dumps(data["keywords"], ensure_ascii=False),
                          locations=json.dumps(data["locations"], ensure_ascii=False), interval_seconds=data["interval_seconds"],
                          limit=data["limit"], posted_within=data["posted_within"], enabled=data["enabled"], next_due_at=time.time())
            session.add(watch)
            session.commit()
            return jsonify(watch=serialize(session, watch)), 201

    @app.put("/api/watches/<watch_id>")
    def update_watch(watch_id):
        with runs.lock, server.SessionLocal() as session:
            watch = session.get(Watch, watch_id)
            if not watch:
                return jsonify(ok=False, error="Düzenli tarama bulunamadı."), 404
            current = dict(name=watch.name, keywords=json.loads(watch.keywords), locations=json.loads(watch.locations),
                           interval_seconds=watch.interval_seconds, limit=watch.limit, posted_within=watch.posted_within,
                           enabled=bool(watch.enabled))
            data = validate(request.get_json(silent=True), current)
            if data["interval_seconds"] != watch.interval_seconds and watch.last_dispatched_at:
                watch.next_due_at = watch.last_dispatched_at + data["interval_seconds"]
            if data["enabled"] and not watch.enabled:
                watch.next_due_at = max(watch.next_due_at or 0, time.time())
            watch.name, watch.interval_seconds, watch.limit = data["name"], data["interval_seconds"], data["limit"]
            watch.posted_within, watch.enabled = data["posted_within"], data["enabled"]
            watch.keywords = json.dumps(data["keywords"], ensure_ascii=False)
            watch.locations = json.dumps(data["locations"], ensure_ascii=False)
            watch.updated_at = datetime.utcnow()
            session.commit()
            return jsonify(watch=serialize(session, watch))

    @app.post("/api/watches/<watch_id>/run-now")
    def run_watch_now(watch_id):
        with runs.lock, server.SessionLocal() as session:
            watch = session.get(Watch, watch_id)
            if not watch:
                return jsonify(ok=False, error="Düzenli tarama bulunamadı."), 404
            if _busy(session, watch):
                return jsonify(ok=False, error="Bu düzenli taramanın önceki turu henüz bitmedi."), 409
            watch.enabled = True
            watch.next_due_at = time.time()
            session.commit()
            return jsonify(watch=serialize(session, watch))

    @app.delete("/api/watches/<watch_id>")
    def delete_watch(watch_id):
        with runs.lock, server.SessionLocal() as session:
            watch = session.get(Watch, watch_id)
            if not watch:
                return jsonify(ok=False, error="Düzenli tarama bulunamadı."), 404
            session.delete(watch)
            session.commit()
            return jsonify(ok=True)
