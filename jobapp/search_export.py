"""Separate search folders containing the frontend's one-job-per-JSON format."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config, skills


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_json(path, value):
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _slug(text):
    # Prefix below also avoids Windows reserved names; length leaves path room.
    return re.sub(r"[^\w-]+", "_", text, flags=re.UNICODE).strip("_ .")[:40] or "default"


class SearchExport:
    def __init__(self, root=None):
        self.root = Path(root or config.ACCOUNTLESS_OUTPUT_DIR)
        self.current = None
        self.folders = []
        self.ids = set()
        self.skills = skills

    def resume(self, folder):
        target = (self.root / folder).resolve()
        if not target.is_relative_to(self.root.resolve()) or not (target / "search.json").exists():
            raise ValueError("Devam edilecek arama havuzu bulunamadı.")
        self.current = target
        self.folders.append(str(target))
        self.metadata = json.loads((target / "search.json").read_text(encoding="utf-8"))
        self.ids = {p.stem for p in (target / "ilan_havuzu").glob("*.json")}
        self.metadata.update(status="running")
        for key in ("finishedAt", "error", "pauseReason", "terminationReason", "terminationMessage"):
            self.metadata.pop(key, None)
        _write_json(target / "search.json", self.metadata)
        return str(target)

    def begin(self, title, location, limit=None):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        folder = self.root / f"search_{_slug(title)}__{_slug(location)}__{stamp}_{uuid.uuid4().hex[:8]}"
        (folder / "ilan_havuzu").mkdir(parents=True, exist_ok=False)
        self.current = folder
        self.folders.append(str(folder.resolve()))
        self.ids = set()
        self.metadata = {
            "title": title,
            "location": location,
            "limit": limit,
            "startedAt": _now(),
            "status": "running",
            "count": 0,
            "format": "frontend/ilan_havuzu",
        }
        _write_json(folder / "search.json", self.metadata)
        self._init_log(folder / "search.log", title, location, limit)
        return self.folders[-1]

    def _init_log(self, log_path, title, location, limit):
        try:
            target_str = f"{limit} ilan" if limit else "Limitsiz"
            header = (
                "=" * 70 + "\n"
                f"LINKEDIN PUBLIC ARAMA DETAY LOGU\n"
                f"Başlık     : {title}\n"
                f"Konum      : {location or 'Varsayılan'}\n"
                f"Hedef Limit: {target_str}\n"
                f"Başlangıç  : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                "=" * 70 + "\n\n"
            )
            log_path.write_text(header, encoding="utf-8")
        except Exception:
            pass

    def log(self, msg, level="info"):
        """Append a timestamped log line to the current search's search.log file."""
        if not self.current:
            return
        try:
            log_file = self.current / "search.log"
            stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
            level_str = (level or "info").upper()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{stamp} UTC] [{level_str:7s}] {msg}\n")
        except Exception:
            pass

    def event(self, kind, data):
        from .audit import clean
        if self.current:
            with (self.current / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"ts": _now(), "kind": kind, "data": clean(data)}, ensure_ascii=False) + "\n")

    def save(self, raw):
        if self.current is None:
            raise RuntimeError("Search export folder has not been created.")
        lines = raw.get("card_lines") or []
        title, company, location = (lines + ["", "", ""])[:3]
        description = raw.get("description", "")
        if not title.strip() or not company.strip():
            return False  # frontend requires both fields
        text = f"{title}\n{location}\n{description}"
        experience = self.skills.extract_experience_years(description, title) if self.skills else None
        job_id = f"ap-linkedin-{raw['external_id']}"
        job = {
            "id": job_id, "title": title, "company": company, "location": location,
            "type": (self.skills.extract_work_type(text) if self.skills else None) or "Office",
            "source": "LinkedIn", "salary": None, "desc": description,
            "skills": self.skills.extract_skills(title, description) if self.skills else [],
            "applyUrl": raw.get("url") or None, "posted": raw.get("posted") or "Bilinmiyor",
            "experience": f"{experience}+ yıl" if experience is not None else "Belirtilmemiş",
            "_collector": {
                "searchId": raw.get("search_id"), "runId": raw.get("run_id"),
                "requestedCity": raw.get("search_location", ""),
                "requestedTitle": raw.get("search_term", ""),
                "requestedCities": [raw.get("search_location", "")],
                "requestedTitles": [raw.get("search_term", "")],
                "sourceJobId": raw["external_id"], "descriptionAvailable": bool(description),
                "collectedAt": _now(), "mode": "accountless",
            },
        }
        _write_json(self.current / "ilan_havuzu" / f"{job_id}.json", job)
        self.ids.add(job_id)
        self.metadata["count"] = len(self.ids)
        _write_json(self.current / "search.json", self.metadata)
        return True

    def finish(self, status, error=None, reason=None, stats=None):
        if self.current is None:
            return
        finished_at = _now()
        started_at = self.metadata.get("startedAt")
        duration = None
        if started_at:
            try:
                t0 = datetime.fromisoformat(started_at)
                t1 = datetime.fromisoformat(finished_at)
                duration = round((t1 - t0).total_seconds(), 2)
            except Exception:
                pass

        reason_messages = {
            "repeated_page": "Kaynak aynı ilanları tekrar döndürdü; yeni ilan içermeyen sayfada tarama durdu.",
            "exhausted_results": "LinkedIn'de bu arama kriterine uyan tüm kamuya açık ilanlar başarıyla toplandı (sayfalamada yeni ilan kalmadı).",
            "reached_limit": "Belirlenen hedef ilan adedine ulaşıldı ve arama tamamlandı.",
            "stopped_by_user": "Arama kullanıcı tarafından durduruldu.",
            "rate_limit_abort": "LinkedIn hız sınırı aşıldı ve maksimum deneme sayısına ulaşıldı.",
            "error": "Arama sırasında bir hata oluştu.",
            "source_paused": "Kaynak erişimi veya bekleme talebi nedeniyle tarama duraklatıldı. Aynı süreçten devam edilebilir.",
            "page_fetch_failed": "Sayfa verisi LinkedIn'den çekilemedi.",
        }

        self.metadata.update(
            status=status,
            finishedAt=finished_at,
            durationSeconds=duration,
        )
        if reason:
            self.metadata["terminationReason"] = reason
            self.metadata["terminationMessage"] = reason_messages.get(reason, reason)
        elif status == "finished":
            self.metadata["terminationReason"] = "exhausted_results"
            self.metadata["terminationMessage"] = reason_messages["exhausted_results"]

        if stats:
            self.metadata["stats"] = stats
        if error and status == "paused":
            self.metadata["pauseReason"] = error
        elif error:
            self.metadata["error"] = error
            self.metadata["terminationReason"] = "error"
            self.metadata["terminationMessage"] = f"Hata: {error}"

        _write_json(self.current / "search.json", self.metadata)

        # Write final finish banner to search.log
        try:
            log_file = self.current / "search.log"
            reason_txt = self.metadata.get("terminationMessage", reason or status)
            summary_banner = (
                "\n" + "-" * 70 + "\n"
                f"ARAMA TAMAMLANDI\n"
                f"Durum       : {status}\n"
                f"Bitiş Nedeni: {reason_txt}\n"
                f"Toplam İlan : {len(self.ids)}\n"
                f"Geçen Süre  : {duration or 0} saniye\n"
            )
            if stats:
                summary_banner += (
                    f"İstatistik  : Taranan Sayfa: {stats.get('pagesScanned', 1)} | "
                    f"Görülen Kart: {stats.get('totalCardsSeen', len(self.ids))} | "
                    f"Mükerrer Elenen: {stats.get('duplicatesSkipped', 0)}\n"
                )
            summary_banner += "=" * 70 + "\n"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(summary_banner)
        except Exception:
            pass

        self.current = None
