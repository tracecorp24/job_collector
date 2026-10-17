"""Panel sekmesi: ilan havuzunun ve toplayıcının özet metrikleri tek uçtan okunur.

Yalnızca okuma yapar; şema değiştirmez. Sayımlar etkin ilanlar (çöpte olmayan, ayrıştırması geçerli)
üzerindendir ve Ana sayfadaki filtrelerle aynı anlama gelir. Sonuç kısa süre bellekte tutulur; böylece
birden çok açık sekme veya sık yenileme veritabanını yormaz.
"""
import json
import threading
import time
from datetime import datetime, timedelta

from flask import jsonify, request
from sqlalchemy import case, func, text

from .models import Job, SearchRun, SearchTask, TaskJob, Watch
from .transport import Coordinator

CACHE_SECONDS = 20
MIN_REFRESH_SECONDS = 3
HOURLY_DAYS = 30
RUN_LIMIT = 12
_cache = {"at": 0.0, "data": None, "owner": None}
_lock = threading.Lock()

# Yalnızca geçerli JSON dizilerini açar; bozuk satır tüm sorguyu düşürmesin.
_EACH = "json_each(CASE WHEN json_valid(jobs.{col}) THEN jobs.{col} ELSE '[]' END)"


def _active():
    return (Job.deleted_at.is_(None), Job.quality_ok.is_(True))


