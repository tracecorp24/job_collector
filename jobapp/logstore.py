"""Sunucu loglarını kalıcı tabloya yazar ve hataları kaybolmayan hata kayıtlarına (incident) toplar.

journald satırları yalnızca sunucuda okunabilir; bu modül aynı kayıtları `app_logs` tablosuna da
yazar, böylece `/api/v1/logs` üzerinden yerelden sorgulanıp indirilebilir. ERROR ve üstü her kayıt,
sebebine göre parmak izine dönüştürülür (mesajdaki sayı/kimlik atılır, `audit` olay türü + sebep verir);
aynı parmak izi tek `incidents` satırında sayılır. Hata kayıtları budanmaz, çözülse de geçmişiyle kalır.

Sağlamlık:
- Her kayıt yazılmadan önce `redact` ile anahtar/şifre benzeri değerlerden arındırılır.
- Yazım ayrı iş parçacığında, tek işlemde toplu yapılır; kuyruk sınırlıdır (taşan kayıt sayılır).
- Veritabanı hazır olana kadar kayıtlar bellekte bekler (`ready`); yazım başarısız olursa kayıtlar
  `SPOOL_DIR/applog-*.jsonl` dosyasına düşer ve veritabanı dönünce içeri alınır (`drain_spool`).
- Yakalanmamış istisnalar CRITICAL olarak loglanır; kapanışta kuyruk boşaltılır.
"""
import atexit
import hashlib
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config, db
from .models import AppLog, Incident

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
QUEUE_LIMIT = 10000
BATCH_SIZE = 200
FLUSH_SECONDS = 1.0
DRAIN_EVERY_SECONDS = 60.0
MASK = "[gizlendi]"
_guard = threading.local()
_writer = None

SECRET_PATTERNS = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer " + MASK),
    (re.compile(r"\bgsk_[A-Za-z0-9]{8,}"), MASK),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), MASK),
    (re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization)\b(\s*[=:]\s*)[^\s,;&\"']+"), r"\1\2" + MASK),
)


def secret_values():
    names = ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "API_KEY", "ADMIN_KEY", "LOG_KEY")
    return [v for v in (getattr(config, n, "") for n in names) if isinstance(v, str) and len(v) >= 8]


def redact(text):
    """Bilinen anahtar değerlerini ve anahtar/şifre desenlerini maskeler."""
    if not text:
        return text
    for value in secret_values():
        text = text.replace(value, MASK)
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def fingerprint(logger, message, key=None):
    first = key or ((message or "").splitlines()[0] if message else "")
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", first.lower())
    text = re.sub(r"\d+(\.\d+)?", "<n>", text)
    return hashlib.sha256(f"{logger}|{text}".encode("utf-8")).hexdigest()


def _history(incident, event, **data):
    items = json.loads(incident.history or "[]")
    items.append(dict(at=datetime.utcnow().isoformat() + "Z", event=event, **data))
    incident.history = json.dumps(items, ensure_ascii=False)


def make_entry(level, logger, message, traceback="", created_at=None, key=None, kind="error"):
    return dict(level=str(level).lower(), logger=logger or "", message=redact(message or "")[:8000],
                traceback=redact(traceback or "")[:20000], created_at=created_at or datetime.utcnow(),
                key=key, kind=kind, version=config.version_info().get("sha", ""))


def entry_from_record(record):
    message = record.getMessage()
    trace = record.exc_text or (logging.Formatter().formatException(record.exc_info) if record.exc_info else "")
    return make_entry(record.levelname, record.name, message, trace, datetime.utcfromtimestamp(record.created),
                      getattr(record, "fingerprint_key", None))


