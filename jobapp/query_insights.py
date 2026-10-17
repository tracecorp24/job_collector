"""Persist and compare per-search yield metrics, including bilingual variants."""
import json
from datetime import datetime, timedelta

from . import audit, professions
from .models import SearchTask


def efficiency(metrics):
    returned = metrics.get("unique_returned_ids")
    if returned is None:
        returned = metrics.get("returned_cards", 0)
    new_count = int(metrics.get("new_jobs", 0) or 0)
    percent = round(100 * new_count / returned, 1) if returned else 0.0
    cards = int(metrics.get("returned_cards", 0) or 0)
    duplicates = int(metrics.get("duplicates", 0) or 0)
    failures = int(metrics.get("detail_failures", 0) or 0)
    collected = int(metrics.get("collected", 0) or 0)
    reasons = []
    if not cards:
        reasons.append("Sonuç kartı dönmedi")
    if metrics.get("found_jobs", 0) and not new_count:
        reasons.append("Bulunan ilanların tamamı havuzda zaten vardı")
    if cards and duplicates / cards >= 0.35:
        reasons.append("Sonuçların önemli bölümü tekrarlandı")
    if failures and failures / max(1, failures + collected) >= 0.15:
        reasons.append("İlan detaylarının kayda değer bölümü alınamadı")
    if metrics.get("termination_reason") == "page_fetch_failed":
        reasons.append("Arama sayfası alınamadı")
    statuses = metrics.get("http_statuses") or {}
    if any(statuses.get(code, 0) for code in ("401", "403", "429", "999")):
        reasons.append("Kaynak erişim veya hız sınırı uyguladı")
    if metrics.get("source_pauses"):
        reasons.append("Kaynak koruması taramayı duraklattı")
    elif metrics.get("retry_waits"):
        reasons.append("Geçici hata veya hız sınırı nedeniyle bekleme oluştu")
    if (metrics.get("termination_reason") in ("exhausted_results", "repeated_page", "no_new_jobs")
            and new_count == 0 and cards):
        reasons.append("Arama sayfaları yeni ilan getirmeden tükendi")
    return {"cards": cards, "unique_cards": returned, "new_jobs": new_count,
            "existing_jobs": max(0, int(metrics.get("found_jobs", 0) or 0) - new_count),
            "duplicates": duplicates, "detail_failures": failures,
            "new_yield_pct": percent, "inefficiency_reasons": reasons}


def annotate(session, task, metrics=None, compare=True):
    """Store an evidence-based efficiency snapshot on a completed search task."""
    meta = professions.query_metadata(task.keyword, task.location)
    task.keyword_language = meta["keyword_language"]
    task.profession_group = meta["profession_group"]
    task.profession_code = meta["profession_code"]
    task.location_key = meta["location_key"]
    if metrics is None:
        report = audit.report(session, task.run_id, task.id)
        metrics = report["metrics"]
        metrics["http_statuses"] = report["http_statuses"]
    try:
        metrics["termination_reason"] = json.loads(task.stats or "{}").get("termination_reason")
    except (ValueError, TypeError):
        metrics["termination_reason"] = None
    result = {"keyword": task.keyword, "location": task.location, **meta,
              **efficiency(metrics), "sample_count": 1, "language_comparisons": []}

    if compare and task.profession_code != "other" and task.ended_at:
        since = task.ended_at - timedelta(days=30)
        peers = (session.query(SearchTask)
                 .filter(SearchTask.id != task.id, SearchTask.profession_code == task.profession_code,
                         SearchTask.location_key == task.location_key,
                         SearchTask.ended_at >= since, SearchTask.ended_at < task.ended_at,
                         SearchTask.status == "finished")
                 .order_by(SearchTask.ended_at.desc()).limit(100).all())
        cohorts = {}
        for peer in peers:
            try:
                saved = json.loads(peer.stats or "{}").get("search_efficiency")
            except (ValueError, TypeError):
                saved = None
            if not saved:
                continue
            cohort = cohorts.setdefault(peer.keyword_language or "other", {"searches": 0, "new_jobs": 0, "unique_cards": 0})
            cohort["searches"] += 1
            cohort["new_jobs"] += int(saved.get("new_jobs", 0))
            cohort["unique_cards"] += int(saved.get("unique_cards") or saved.get("cards") or 0)

        current = cohorts.setdefault(task.keyword_language or "other", {"searches": 0, "new_jobs": 0, "unique_cards": 0})
        current["searches"] += 1
        current["new_jobs"] += result["new_jobs"]
        current["unique_cards"] += int(result["unique_cards"] or result["cards"] or 0)
        for language, cohort in sorted(cohorts.items()):
            if cohort["searches"] < 1:
                continue
            cohort["new_yield_pct"] = round(100 * cohort["new_jobs"] / cohort["unique_cards"], 1) if cohort["unique_cards"] else 0
            cohort["is_current_language"] = language == task.keyword_language
            cohort["evidence"] = "sınırlı" if cohort["searches"] < 3 else "tekrarlı"
            result["language_comparisons"].append({"language": language, **cohort})

        counterpart = {"tr": "en", "en": "tr"}.get(task.keyword_language)
        other_language = next((cohort for cohort in result["language_comparisons"]
                               if cohort["language"] == counterpart), None)
        if other_language:
            own = next(cohort for cohort in result["language_comparisons"] if cohort["is_current_language"])
            if own["new_yield_pct"] > other_language["new_yield_pct"]:
                winner = task.keyword_language
            elif own["new_yield_pct"] < other_language["new_yield_pct"]:
                winner = other_language["language"]
            else:
                winner = "berabere"
            result["bilingual_comparison"] = {
                "profession_code": task.profession_code,
                "profession_group": task.profession_group,
                "location": task.location,
                "result": winner,
                "note": "Karşılaştırma son 30 günde aynı meslek ve konumdaki tamamlanan aramalara dayanır.",
            }

    return result


def persist(session, task):
    result = annotate(session, task, compare=task.status == "finished")
    stats = json.loads(task.stats or "{}")
    stats["search_efficiency"] = result
    task.stats = json.dumps(stats, ensure_ascii=False)
    audit.record(session, task.run_id, task.id, "search_efficiency", result)
    return result