def _count_if(condition):
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _percentile(values, fraction):
    if not values:
        return None
    index = (len(values) - 1) * fraction
    low, high = int(index), min(int(index) + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (index - low)


def _grouped(session, column, limit=None, skip_empty=True):
    count = func.count(Job.id)
    query = session.query(column, count).filter(*_active()).group_by(column).order_by(count.desc())
    if skip_empty:
        query = query.filter(column.isnot(None), column != "")
    if limit:
        query = query.limit(limit)
    return [{"value": value, "count": n} for value, n in query.all()]


def _folded(session, column, empty=("", "Unknown")):
    """Boş ve bilinmeyen değerleri tek '__missing__' kovasında birleştirir (filtre paneliyle aynı anlam)."""
    merged = {}
    for value, n in session.query(column, func.count(Job.id)).filter(*_active()).group_by(column):
        key = "__missing__" if value is None or value in empty else value
        merged[key] = merged.get(key, 0) + n
    return [{"value": k, "count": v} for k, v in sorted(merged.items(), key=lambda i: -i[1])]


def _json_top(session, column, limit, kinds=("text",)):
    """Etkin ilanların JSON dizi sütunundaki değerleri, büyük/küçük harf ayrımı olmadan sayar."""
    sql = text(
        "SELECT MAX(e.value) AS value, COUNT(*) AS n "
        f"FROM jobs, {_EACH.format(col=column)} AS e "
        "WHERE jobs.deleted_at IS NULL AND jobs.quality_ok = 1 AND e.type = 'text' AND TRIM(e.value) != '' "
        "GROUP BY LOWER(TRIM(e.value)) ORDER BY n DESC, value LIMIT :limit")
    return [{"value": row.value, "count": row.n} for row in session.execute(sql, {"limit": limit})]


def _salary(session):
    rows = session.query(Job.salary_currency, Job.salary_period, Job.salary_min, Job.salary_max).filter(
        *_active(), Job.salary_currency != "", Job.salary_period != "",
        (Job.salary_min.isnot(None)) | (Job.salary_max.isnot(None))).all()
    groups = {}
    for currency, period, low, high in rows:
        points = [v for v in (low, high) if v is not None]
        groups.setdefault((currency, period), []).append(sum(points) / len(points))
    result = []
    for (currency, period), values in sorted(groups.items(), key=lambda i: -len(i[1]))[:6]:
        values.sort()
        result.append({"currency": currency, "period": period, "count": len(values),
                       "p25": round(_percentile(values, .25)), "median": round(_percentile(values, .5)),
                       "p75": round(_percentile(values, .75)), "min": round(values[0]), "max": round(values[-1])})
    return result


def _posted_age(session, now):
    edges = [(1, "≤ 1 gün"), (3, "2–3 gün"), (7, "4–7 gün"), (30, "8–30 gün")]
    conditions = []
    for days, _ in edges:
        conditions.append((Job.posted_at >= now - timedelta(days=days), str(days)))
    bucket = case(*conditions, (Job.posted_at.isnot(None), "old"), else_="unknown")
    counts = dict(session.query(bucket, func.count(Job.id)).filter(*_active()).group_by(bucket).all())
    rows = [{"key": str(days), "label": label, "count": counts.get(str(days), 0)} for days, label in edges]
    rows.append({"key": "old", "label": "30+ gün", "count": counts.get("old", 0)})
    rows.append({"key": "unknown", "label": "Tarihi yok", "count": counts.get("unknown", 0)})
    return rows


def _hourly(session, since):
    bucket = func.strftime("%Y-%m-%d %H", Job.created_at)
    rows = session.query(bucket, func.count(Job.id)).filter(*_active(), Job.created_at >= since).group_by(bucket).all()
    return [[hour, n] for hour, n in rows if hour]


def _collector(session, server, now_dt):
    now = time.time()
    source = Coordinator().state()
    watches = session.query(Watch).all()
    enabled = [w for w in watches if w.enabled]
    next_due = min((w.next_due_at or 0 for w in enabled), default=None)
    week = now_dt - timedelta(days=7)
    rows = (session.query(SearchRun).filter(SearchRun.deleted_at.is_(None), SearchRun.created_at >= week)
            .order_by(SearchRun.created_at.desc()).limit(300).all())
    scrapes = []
    for run in rows:
        try:
            options = json.loads(run.options or "{}")
        except (ValueError, TypeError):
            options = {}
        if options.get("kind", "scrape") == "scrape":
            scrapes.append((run, options))
    statuses = {}
    for run, _ in scrapes:
        statuses[run.status] = statuses.get(run.status, 0) + 1
    recent = scrapes[:RUN_LIMIT]
    counts = {run.id: {"new": 0, "updated": 0, "tasks": 0} for run, _ in recent}
    if counts:
        links = (session.query(SearchTask.run_id, TaskJob.is_new, TaskJob.outcome, func.count())
                 .join(SearchTask, SearchTask.id == TaskJob.task_id).filter(SearchTask.run_id.in_(counts))
                 .group_by(SearchTask.run_id, TaskJob.is_new, TaskJob.outcome).all())
        for run_id, is_new, outcome, n in links:
            kind = outcome if outcome in ("new", "updated", "unchanged") else "new" if is_new else "updated"
            if kind in ("new", "updated"):
                counts[run_id][kind] += n
        for run_id, n in session.query(SearchTask.run_id, func.count()).filter(SearchTask.run_id.in_(counts)).group_by(SearchTask.run_id):
            counts[run_id]["tasks"] = n
    return {
        "running": bool(server.state.running),
        "source": {"paused": bool(source["paused"]), "remaining_seconds": source["remaining_seconds"],
                   "reason": source["reason"] or "", "interval_floor": source["interval_floor"]},
        "watches": {"total": len(watches), "enabled": len(enabled), "next_due_at": next_due},
        "run_statuses": statuses,
        "runs": [{"id": run.id, "status": run.status, "watch": bool(options.get("watch_id")),
                  "created_at": run.created_at.isoformat() + "Z", "ended_at": run.ended_at.isoformat() + "Z" if run.ended_at else None,
                  **counts[run.id]} for run, options in reversed(recent)],
        "now": now,
    }


def build(server):
    now_dt = datetime.utcnow()
    d1, d7, d14 = (now_dt - timedelta(days=n) for n in (1, 7, 14))
    with server.SessionLocal() as session:
        row = session.query(
            func.count(Job.id),
            _count_if(Job.created_at >= d1), _count_if(Job.created_at >= d7),
            _count_if((Job.created_at >= d14) & (Job.created_at < d7)),
            _count_if(Job.posted_at >= d1), _count_if(Job.posted_at >= d7),
            _count_if((Job.salary.isnot(None)) & (Job.salary != "")),
            _count_if(Job.workplace_type == "Remote"), _count_if(Job.workplace_type == "Hybrid"),
            _count_if(Job.flag.in_(("scam", "ghost"))),
            _count_if((Job.description.isnot(None)) & (Job.description != "")),
            _count_if((Job.summary.isnot(None)) & (Job.summary != "")),
            _count_if(Job.embedding.isnot(None)),
            func.max(Job.created_at), func.max(Job.scraped_at),
            func.count(func.distinct(Job.company)),
        ).filter(*_active()).one()
        keys = ("total", "created_24h", "created_7d", "created_prev_7d", "posted_24h", "posted_7d", "with_salary",
                "remote", "hybrid", "flagged", "with_description", "with_summary", "with_embedding")
        totals = dict(zip(keys, (int(v or 0) for v in row[:13])))
        totals["companies"] = int(row[15] or 0)
        totals["trash"] = session.query(func.count(Job.id)).filter(Job.deleted_at.isnot(None)).scalar() or 0
        totals["invalid"] = session.query(func.count(Job.id)).filter(Job.deleted_at.is_(None), Job.quality_ok.is_(False)).scalar() or 0
        totals["last_created_at"] = row[13].isoformat() + "Z" if row[13] else None
        totals["last_scraped_at"] = row[14].isoformat() + "Z" if row[14] else None
        return {
            "generated_at": now_dt.isoformat() + "Z",
            "totals": totals,
            "hourly": _hourly(session, now_dt - timedelta(days=HOURLY_DAYS)),
            "posted_age": _posted_age(session, now_dt),
            "professions": _json_top(session, "profession_groups", 8),
            "workplace": _folded(session, Job.workplace_type),
            "seniority": _folded(session, Job.seniority),
            "skills": _json_top(session, "tags", 12),
            "companies": _grouped(session, Job.company, 8),
            "locations": _grouped(session, Job.location, 8),
            "backend": _grouped(session, Job.classified_by, skip_empty=False),
            "salary": _salary(session),
            "collector": _collector(session, server, now_dt),
        }


def install(server):
    app = server.app

    @app.get("/api/dashboard")
    def dashboard():
        force = request.args.get("refresh") == "1"
        with _lock:
            age = time.time() - _cache["at"]
            if _cache["data"] is not None and _cache["owner"] is server.SessionLocal and age < (MIN_REFRESH_SECONDS if force else CACHE_SECONDS):
                return jsonify(_cache["data"])
            data = build(server)
            _cache.update(at=time.time(), data=data, owner=server.SessionLocal)
        return jsonify(data)
