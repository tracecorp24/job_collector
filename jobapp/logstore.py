"""Sunucu loglarını kalıcı tabloya yazar ve hataları kaybolmayan hata kayıtlarına (incident) toplar.

journald satırları yalnızca sunucuda okunabilir; bu modül aynı kayıtları `app_logs` tablosuna da
yazar, böylece `/api/v1/logs` üzerinden yerelden sorgulanıp indirilebilir. ERROR ve üstü her kayıt,
mesajın değişken kısımları (sayı, kimlik) atılarak parmak izine dönüştürülür; aynı parmak izi tek
`incidents` satırında sayılır. Hata kayıtları budanmaz, çözülse de geçmişiyle birlikte kalır.
"""
import hashlib
import json
import logging
import logging.handlers
import queue
import re
import sys
import threading
from datetime import datetime

from . import db
from .models import AppLog, Incident

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
_guard = threading.local()
_listener = None


def fingerprint(logger, message):
    first = (message or "").splitlines()[0] if message else ""
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", first.lower())
    text = re.sub(r"\d+(\.\d+)?", "<n>", text)
    return hashlib.sha256(f"{logger}|{text}".encode("utf-8")).hexdigest()


def _history(incident, event, **data):
    items = json.loads(incident.history or "[]")
    items.append(dict(at=datetime.utcnow().isoformat() + "Z", event=event, **data))
    incident.history = json.dumps(items, ensure_ascii=False)


def store(level, logger, message, traceback="", created_at=None, session=None):
    """Bir log satırını yazar; hata düzeyindeyse ilgili hata kaydını açar veya günceller."""
    own = session is None
    session = session or db.SessionLocal(bind=db.engine)
    try:
        level = level.lower()
        created_at = created_at or datetime.utcnow()
        incident_id = None
        if LEVELS.get(level, 0) >= LEVELS["error"]:
            fp = fingerprint(logger, message)
            incident = session.query(Incident).filter_by(fingerprint=fp).first()
            if incident is None:
                incident = Incident(fingerprint=fp, level=level, logger=logger, count=0, first_seen=created_at,
                                    title=f"[{logger}] {(message or '').splitlines()[0][:150] if message else 'Hata'}")
                _history(incident, "opened")
                session.add(incident)
            elif incident.status == "resolved":
                incident.status = "open"
                incident.reopen_count = (incident.reopen_count or 0) + 1
                incident.resolved_at = None
                _history(incident, "reopened", reason="Çözüldükten sonra tekrar görüldü.")
            incident.count = (incident.count or 0) + 1
            incident.last_seen = created_at
            incident.sample = (message or "")[:4000]
            incident.traceback = (traceback or incident.traceback or "")[:20000]
            session.flush()
            incident_id = incident.id
        session.add(AppLog(created_at=created_at, level=level, logger=logger[:80], message=(message or "")[:8000],
                           traceback=(traceback or "")[:20000], incident_id=incident_id))
        session.commit()
        return incident_id
    finally:
        if own:
            session.close()


class DatabaseHandler(logging.Handler):
    def emit(self, record):
        if getattr(_guard, "active", False):
            return
        _guard.active = True
        try:
            message = record.getMessage()
            trace = record.exc_text or (logging.Formatter().formatException(record.exc_info) if record.exc_info else "")
            store(record.levelname, record.name, message, trace, datetime.utcfromtimestamp(record.created))
        except Exception as exc:  # Log yazımı hiçbir zaman servisi durdurmamalı; journald'a düşer.
            print(f"app_logs yazılamadı: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            _guard.active = False


def install(level=logging.INFO):
    """Kök loga kuyruklu veritabanı yazıcısı ekler; yazım ayrı iş parçacığında yapılır."""
    global _listener
    if _listener:
        return _listener
    pending = queue.SimpleQueue()
    handler = logging.handlers.QueueHandler(pending)
    handler.setLevel(level)
    logging.getLogger().addHandler(handler)
    _listener = logging.handlers.QueueListener(pending, DatabaseHandler(), respect_handler_level=False)
    _listener.start()
    return _listener


def link_issue(incident, number):
    incident.issue_number = number
    incident.issue_state = "open"
    _history(incident, "issue_linked", issue=number)


def resolve(incident, resolution="", number=None):
    incident.status = "resolved"
    incident.issue_state = "closed"
    incident.resolved_at = datetime.utcnow()
    incident.resolution = resolution or "Çözüldü."
    _history(incident, "resolved", issue=number or incident.issue_number, resolution=incident.resolution)


def serialize(incident, full=False):
    data = dict(id=incident.id, fingerprint=incident.fingerprint, level=incident.level, logger=incident.logger,
                title=incident.title, count=incident.count, status=incident.status, issue_number=incident.issue_number,
                issue_state=incident.issue_state or "", reopen_count=incident.reopen_count or 0,
                first_seen=incident.first_seen.isoformat() + "Z" if incident.first_seen else None,
                last_seen=incident.last_seen.isoformat() + "Z" if incident.last_seen else None,
                resolved_at=incident.resolved_at.isoformat() + "Z" if incident.resolved_at else None,
                resolution=incident.resolution or "", sample=incident.sample or "")
    if full:
        data.update(traceback=incident.traceback or "", history=json.loads(incident.history or "[]"))
    return data