def store_batch(entries, session=None):
    """Kayıtları tek işlemde yazar; hata düzeyindekiler için hata kaydını açar/günceller/yeniden açar."""
    own = session is None
    session = session or db.SessionLocal(bind=db.engine)
    try:
        for entry in entries:
            incident_id = None
            if LEVELS.get(entry["level"], 0) >= LEVELS["error"]:
                fp = fingerprint(entry["logger"], entry["message"], entry.get("key"))
                incident = session.query(Incident).filter_by(fingerprint=fp).first()
                first_line = entry["message"].splitlines()[0][:150] if entry["message"] else "Hata"
                if incident is None:
                    incident = Incident(fingerprint=fp, level=entry["level"], logger=entry["logger"], count=0,
                                        kind=entry.get("kind", "error"),
                                        first_seen=entry["created_at"], first_version=entry["version"],
                                        title=f"[{entry['logger']}] {first_line}")
                    _history(incident, "opened", version=entry["version"])
                    session.add(incident)
                elif incident.status in ("resolved", "fix_deployed"):
                    reason = ("Düzeltme yayınlandıktan sonra tekrar görüldü (düzeltme yetmedi)." if incident.status == "fix_deployed"
                              else "Çözüldü olarak işaretlendikten sonra tekrar görüldü.")
                    incident.status = "open"
                    incident.reopen_count = (incident.reopen_count or 0) + 1
                    incident.resolved_at = None
                    incident.fix_deployed_at = None
                    _history(incident, "reopened", reason=reason, version=entry["version"])
                incident.count = (incident.count or 0) + 1
                incident.last_seen = entry["created_at"]
                incident.last_version = entry["version"]
                incident.sample = entry["message"][:4000]
                incident.traceback = (entry["traceback"] or incident.traceback or "")[:20000]
                session.flush()
                incident_id = incident.id
            session.add(AppLog(created_at=entry["created_at"], level=entry["level"], logger=entry["logger"][:80],
                               message=entry["message"], traceback=entry["traceback"], incident_id=incident_id,
                               version=entry["version"]))
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        if own:
            session.close()


def store(level, logger, message, traceback="", created_at=None, session=None, key=None):
    """Tek kaydı hemen yazar (testler, spool/dış kaynaklar); işlenmiş hata kaydı kimliğini döndürür."""
    entry = make_entry(level, logger, message, traceback, created_at, key)
    store_batch([entry], session)
    if LEVELS.get(entry["level"], 0) < LEVELS["error"]:
        return None
    own = session is None
    session = session or db.SessionLocal(bind=db.engine)
    try:
        row = session.query(Incident.id).filter_by(fingerprint=fingerprint(entry["logger"], entry["message"], key)).first()
        return row[0] if row else None
    finally:
        if own:
            session.close()


def spool_path():
    return Path(config.SPOOL_DIR)


def spool(entries):
    """Veritabanı yazılamıyorsa kayıtları dosyaya ekler."""
    folder = spool_path()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"applog-{datetime.utcnow():%Y%m%d}.jsonl"
    with target.open("a", encoding="utf-8") as file:
        for entry in entries:
            file.write(json.dumps(dict(entry, created_at=entry["created_at"].isoformat()), ensure_ascii=False) + "\n")


def drain_spool():
    """Spool dosyalarındaki log kayıtlarını veritabanına alır, dosyayı `done/` altına taşır. Alınan kayıt sayısı döner."""
    folder = spool_path()
    if not folder.is_dir():
        return 0
    total = 0
    for path in sorted(list(folder.glob("applog-*.jsonl")) + list(folder.glob("external-*.jsonl"))):
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                if path.name.startswith("external-"):
                    # Süreç dışı olay (deploy geri alma, yedek hatası, systemd): kabuk betikleri yazar.
                    source, title = str(raw["source"])[:40], str(raw["title"])[:150]
                    raw = make_entry(raw.get("level", "error"), f"linko.{source}", title + chr(10) + str(raw.get("message", "")),
                                     created_at=datetime.utcfromtimestamp(float(raw["at"])), key=f"external|{source}|{title}", kind="external")
                else:
                    raw["created_at"] = datetime.fromisoformat(raw["created_at"])
                entries.append(raw)
            except (ValueError, KeyError, TypeError):
                continue
        for start in range(0, len(entries), BATCH_SIZE):
            store_batch(entries[start:start + BATCH_SIZE])
        (folder / "done").mkdir(exist_ok=True)
        os.replace(path, folder / "done" / path.name)
        total += len(entries)
    return total


