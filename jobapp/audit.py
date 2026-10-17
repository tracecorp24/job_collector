"""Correlated process audit and evidence-based explanations of collection losses."""
import json
import logging
from collections import Counter
from datetime import datetime
from sqlalchemy import func
from . import config
from .models import SearchEvent, SearchRun, SearchTask, TaskJob, Job

VERSION = "audit.v1"
log = logging.getLogger("linko.audit")
# Uyarı/hatalar her zaman, bu olaylar bilgi düzeyinde sunucu loguna da yazılır; istek başı olaylar yalnızca DB'de kalır.
LOGGED = {"run_created", "run_started", "run_completed", "watch_run_created", "scheduled_run_created",
          "automatic_resume", "automatic_retry_scheduled", "process_recovered", "source_acknowledged", "schedule_disabled"}
SUMMARY = ("name", "keyword", "location", "status", "reason", "msg", "seconds", "remaining_seconds", "status_code",
           "retry_at", "attempt", "previous_status", "new", "updated")
SENSITIVE = {"authorization", "cookie", "set-cookie", "password", "api_key", "token", "secret"}


def clean(value):
    if isinstance(value, dict):
        return {str(k): "[gizlendi]" if str(k).lower() in SENSITIVE else clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, str):
        secret = config.ANTHROPIC_API_KEY
        return value.replace(secret, "[gizlendi]") if secret else value
    return value


def record(session, run_id, task_id, kind, data=None, level="info"):
    data = clean(dict(data or {}, run_id=run_id, search_id=task_id, audit_version=VERSION))
    event = SearchEvent(run_id=run_id, task_id=task_id, kind=kind, level=level, data=json.dumps(data, ensure_ascii=False))
    session.add(event)
    if level in ("warning", "error") or kind in LOGGED:
        summary = " ".join(f"{k}={str(data[k])[:120]}" for k in SUMMARY if data.get(k) not in (None, ""))
        # Parmak izi olay türü + sebepten üretilir; unvan/konum/kimlik aynı hatayı bölmesin.
        key = f"{kind}|{data.get('error_type') or data.get('reason') or data.get('msg') or ''}"[:160]
        log.log(logging.ERROR if level == "error" else logging.WARNING if level == "warning" else logging.INFO,
                "%s run=%s task=%s %s", kind, (run_id or "-")[:8], (task_id or "-")[:8], summary,
                extra={"fingerprint_key": key})
    return event


