"""One persisted, AI-written summary per day of completed searches."""
import json
import logging
import threading
import time
from datetime import datetime, timedelta

from . import audit, config, groq_client, query_insights
from .models import SearchRun, SearchTask, Setting

log = logging.getLogger("linko.daily_summary")
KEY = "daily_search_summary_latest"
INTERVAL_SECONDS = 24 * 60 * 60
_lock = threading.Lock()
_running = False
_last_check = 0.0


def _timestamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError, AttributeError):
        return None


def _fallback(searches, total_new):
    lines = [f"Son rapordan beri {len(searches)} arama tamamlandı ve {total_new} yeni ilan kaydedildi."]
    comparisons = [s["efficiency"].get("bilingual_comparison") for s in searches if s.get("efficiency", {}).get("bilingual_comparison")]
    for row in comparisons[:3]:
        result = row["result"]
        message = "İki dildeki aramalar benzer yeni ilan verimi gösterdi." if result == "berabere" else f"Bu karşılaştırmada {result} dilindeki arama daha çok yeni ilan getirdi."
        lines.append(f"{row['profession_group']} · {row['location']}: {message} {row['note']}")
    weak = [s for s in searches if s["efficiency"].get("inefficiency_reasons")]
    for row in weak[:3]:
        lines.append(f"{row['keyword']} · {row['location']}: {', '.join(row['efficiency']['inefficiency_reasons'])}.")
    return " ".join(lines)


def _generate(server, searches, window_start, window_end):
    global _running
    try:
        total_new = sum(s["metrics"].get("new_jobs", 0) or 0 for s in searches)
        total_cards = sum(s["efficiency"].get("unique_cards") or 0 for s in searches)
        comparisons = [s["efficiency"]["bilingual_comparison"] for s in searches
                       if s["efficiency"].get("bilingual_comparison")]
        grouped = {}
        for search in searches:
            efficiency = search["efficiency"]
            key = (efficiency.get("profession_code"), efficiency.get("location_key"))
            if efficiency.get("profession_code") == "other":
                continue
            pair = grouped.setdefault(key, {"profession_group": efficiency.get("profession_group"),
                                            "location": search["location"], "languages": {}})
            language = efficiency.get("keyword_language", "other")
            stats = pair["languages"].setdefault(language, {"searches": 0, "new_jobs": 0, "unique_cards": 0})
            stats["searches"] += 1
            stats["new_jobs"] += efficiency.get("new_jobs", 0)
            stats["unique_cards"] += efficiency.get("unique_cards") or 0
        pairs = []
        for item in grouped.values():
            if "tr" in item["languages"] and "en" in item["languages"]:
                for value in item["languages"].values():
                    value["new_yield_pct"] = round(100 * value["new_jobs"] / value["unique_cards"], 1) if value["unique_cards"] else 0
                pairs.append(item)

        summary = _fallback(searches, total_new)
        source = "metrics"
        if config.GROQ_API_KEY:
            evidence = [{"search": s["keyword"], "location": s["location"],
                         "language": s["efficiency"].get("keyword_language"),
                         "profession": s["efficiency"].get("profession_group"),
                         "new_jobs": s["efficiency"].get("new_jobs", 0),
                         "new_yield_pct": s["efficiency"].get("new_yield_pct", 0),
                         "inefficiencies": s["efficiency"].get("inefficiency_reasons", [])}
                        for s in searches[:60]]
            try:
                response = groq_client.chat_json([
                    {"role": "system", "content": (
                        "Türkçe çalışan genel bir iş ilanı toplayıcısı için kısa günlük rapor yaz. "
                        "Yalnızca girdideki sayıları ve bulguları kullan; gözlem ile yorumu ayır. "
                        "Türkçe ve İngilizce aramaları aynı meslek ve konum grubunda kıyasla. "
                        "Örnek sayısı azsa sonucu kesinleştirme. İlanların gerçek iş ilanı veya dolandırıcılık olduğuna dair "
                        "ölçülmemiş iddialarda bulunma. En fazla 120 kelimelik tek bir summary metnini JSON olarak döndür: "
                        '{"summary":"..."}.'
                    )},
                    {"role": "user", "content": json.dumps({"search_count": len(searches), "new_jobs": total_new,
                                                               "unique_cards": total_cards, "language_pairs": pairs,
                                                               "searches": evidence}, ensure_ascii=False)},
                ], max_tokens=300, max_wait=12)
                if isinstance(response.get("summary"), str) and response["summary"].strip():
                    summary = response["summary"].strip()[:1600]
                    source = "groq"
            except groq_client.GroqError as error:
                log.info("Günlük arama özeti ölçüm tabanlı olarak hazırlandı: %s", error)

        report = {"available": True, "generated_at": datetime.utcnow().isoformat() + "Z",
                  "window_start": window_start.isoformat() + "Z", "window_end": window_end.isoformat() + "Z",
                  "search_count": len(searches), "new_jobs": total_new, "unique_cards": total_cards,
                  "summary_source": source, "summary": summary, "language_pairs": pairs, "searches": searches}
        with server.SessionLocal() as session:
            saved = session.get(Setting, KEY)
            if saved is None:
                saved = Setting(key=KEY)
                session.add(saved)
            saved.value = json.dumps(report, ensure_ascii=False)
            session.commit()
    except Exception:
        log.exception("Günlük arama özeti kaydedilemedi; sonraki denetimde yeniden denenecek.")
    finally:
        with _lock:
            _running = False


