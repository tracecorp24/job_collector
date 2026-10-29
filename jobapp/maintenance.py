"""Günlük bakım: büyüyen kayıt tablolarını saklama süresine göre budar ve depolama durumunu raporlar.

`search_events` arama işlem kayıtlarını, `job_changes` API değişiklik akışını tutar; ikisi de her
taramada büyür. Süreleri `JOBAPP_EVENT_RETENTION_DAYS` ve `JOBAPP_CHANGES_RETENTION_DAYS` belirler.
Değişiklik akışı tüketicisi bu süreden daha uzun ara verirse `after=0` ile baştan senkronize olmalıdır.
"""
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import text
from . import config, db
from .models import Setting

log = logging.getLogger(__name__)
MARKER = "maintenance_last_run"
EVERY_SECONDS = 86400


def due(session, now):
    row = session.get(Setting, MARKER)
    try:
        return now - json.loads(row.value)["at"] >= EVERY_SECONDS if row else True
    except (ValueError, KeyError, TypeError):
        return True


def run(session, now=None):
    """Budar, sonucu settings'e yazar. Çağıran supervisor kilidini tutar."""
    now = time.time() if now is None else now
    events_cutoff = datetime.utcfromtimestamp(now) - timedelta(days=config.EVENT_RETENTION_DAYS)
    changes_cutoff = (datetime.utcfromtimestamp(now) - timedelta(days=config.CHANGES_RETENTION_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    events = session.execute(text("DELETE FROM search_events WHERE created_at < :cutoff"), {"cutoff": events_cutoff}).rowcount
    changes = session.execute(text("DELETE FROM job_changes WHERE created_at < :cutoff"), {"cutoff": changes_cutoff}).rowcount
    # Hata kayıtları (incidents) hiçbir zaman budanmaz; yalnızca ham log satırları.
    logs_cutoff = datetime.utcfromtimestamp(now) - timedelta(days=config.APP_LOG_RETENTION_DAYS)
    app_logs = session.execute(text("DELETE FROM app_logs WHERE created_at < :cutoff"), {"cutoff": logs_cutoff}).rowcount
    result = dict(at=now, events_deleted=events, changes_deleted=changes, app_logs_deleted=app_logs,
                  event_retention_days=config.EVENT_RETENTION_DAYS, changes_retention_days=config.CHANGES_RETENTION_DAYS)
    row = session.get(Setting, MARKER) or Setting(key=MARKER)
    row.value = json.dumps(result)
    session.merge(row)
    session.commit()
    with db.engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA optimize")
    log.info("Günlük bakım: %s işlem kaydı, %s değişiklik kaydı ve %s sunucu logu budandı (saklama %s/%s/%s gün).",
             events, changes, app_logs, config.EVENT_RETENTION_DAYS, config.CHANGES_RETENTION_DAYS, config.APP_LOG_RETENTION_DAYS)
    return result


def storage(session):
    """Servis paneli için depolama, bakım ve sunucu dışı yedek durumu."""
    path = Path(db.engine.url.database or "")
    size = path.stat().st_size if path.name and path.exists() else None
    counts = {t: session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in ("jobs", "search_events", "job_changes", "app_logs", "incidents")}
    row = session.get(Setting, MARKER)
    backup = None
    status_file = Path(config.BACKUP_STATUS_PATH)
    try:
        backup = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else None
    except (OSError, ValueError):
        backup = {"ok": False, "message": "Yedek durum dosyası okunamadı."}
    from .details import pending_count
    return dict(db_bytes=size, counts=counts, details_pending=pending_count(session), maintenance=json.loads(row.value) if row else None, offsite_backup=backup,
                event_retention_days=config.EVENT_RETENTION_DAYS, changes_retention_days=config.CHANGES_RETENTION_DAYS)
