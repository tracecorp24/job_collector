"""Profil uygunluk puanı: kayıtlı özgeçmiş ile ilanları Groq'a karşılaştırtır (0-100 + kısa gerekçe).

Embedding gerektirmez, bu yüzden Ollama'nın olmadığı sunucuda da çalışır. Kotayı verimli
kullanmak için ilanlar tam açıklama yerine kısa özetleriyle, birkaç ilan tek istekte gönderilir.
Puan, hangi profil metni için üretildiğini (`fit_profile`) saklar; profil değişince eski puanlar
"güncel değil" sayılır ve yeniden puanlanır, hiçbir veri silinmez.
"""
import hashlib
import json
import time
from . import groq_client
from .db import SessionLocal, init_db
from .models import Job
from .profile import get_profile

BATCH = 6
MAX_PROFILE = 3000
INSTRUCTIONS = (
    "Sen bir kariyer danışmanısın. Sana bir adayın profili ve numaralı iş ilanları verilecek. Her ilan için "
    "adayın ilana uygunluğunu 0-100 arası puanla (beceri, deneyim yılı, kıdem ve alan uyumuna bak; "
    "eksik kritik şartlar puanı düşürür). Gerekçeyi Türkçe, en fazla 15 kelimeyle yaz: güçlü yön + eksik. "
    'Yalnızca şu JSON\'u döndür: {"results": [{"id": <ilan id>, "score": <0-100>, "reason": "..."}]}'
)


def profile_hash(text):
    text = (text or "").strip()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] if text else ""


def _brief(job):
    try:
        tags = ", ".join(json.loads(job.tags or "[]"))
    except (ValueError, TypeError):
        tags = ""
    about = job.summary or (job.description or "")[:600]
    years = f"{job.experience_years} yıl" if job.experience_years is not None else "belirtilmemiş"
    return (f"[id={job.id}] {job.title} — {job.company} ({job.location})\n"
            f"Kıdem: {job.seniority}; deneyim: {years}; beceriler: {tags}\n{about}")


def score_batch(profile_text, jobs, max_wait=65):
    """Returns {job_id: (score, reason)} for the jobs the model answered for."""
    content = f"PROFİL:\n{profile_text[:MAX_PROFILE]}\n\nİLANLAR:\n\n" + "\n\n".join(_brief(j) for j in jobs)
    data = groq_client.chat_json([{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": content}],
                                 max_tokens=120 + 60 * len(jobs), max_wait=max_wait)
    wanted, result = {j.id for j in jobs}, {}
    for item in data.get("results") or []:
        try:
            job_id, score = int(item.get("id")), int(round(float(item.get("score"))))
        except (TypeError, ValueError, AttributeError):
            continue
        if job_id in wanted:
            result[job_id] = (max(0, min(100, score)), str(item.get("reason") or "").strip()[:200])
    return result


def run_fit_backfill(limit=None, emit=None, should_stop=None, force=False, skip_ids=None) -> dict:
    should_stop = should_stop or (lambda: False)

    def _emit(kind, data=None):
        if emit:
            emit(kind, data or {})

    init_db()
    session = SessionLocal()
    stats = {"scored": 0, "skipped": 0, "total": 0}
    try:
        profile_text = get_profile(session)["text"].strip()
        if not profile_text:
            _emit("error", {"msg": "Önce Profilim bölümüne özgeçmişini ekle."})
            stats["termination_reason"] = "model_unavailable"
            return stats
        current = profile_hash(profile_text)
        q = session.query(Job).filter(Job.quality_ok.is_(True), Job.deleted_at.is_(None))
        if not force:
            q = q.filter((Job.fit_profile != current) | Job.fit_profile.is_(None) | Job.fit_score.is_(None))
        if skip_ids:
            q = q.filter(~Job.id.in_(skip_ids))
        q = q.order_by(Job.scraped_at.desc(), Job.id.desc())
        if limit:
            q = q.limit(limit)
        jobs = q.all()
        stats["total"] = len(jobs)
        _emit("queue_ready", {"total": len(jobs)})
        failures, done, reason = 0, 0, "completed"
        for start in range(0, len(jobs), BATCH):
            if should_stop():
                reason = "stopped_by_user"
                break
            batch = jobs[start:start + BATCH]
            started = time.monotonic()
            try:
                scores = score_batch(profile_text, batch)
            except groq_client.GroqError as error:
                scores = {}
                _emit("log", {"msg": f"Uygunluk puanlanamadı: {error}", "level": "warning"})
                if error.status in (429, 503):
                    failures = 2
            failures = 0 if scores else failures + 1
            for job in batch:
                done += 1
                if job.id in scores:
                    job.fit_score, job.fit_reason = scores[job.id]
                    job.fit_profile = current
                    stats["scored"] += 1
                    _emit("processing_result", {"stage": "fit", "status": "saved", "job_id": job.id, "score": job.fit_score,
                                                "duration_ms": round((time.monotonic() - started) * 1000)})
                else:
                    stats["skipped"] += 1
                    _emit("processing_result", {"stage": "fit", "status": "failed", "job_id": job.id, "level": "warning"})
            session.commit()
            _emit("task_done", {"done": done, "total": len(jobs), "pct": int(done / max(len(jobs), 1) * 100)})
            if failures >= 2:
                reason = "model_unavailable"
                _emit("log", {"msg": "Groq'a ulaşılamadı veya kota doldu — durduruldu, kalanlar sonra puanlanabilir.", "level": "error"})
                break
        stats["termination_reason"] = reason
        _emit("finished", stats)
    except Exception as e:
        _emit("error", {"msg": str(e)})
    finally:
        session.close()
    return stats
