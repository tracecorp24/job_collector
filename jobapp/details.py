"""Önce kart, detay sonra: taramada açıklaması istenmeyen ilanların detayını arka planda tamamlar.

Tarama sayfasındaki ilanlar tek istekle listeye düşer (`detail_pending`). Bu iş parçacığı, tarama
çalışmıyorken ve kaynak duraklatılmamışken en yeni bekleyen ilanın detayını çeker. İstekler
kazıyıcının `_get` yolundan geçer: ortak istek sırası, rastgele aralık, 429 duraklatması ve güvenlik
kontrolü tespiti aynen uygulanır. Tarama başlarsa bekleyen istek bırakılır; tarama önceliklidir.
"""
import json
import logging
import threading
import time
from sqlalchemy import text
from . import config
from .models import Job, SearchRun
from .transport import Coordinator, SourcePaused, fingerprint

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
DESCRIPTION_SELECTOR = ".show-more-less-html__markup, .description__text"
PENDING = "deleted_at IS NULL AND json_extract(raw, '$.detail_pending') = 1"
worker = None


def pending_ids(session, limit=1):
    return [row[0] for row in session.execute(
        text(f"SELECT id FROM jobs WHERE {PENDING} ORDER BY created_at DESC, id DESC LIMIT :n"), {"n": limit})]


def pending_count(session):
    return session.execute(text(f"SELECT COUNT(*) FROM jobs WHERE {PENDING}")).scalar()


def _backend(session, raw):
    run = session.get(SearchRun, raw.get("run_id")) if raw.get("run_id") else None
    try:
        return json.loads(run.options or "{}").get("classify_backend", "rules") if run else "rules"
    except ValueError:
        return "rules"


def fill_one(server, scraper):
    """En yeni bekleyen ilanın detayını çeker. Bir ilan işlendiyse True döner."""
    if server.state.running or Coordinator().state()["paused"]:
        return False
    with server.SessionLocal() as session:
        ids = pending_ids(session)
        if not ids:
            return False
        job_id = ids[0]
        requested_raw = json.loads(session.get(Job, job_id).raw or "{}")
        url = requested_raw.get("url")
    scraper.last_status = None
    cached = scraper.details.get(requested_raw)
    try:
        detail = scraper._get(url) if url and cached is None else None
    except SourcePaused:
        return False
    except Exception as exc:  # ağ/kaynak hatası: deneme sayılır, sonsuz döngüye girmez
        log.warning("İlan %s detayı alınamadı: %s", job_id, exc)
        detail = None
    if detail is None and cached is None and server.state.running:
        return False  # tarama başladığı için istek bırakıldı; deneme sayılmaz
    box = detail.select_one(DESCRIPTION_SELECTOR) if detail is not None else None
    description = cached["description"] if cached and cached["status"] == 200 else (
        box.get_text("\n", strip=True) if box is not None else "")
    with server.SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            return True
        raw = json.loads(job.raw or "{}")
        if job.deleted_at or not raw.get("detail_pending") or fingerprint(raw) != fingerprint(requested_raw):
            return True  # a newer scan/delete owns the row; don't overwrite it
        if description:
            cached = cached or scraper.details.put(requested_raw, description)
            raw.update(description=cached["description"], detail_fetched_at=cached["fetched_at"])
            raw.pop("detail_pending", None)
            raw.pop("detail_attempts", None)
            from .pipeline import process_raw
            process_raw(session, raw, classify_backend=_backend(session, raw))
            log.info("Detay tamamlandı: #%s %s (%s)", job_id, job.title, job.company)
        elif (cached and cached["status"] in (404, 410)) or scraper.last_status in (404, 410):
            if cached is None:
                scraper.details.put(requested_raw, "", scraper.last_status)
            raw.pop("detail_pending", None)
            raw["detail_missing"] = True
            job.raw = json.dumps(raw, ensure_ascii=False)
            log.info("İlan #%s kaynakta kaldırılmış (HTTP %s); detay beklemesi kapatıldı.", job_id, scraper.last_status)
        else:
            raw["detail_attempts"] = raw.get("detail_attempts", 0) + 1
            if raw["detail_attempts"] >= MAX_ATTEMPTS:
                raw.pop("detail_pending", None)
                raw["detail_failed"] = True
                log.warning("İlan #%s detayı %s denemede alınamadı; bekleyenlerden çıkarıldı.", job_id, MAX_ATTEMPTS)
            job.raw = json.dumps(raw, ensure_ascii=False)
        session.commit()
    return True


def start(server):
    global worker
    if worker and worker.is_alive():
        return

    def loop():
        from .scraper.accountless import AccountlessScraper
        scraper = None
        while True:
            busy = False
            try:
                scraper = scraper or AccountlessScraper(should_stop=lambda: server.state.running)
                busy = fill_one(server, scraper)
            except Exception:
                log.exception("Detay tamamlayıcı hata verdi; yeniden denenecek")
            time.sleep(1 if busy else config.SERVICE_POLL_SECONDS)

    worker = threading.Thread(target=loop, name="detail-filler", daemon=True)
    worker.start()