class Writer:
    """Kuyruktan toplu yazan iş parçacığı. `ready` verilene kadar bekler; kuyruk taşarsa kaydı düşürür ve sayar."""

    def __init__(self, limit=QUEUE_LIMIT):
        self.queue = queue.Queue(maxsize=limit)
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.stats = dict(written=0, spooled=0, dropped=0, last_error="")
        self.thread = threading.Thread(target=self.run, name="log-writer", daemon=True)

    def put(self, entry):
        try:
            self.queue.put_nowait(entry)
        except queue.Full:
            self.stats["dropped"] += 1

    def collect(self):
        batch = []
        try:
            batch.append(self.queue.get(timeout=FLUSH_SECONDS))
        except queue.Empty:
            return batch
        while len(batch) < BATCH_SIZE:
            try:
                batch.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return batch

    def write(self, batch):
        try:
            store_batch(batch)
            self.stats["written"] += len(batch)
        except Exception as exc:  # Log yazımı servisi durdurmamalı; kayıtlar dosyaya düşer.
            self.stats["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            try:
                spool(batch)
                self.stats["spooled"] += len(batch)
            except OSError:
                self.stats["dropped"] += len(batch)

    def run(self):
        while not self.ready.wait(0.5):
            if self.stopping.is_set():
                break
        last_drain = 0.0
        while True:
            batch = self.collect()
            if batch:
                self.write(batch)
            if time.monotonic() - last_drain >= DRAIN_EVERY_SECONDS and self.queue.empty():
                last_drain = time.monotonic()
                try:
                    drain_spool()
                except Exception as exc:
                    self.stats["last_error"] = f"drain: {type(exc).__name__}: {exc}"[:300]
            if self.stopping.is_set() and self.queue.empty():
                return


class QueueingHandler(logging.Handler):
    def __init__(self, writer):
        super().__init__()
        self.writer = writer

    def emit(self, record):
        if getattr(_guard, "active", False) or record.name == "linko.logstore":
            return
        _guard.active = True
        try:
            self.writer.put(entry_from_record(record))
        except Exception:
            self.writer.stats["dropped"] += 1
        finally:
            _guard.active = False


class DatabaseHandler(logging.Handler):
    """Senkron yazan yedek yol (testler); üretimde `install()` kuyruklu yazıcıyı kullanır."""

    def emit(self, record):
        if getattr(_guard, "active", False):
            return
        _guard.active = True
        try:
            store_batch([entry_from_record(record)])
        except Exception as exc:
            print(f"app_logs yazılamadı: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            _guard.active = False


def log_uncaught(exc_type, exc, tb, where="ana iş parçacığı"):
    logging.getLogger("linko").critical("Yakalanmamış istisna (%s): %s", where, exc, exc_info=(exc_type, exc, tb))


def install(level=logging.INFO):
    """Kök loga kuyruklu yazıcıyı ve istisna kancalarını ekler. `create_app()`'ten ÖNCE çağrılır; yazım `ready()` ile başlar."""
    global _writer
    if _writer:
        return _writer
    _writer = Writer()
    handler = QueueingHandler(_writer)
    handler.setLevel(level)
    logging.getLogger().addHandler(handler)
    _writer.thread.start()
    previous = sys.excepthook
    sys.excepthook = lambda t, e, tb: (log_uncaught(t, e, tb), previous(t, e, tb))
    threading.excepthook = lambda args: log_uncaught(args.exc_type, args.exc_value, args.exc_traceback,
                                                      args.thread.name if args.thread else "iş parçacığı")
    atexit.register(shutdown)
    return _writer


def ready():
    if _writer:
        _writer.ready.set()


def shutdown(timeout=10.0):
    if _writer and _writer.thread.is_alive():
        _writer.ready.set()
        _writer.stopping.set()
        _writer.thread.join(timeout)


def stats():
    if not _writer:
        return dict(active=False)
    return dict(_writer.stats, active=True, queued=_writer.queue.qsize(), version=config.version_info().get("sha"))


def report_external(session, source, title, message="", level="error", created_at=None, status=None, issue_number=None):
    """Süreç dışı kaynaktan (uptime, betikler) gelen olayı hata kaydı olarak işler; isteğe bağlı çözülmüş işaretler."""
    entry = make_entry(level, f"linko.{source}", title + chr(10) + message, created_at=created_at,
                       key=f"external|{source}|{title}", kind="external")
    store_batch([entry], session)
    incident = session.query(Incident).filter_by(fingerprint=fingerprint(entry["logger"], entry["message"], entry["key"])).one()
    if issue_number and incident.issue_number != issue_number:
        link_issue(incident, issue_number)
    if status == "resolved" and incident.status != "resolved":
        resolve(incident, f"{source} olayı sona erdi.", issue_number)
    session.commit()
    return incident


def problem_fingerprint(key):
    return fingerprint("linko.problem", None, key=f"problem|{key}")


def raise_problem(session, key, title, message):
    """Sorun kuralı tetiklendi: kayıt yoksa açar, çözülmüşse yeniden açar, açıksa yalnızca son görülmeyi günceller."""
    incident = session.query(Incident).filter_by(fingerprint=problem_fingerprint(key)).first()
    if incident is not None and incident.status == "open":
        incident.last_seen = datetime.utcnow()
        incident.last_version = config.version_info().get("sha", "")
        incident.sample = redact(title + chr(10) + message)[:4000]
        session.commit()
        return incident.id
    store_batch([make_entry("error", "linko.problem", title + chr(10) + message, key=f"problem|{key}", kind="problem")], session)
    return session.query(Incident.id).filter_by(fingerprint=problem_fingerprint(key)).scalar()


def clear_problem(session, key, resolution):
    """Koşul ortadan kalktı: kaydı çözüldü yapar; GitHub issue'su (varsa) senkron tarafından kapatılır."""
    incident = session.query(Incident).filter_by(fingerprint=problem_fingerprint(key)).first()
    if incident is not None and incident.status != "resolved":
        resolve(incident, resolution, issue_closed=False)
        session.commit()
        return True
    return False


def mark_fix_deployed(incident, commit, deployed_at=None, number=None):
    """Issue kapandı ve kapatan commit canlıda: 24 saat tekrar görülmezse çözüldü olacak."""
    incident.status = "fix_deployed"
    incident.issue_state = "closed"
    incident.fix_commit = (commit or "")[:40]
    incident.fix_deployed_at = datetime.utcfromtimestamp(deployed_at) if deployed_at else datetime.utcnow()
    _history(incident, "fix_deployed", issue=number or incident.issue_number, commit=incident.fix_commit)


def reopen_by_issue(incident):
    """Issue GitHub'da elle yeniden açıldı: kayıt açık duruma döner, geçmişe işlenir."""
    incident.status = "open"
    incident.issue_state = "open"
    incident.resolved_at = None
    incident.fix_deployed_at = None
    incident.reopen_count = (incident.reopen_count or 0) + 1
    _history(incident, "issue_reopened", issue=incident.issue_number, reason="Issue elle yeniden açıldı.")


def link_issue(incident, number):
    incident.issue_number = number
    incident.issue_state = "open"
    _history(incident, "issue_linked", issue=number)


def resolve(incident, resolution="", number=None, issue_closed=True):
    """`issue_closed=False`: sunucu tarafında çözüldü (koşul kalktı); issue açık kalır, senkron kapatır."""
    incident.status = "resolved"
    if issue_closed:
        incident.issue_state = "closed"
    incident.resolved_at = datetime.utcnow()
    incident.resolution = resolution or "Çözüldü."
    _history(incident, "resolved", issue=number or incident.issue_number, resolution=incident.resolution)


def serialize(incident, full=False):
    data = dict(id=incident.id, fingerprint=incident.fingerprint, level=incident.level, logger=incident.logger,
                title=incident.title, kind=incident.kind or "error", count=incident.count, status=incident.status,
                issue_number=incident.issue_number,
                issue_state=incident.issue_state or "", reopen_count=incident.reopen_count or 0,
                first_seen=incident.first_seen.isoformat() + "Z" if incident.first_seen else None,
                last_seen=incident.last_seen.isoformat() + "Z" if incident.last_seen else None,
                first_version=incident.first_version or "", last_version=incident.last_version or "",
                fix_commit=incident.fix_commit or "",
                fix_deployed_at=incident.fix_deployed_at.isoformat() + "Z" if incident.fix_deployed_at else None,
                resolved_at=incident.resolved_at.isoformat() + "Z" if incident.resolved_at else None,
                resolution=incident.resolution or "", sample=incident.sample or "")
    if full:
        data.update(traceback=incident.traceback or "", history=json.loads(incident.history or "[]"))
    return data