def dispatch(server, now=None):
    """Called by the supervisor; one background job is started at most once a day."""
    global _running, _last_check
    now = time.time() if now is None else now
    with _lock:
        if _running or now - _last_check < 60:
            return False
        _last_check = now
    now_dt = datetime.utcfromtimestamp(now)
    try:
        with server.SessionLocal() as session:
            saved = session.get(Setting, KEY)
            previous = None
            if saved:
                try:
                    previous = json.loads(saved.value or "{}")
                except (ValueError, TypeError):
                    previous = None
            last_generated = _timestamp(previous.get("generated_at")) if previous else None
            if last_generated and (now_dt - last_generated).total_seconds() < INTERVAL_SECONDS:
                return False
            window_start = _timestamp(previous.get("window_end")) if previous else None
            window_start = window_start or now_dt - timedelta(days=1)
            candidates = (session.query(SearchTask, SearchRun)
                          .join(SearchRun, SearchTask.run_id == SearchRun.id)
                          .filter(SearchTask.ended_at > window_start,
                                  SearchTask.status.in_(("finished", "stopped", "error")),
                                  SearchRun.deleted_at.is_(None))
                          .order_by(SearchTask.ended_at, SearchTask.id).limit(60).all())
            searches = []
            for task, run in candidates:
                try:
                    if json.loads(run.options or "{}").get("kind", "scrape") != "scrape":
                        continue
                    report = audit.report(session, run.id, task.id)
                    metrics = report["metrics"]
                    metrics["http_statuses"] = report["http_statuses"]
                    stored = json.loads(task.stats or "{}").get("search_efficiency")
                    efficiency = stored or query_insights.annotate(session, task, metrics, compare=False)
                    searches.append({"run_id": run.id, "search_id": task.id,
                                     "keyword": task.keyword, "location": task.location,
                                     "status": task.status, "metrics": metrics, "efficiency": efficiency,
                                     "ended_at": task.ended_at.isoformat() + "Z" if task.ended_at else None})
                except Exception:
                    log.exception("Günlük raporda arama ölçümleri okunamadı: %s", task.id)
            if not searches:
                return False
            _running = True
        thread = threading.Thread(target=_generate, args=(server, searches, window_start, now_dt),
                                  name="daily-search-summary", daemon=True)
        thread.start()
        return True
    except Exception:
        log.exception("Günlük arama özeti denetimi başarısız oldu.")
        return False
