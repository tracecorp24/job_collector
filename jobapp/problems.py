"""Sorun kuralları: hata fırlatmayan ama gözden kaçmaması gereken durumları hata kaydına çevirir.

Beş dakikada bir her kural değerlendirilir. Koşul sağlanınca `kind=problem` hata kaydı açılır (GitHub
issue'su `incident_sync` ile açılır); koşul 30 dakika boyunca ortadan kalkarsa kayıt kendiliğinden çözülür.
Kayıtlar silinmez. Kural eşikleri aşağıdadır; kaynak bekleme politikasına dokunmaz, yalnızca gözlemler.
"""
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config, details, logstore, service
from .models import SearchRun, Setting

log = logging.getLogger("linko.problems")
EVERY_SECONDS = 300.0
CLEAR_AFTER_SECONDS = 1800.0
SOURCE_BLOCK_SECONDS = 3 * 3600
SOURCE_VIOLATION_STREAK = 5
STALLED_SECONDS = 24 * 3600
SUPERVISOR_ERROR_SECONDS = 600
DETAIL_BACKLOG_SECONDS = 24 * 3600
BACKUP_STALE_SECONDS = 36 * 3600
DROP_WINDOW_SECONDS = 1800
BACKLOG_KEY = "problem_detail_backlog"

memory = {}          # kural başına bellek içi durum (hata süresi, sayaçlar)
inactive_since = {}  # kural anahtarı -> koşulun ilk kalktığı an
active_keys = set()
thread = None


def source_blocked_long(session, now):
    from .transport import Coordinator
    state = Coordinator().state()
    if state["remaining_seconds"] >= SOURCE_BLOCK_SECONDS or state["violation_streak"] >= SOURCE_VIOLATION_STREAK:
        return ("Kaynak uzun süredir kilitli",
                f"Kalan bekleme {state['remaining_seconds']} sn, ardışık ihlal {state['violation_streak']}, son durum: {state['reason']}")


def queue_stalled(session, now):
    from .transport import Coordinator
    if Coordinator().state()["paused"]:
        return None
    cutoff = datetime.utcfromtimestamp(now - STALLED_SECONDS)
    runs = session.query(SearchRun).filter(SearchRun.deleted_at.is_(None), SearchRun.updated_at < cutoff,
                                           SearchRun.status.in_(("queued", "paused", "error", "running")))
    for run in runs:
        options = json.loads(run.options or "{}")
        if options.get("user_paused") or options.get("kind", "scrape") != "scrape":
            continue
        if run.status == "queued" and not options.get("service_managed"):
            continue  # Kullanıcının taslak kuyruğu kendiliğinden başlamaz.
        return ("Kuyruk ilerlemiyor", f"Koşu {run.id[:8]} {run.status} durumunda, son güncelleme {run.updated_at.isoformat()}Z; kaynak açık.")


def supervisor_error(session, now):
    alive = bool(service.supervisor and service.supervisor.is_alive())
    if not service.last_error:
        memory.pop("error_since", None)
        return None
    since = memory.setdefault("error_since", now)
    if now - since >= SUPERVISOR_ERROR_SECONDS:
        return ("Toplayıcı hata veriyor", f"Son hata: {service.last_error[:300]} (yönetici iş parçacığı {'canlı' if alive else 'ÖLÜ'}).")


def detail_backlog(session, now):
    count = details.pending_count(session)
    paused = session.get(Setting, "completion_paused")
    if paused and paused.value == "1":
        session.merge(Setting(key=BACKLOG_KEY, value=json.dumps({"min":count, "since":now})))
        session.commit()
        return None  # An explicit user pause is not a stalled collector.
    row = session.get(Setting, BACKLOG_KEY)
    try:
        saved = json.loads(row.value) if row else None
    except ValueError:
        saved = None
    if not saved or count < saved["min"]:
        saved = {"min": count, "since": now}  # azaldı: ilerleme var, sayaç yeniden başlar
        session.merge(Setting(key=BACKLOG_KEY, value=json.dumps(saved)))
        session.commit()
    if count > 0 and now - saved["since"] >= DETAIL_BACKLOG_SECONDS:
        return ("Detay tamamlama tıkandı", f"{count} ilanın detayı bekliyor; {int((now - saved['since']) / 3600)} saattir azalmadı.")


def backup_stale(session, now):
    path = Path(config.BACKUP_STATUS_PATH)
    if not path.exists():
        return None
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ("Sunucu dışı yedek durumu okunamıyor", f"{path} okunamadı.")
    if not status.get("ok"):
        return ("Sunucu dışı yedek alınamıyor", str(status.get("message") or "Yedekleme başarısız."))
    if now - float(status.get("at", 0)) > BACKUP_STALE_SECONDS:
        return ("Sunucu dışı yedek eskidi", f"Son başarılı yedek {int((now - float(status['at'])) / 3600)} saat önce.")


def log_drops(session, now):
    stats = logstore.stats()
    total = stats.get("dropped", 0) + stats.get("spooled", 0)
    seen = memory.get("drops")
    if seen is None or total != seen[0]:
        memory["drops"] = seen = (total, now)
    if total > 0 and now - seen[1] < DROP_WINDOW_SECONDS:
        return ("Log kaydı kaybı riski",
                f"Yazılamayan: {stats.get('dropped', 0)}, dosyaya düşen: {stats.get('spooled', 0)}; son hata: {stats.get('last_error', '')}")


RULES = {
    "source_blocked_long": source_blocked_long,
    "queue_stalled": queue_stalled,
    "supervisor_error": supervisor_error,
    "detail_backlog": detail_backlog,
    "backup_stale": backup_stale,
    "log_drops": log_drops,
}


def run_once(session, now=None):
    """Kuralları değerlendirir; sorun kayıtlarını açar/günceller, kalkanları (30 dk sonra) çözer."""
    now = time.time() if now is None else now
    for key, rule in RULES.items():
        try:
            outcome = rule(session, now)
        except Exception:
            log.exception("Sorun kuralı değerlendirilemedi: %s", key)
            continue
        if outcome:
            inactive_since.pop(key, None)
            active_keys.add(key)
            logstore.raise_problem(session, key, *outcome)
        else:
            active_keys.discard(key)
            since = inactive_since.setdefault(key, now)
            if now - since >= CLEAR_AFTER_SECONDS:
                if logstore.clear_problem(session, key, f"Koşul {int(CLEAR_AFTER_SECONDS / 60)} dakikadır sağlanmıyor; otomatik çözüldü."):
                    log.info("Sorun çözüldü: %s", key)


def start(server):
    global thread
    if thread and thread.is_alive():
        return

    def loop():
        time.sleep(30)
        while True:
            try:
                with server.SessionLocal() as session:
                    run_once(session)
            except Exception:
                log.exception("Sorun kuralları döngüsü başarısız; sonraki turda yeniden denenecek")
            time.sleep(EVERY_SECONDS)
    thread = threading.Thread(target=loop, name="problem-rules", daemon=True)
    thread.start()