def report(session, run_id, task_id=None):
    run = session.get(SearchRun, run_id)
    if not run:
        raise ValueError("Süreç bulunamadı.")
    tasks = session.query(SearchTask).filter_by(run_id=run_id)
    if task_id:
        tasks = tasks.filter_by(id=task_id)
    tasks = tasks.order_by(SearchTask.position).all()
    if task_id and not tasks:
        raise ValueError("Görev bu sürece ait değil.")
    ids = [t.id for t in tasks]
    events = session.query(SearchEvent).filter_by(run_id=run_id)
    if task_id:
        events = events.filter_by(task_id=task_id)
    events = events.order_by(SearchEvent.id).yield_per(500)
    metrics = dict(requests=0, search_requests=0, detail_requests=0, returned_cards=0, collected=0,
                   duplicates=0, detail_failures=0, invalid_cards=0, not_processed=0,
                   processing_failures=0, quality_rejections=0, model_fallbacks=0, retry_waits=0, wait_seconds=0,
                   cache_hits=0, cache_misses=0, source_pauses=0)
    statuses = Counter()
    returned_ids, collected_ids, failed_ids = set(), set(), set()
    reasons, timeline, last_error = {}, [], None
    has_pages = False
    for event in events:
        data = json.loads(event.data)
        if event.kind in ("cache_hit", "cache_miss"):
            metrics["cache_hits" if event.kind == "cache_hit" else "cache_misses"] += 1
        elif event.kind == "source_paused":
            metrics["source_pauses"] += 1
        elif event.kind == "request_finished":
            metrics["requests"] += 1
            metrics["search_requests" if data.get("params") else "detail_requests"] += 1
            statuses[str(data.get("status") or "network_error")] += 1
        elif event.kind == "page_result":
            has_pages = True
            for key in ("collected", "duplicates", "detail_failures", "invalid_cards", "not_processed"):
                metrics[key] += data.get(key, 0)
            metrics["returned_cards"] += data.get("cards_returned", 0)
            returned_ids.update(data.get("returned_ids", []))
            collected_ids.update(data.get("collected_ids", []))
            failed_ids.update(data.get("failed_ids", []))
        elif event.kind == "job_skipped":
            metrics["quality_rejections" if data.get("reason") == "quality_rejected" else "processing_failures"] += 1
        elif event.kind == "processing_result":
            metrics["model_fallbacks"] += bool(data.get("classification_fallback"))
            if data.get("status") == "failed":
                metrics["processing_failures"] += 1
        elif event.kind == "waiting":
            metrics["retry_waits"] += 1
            metrics["wait_seconds"] += data.get("seconds", 0)
        elif event.kind == "task_done" and data.get("reason"):
            reasons[event.task_id] = data["reason"]
        if event.kind in ("run_created", "task_queued", "run_started", "user_action", "task_start", "task_done", "finished", "error", "source_paused", "process_recovered", "run_completed"):
            timeline.append({"event_id": event.id, "search_id": event.task_id, "kind": event.kind,
                             "at": event.created_at.isoformat() + "Z", "data": data})
        if event.kind == "error":
            last_error = data
    links = session.query(TaskJob).filter(TaskJob.task_id.in_(ids))
    linked = session.query(Job).join(TaskJob, TaskJob.job_id == Job.id).filter(TaskJob.task_id.in_(ids)).distinct()
    metrics.update(found_jobs=linked.count(), new_jobs=links.filter(TaskJob.is_new.is_(True)).count(),
                   updated_jobs=links.filter(TaskJob.is_new.is_(False), TaskJob.outcome != "unchanged").count(),
                   unchanged_jobs=links.filter(TaskJob.outcome == "unchanged").count(),
                   visible_jobs=linked.filter(Job.quality_ok.is_(True), Job.deleted_at.is_(None)).count(),
                   deleted_jobs=linked.filter(Job.deleted_at.isnot(None)).count(),
                   invalid_jobs=linked.filter(Job.quality_ok.is_(False), Job.deleted_at.is_(None)).count(),
                   unique_returned_ids=len(returned_ids) if returned_ids else None,
                   unique_collected_ids=len(collected_ids) if collected_ids else None)
    findings = []
    def finding(code, title, evidence, steps, severity="info"):
        findings.append(dict(code=code, title=title, evidence=evidence, next_steps=steps, severity=severity))
    kind = json.loads(run.options).get("kind", "scrape")
    if metrics["source_pauses"]:
        finding("source_paused", "Kaynak koruması taramayı otomatik duraklattı.", metrics["source_pauses"],
                ["Kaynak durumundaki bekleme süresinin dolmasını bekleyin.", "Güvenlik kontrolünde erişimi kontrol edip duraklatmayı kaldırın; ardından aynı süreçten devam edin."], "warning")
    if metrics["cache_hits"]:
        finding("cache", "Geçerli önbellekteki detaylar yeniden indirilmedi.", metrics["cache_hits"],
                ["Önbellek 24 saat geçerlidir; süresi dolan veya kart bilgisi değişen ilanlar yeniden alınır."])
    if not has_pages and kind == "scrape":
        finding("limited_history", "Bu süreç için ayrıntılı sayfa geçmişi bulunmuyor.",
                "Eski süreçlerin bilinmeyen istek sayıları ve yanıtları sonradan tahmin edilmez.",
                ["Kaynak metin logunu inceleyin.", "Yeni taramalar bütün istek ve sayfa ayrıntılarını kaydeder."], "warning")
        metrics["collected"] = sum(json.loads(t.checkpoint).get("collected", 0) for t in tasks)
    if any(statuses[k] for k in ("401", "403", "429", "999")):
        finding("rate_limit", "Kaynak erişim veya hız sınırı uyguladı.", dict(statuses),
                ["Retry-After ve bekleme sürelerine uyun.", "Kaynak yeniden erişilebilir olduğunda aynı süreçten devam edin; istek aralığını kısaltmayın."], "warning")
    if statuses["network_error"] or any(int(k) >= 500 for k in statuses if k.isdigit()):
        finding("network", "Bağlantı veya kaynak sunucu hataları oluştu.", dict(statuses),
                ["Bağlantıyı kontrol edin.", "Aynı süreç kimliğiyle devam edin; kaydedilmiş ilanların detayları tekrar istenmez."], "warning")
    if metrics["duplicates"]:
        finding("duplicates", "Dönen kartların bir kısmı daha önce görülmüş ilanlardı.", f"{metrics['duplicates']} tekrar kart elendi.",
                ["Dönen kart sayısını benzersiz ilan sayısıyla karşılaştırın.", "Aynı kaydı çoğaltmak yerine farklı unvan veya konumlarla yeni süreç oluşturun."])
    if metrics["detail_failures"]:
        finding("detail_failures", "Bazı ilanların detay metni alınamadı.", {"count": metrics["detail_failures"], "job_ids": sorted(failed_ids)},
                ["Başarısız ilan kimliklerinin istek kayıtlarını inceleyin.", "Kaldırılan ilanlar geri getirilemez; geçici hatalarda aramayı yeniden tarayın."], "warning")
    if metrics["processing_failures"] or metrics["quality_rejections"]:
        finding("processing", "Alınan içeriklerin bir kısmı kayıt/ayrıştırma aşamasında elendi.",
                {"failed": metrics["processing_failures"], "quality_rejected": metrics["quality_rejections"]},
                ["İşleme sonuçları katmanında ilan kimliği, aşama ve hata türünü inceleyin.", "Eksik ayrıştırılan kayıtları görünürlük filtresinden açın."], "warning")
    if metrics["model_fallbacks"]:
        finding("model_fallback", "Seçilen yapay zekâ yerine hızlı analiz kullanıldı.", metrics["model_fallbacks"],
                ["Model bağlantısını ve model adını kontrol edin.", "Kayıtlı ilanları yeniden analiz edin; yeniden tarama gerekmez."], "warning")
    if metrics["deleted_jobs"] or metrics["invalid_jobs"]:
        finding("hidden", "Kaydedilen bazı ilanlar varsayılan listede görünmüyor.",
                {"trash": metrics["deleted_jobs"], "invalid": metrics["invalid_jobs"]},
                ["Çöp kutusu ve ayrıştırma kalitesi filtrelerini kontrol edin."])
    if metrics["found_jobs"] and not metrics["new_jobs"]:
        finding("already_known", "Bu süreçte bulunan ilanlar sistemde zaten vardı.", f"{metrics['found_jobs']} ilişkili ilan var; ilk kez eklenen ilan yok.",
                ["İlanları gör düğmesiyle tüm ilişkili ilanları açın.", "İlk kez eklenenler filtresini kaldırın."])
    task_reports = []
    for task in tasks:
        checkpoint, stats = json.loads(task.checkpoint), json.loads(task.stats)
        reason = reasons.get(task.id) or stats.get("termination_reason")
        count = checkpoint.get("collected", 0)
        if task.limit and count >= task.limit:
            finding("target_reached", f"{task.keyword}: belirlenen hedefe ulaşıldı.", {"search_id": task.id, "target": task.limit, "collected": count},
                    ["Daha fazla sonuç için hedefi artırın veya yeni taramada limitsiz seçin."])
        elif reason in ("exhausted_results", "repeated_page"):
            finding(reason, f"{task.keyword}: kaynak boş veya tekrarlanan sonuç döndürdü.", {"search_id": task.id, "reason": reason, "collected": count},
                    ["Hedef ilan sayısı, kaynağın o sorgu için erişilebilir ilan sayısını garanti etmez.", "Unvanı veya konumu genişletin; önerilen değişiklikle yeni bir süreç oluşturun."])
        task_reports.append({"search_id": task.id, "keyword": task.keyword, "location": task.location, "target": task.limit,
                             "collected": count, "status": task.status, "termination_reason": reason, "error": task.error})
    if run.status in ("paused", "pausing", "cancelled", "cancelling", "stopped", "stopping"):
        finding("interrupted", "Süreç tamamlanmadan duraklatıldı veya iptal edildi.", run.status,
                ["Duraklatılmış süreci aynı kimlikle devam ettirin; durdurulmuş veya iptal edilmiş süreç için yeni çalışma oluşturun."])
    if kind != "scrape":
        metrics["processed_jobs"] = sum(json.loads(t.checkpoint).get("collected",0) for t in tasks)
        metrics["target_jobs"] = sum(json.loads(t.checkpoint).get("target_total",0) for t in tasks)
    return {"run_id": run_id, "search_id": task_id, "audit_version": VERSION, "generated_at": datetime.utcnow().isoformat()+"Z",
            "status": run.status, "kind": kind, "options": clean(json.loads(run.options)),
            "coverage": "detailed" if has_pages else "legacy_or_non_scrape", "metrics": metrics, "http_statuses": dict(statuses),
            "failed_job_ids": sorted(failed_ids), "tasks": task_reports, "findings": findings, "timeline": timeline,
            "last_error": last_error, "notes": ["Kart toplamları tekrar isteklerini içerir; LinkedIn genel toplamı değildir.",
                                                  "İlan ile süreç ilişkileri çöp kutusu ve kalite durumundan bağımsız saklanır."]}
