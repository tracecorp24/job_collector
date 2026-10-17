"""Yerelden log sorgulama/indirme ve hata kaydı (incident) API'si. Yalnızca yönetici anahtarıyla.

- GET  /api/v1/logs               sayfalı sorgu (source=app|events)
- GET  /api/v1/logs/export        aralığı NDJSON olarak indir
- GET  /api/v1/incidents          hata kayıtları (status=open|resolved|all, needs_issue=1)
- GET  /api/v1/incidents/<id>     ayrıntı + geçmiş + son loglar
- POST /api/v1/incidents/<id>     GitHub senkronu: {"action":"link","issue_number":N} | {"action":"resolve",...}
"""
import hmac
import json
import re
from datetime import datetime, timedelta, timezone

from flask import Response, jsonify, request, stream_with_context
from sqlalchemy import or_

from . import config, logstore
from .models import AppLog, Incident, SearchEvent

MAX_LIMIT = 1000
MAX_EXPORT_DAYS = 31
RELATIVE = re.compile(r"^(\d+)([mhd])$")


def parse_time(value, name):
    """ISO 8601 (Z/ofsetli veya UTC kabul edilen yerel) ya da göreli '30m', '2h', '7d'."""
    if not value:
        return None
    value = value.strip()
    match = RELATIVE.match(value)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        return datetime.utcnow() - timedelta(**{dict(m="minutes", h="hours", d="days")[unit]: amount})
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} geçersiz; ISO 8601 (2026-10-17T08:00:00Z) veya 30m/2h/7d kullanın.")
    if moment.tzinfo:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def stamp(moment):
    return moment.isoformat() + "Z" if moment else None


def require_admin():
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not (config.ADMIN_KEY and hmac.compare_digest(supplied, config.ADMIN_KEY)):
        return jsonify(error="Loglar için yönetici anahtarı gerekli.", code="forbidden"), 403
    return None


def filtered(args):
    source = args.get("source", "app")
    if source not in ("app", "events"):
        raise ValueError("source app veya events olmalı.")
    model = AppLog if source == "app" else SearchEvent
    since, until = parse_time(args.get("since"), "since"), parse_time(args.get("until"), "until")
    incident = args.get("incident_id")
    if incident and not incident.isdigit():
        raise ValueError("incident_id tam sayı olmalı.")
    def apply(query):
        if since:
            query = query.filter(model.created_at >= since)
        if until:
            query = query.filter(model.created_at < until)
        level = args.get("level")
        if level:
            if level not in logstore.LEVELS:
                raise ValueError("level debug, info, warning, error veya critical olmalı.")
            query = query.filter(model.level.in_([k for k, v in logstore.LEVELS.items() if v >= logstore.LEVELS[level]]))
        text = args.get("q")
        if source == "app":
            if args.get("logger"):
                query = query.filter(AppLog.logger.like(args["logger"] + "%"))
            if incident:
                query = query.filter(AppLog.incident_id == int(incident))
            if text:
                query = query.filter(or_(AppLog.message.contains(text), AppLog.traceback.contains(text)))
        else:
            for key, column in (("run_id", SearchEvent.run_id), ("task_id", SearchEvent.task_id), ("kind", SearchEvent.kind)):
                if args.get(key):
                    query = query.filter(column == args[key])
            if text:
                query = query.filter(SearchEvent.data.contains(text))
        return query
    return source, model, since, until, apply


def row(source, item):
    if source == "app":
        return dict(id=item.id, ts=stamp(item.created_at), level=item.level, logger=item.logger, message=item.message,
                    traceback=item.traceback or None, incident_id=item.incident_id)
    return dict(id=item.id, ts=stamp(item.created_at), level=item.level, kind=item.kind, run_id=item.run_id,
                task_id=item.task_id, data=json.loads(item.data or "{}"))


def install(server):
    app = server.app

    @app.get("/api/v1/logs")
    def query_logs():
        denied = require_admin()
        if denied:
            return denied
        source, model, _, _, apply = filtered(request.args)
        try:
            after = int(request.args.get("after_id", 0))
            limit = int(request.args.get("limit", 200))
        except ValueError:
            raise ValueError("after_id ve limit tam sayı olmalı.")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit 1–{MAX_LIMIT} aralığında olmalı.")
        with server.SessionLocal() as session:
            query = apply(session.query(model))
            if request.args.get("order") == "desc":
                if after:
                    query = query.filter(model.id < after)
                rows = query.order_by(model.id.desc()).limit(limit + 1).all()
            else:
                rows = query.filter(model.id > after).order_by(model.id).limit(limit + 1).all()
            items = [row(source, r) for r in rows[:limit]]
        return jsonify(source=source, items=items, next_after_id=items[-1]["id"] if items else after, has_more=len(rows) > limit)

    @app.get("/api/v1/logs/export")
    def export_logs():
        denied = require_admin()
        if denied:
            return denied
        source, model, since, until, apply = filtered(request.args)
        if not since:
            raise ValueError("İndirme için since gerekli (ör. since=2026-10-17T00:00:00Z veya since=24h).")
        if ((until or datetime.utcnow()) - since).days > MAX_EXPORT_DAYS:
            raise ValueError(f"Tek indirme en fazla {MAX_EXPORT_DAYS} gün olabilir; aralığı bölün.")

        def generate():
            with server.SessionLocal() as session:
                for item in apply(session.query(model)).order_by(model.id).yield_per(500):
                    yield json.dumps(row(source, item), ensure_ascii=False) + "\n"
        name = f"linko-{source}-{since:%Y%m%dT%H%M}-{(until or datetime.utcnow()):%Y%m%dT%H%M}.jsonl"
        return Response(stream_with_context(generate()), mimetype="application/x-ndjson",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/api/v1/incidents")
    def list_incidents():
        denied = require_admin()
        if denied:
            return denied
        status = request.args.get("status", "open")
        if status not in ("open", "resolved", "all"):
            raise ValueError("status open, resolved veya all olmalı.")
        with server.SessionLocal() as session:
            query = session.query(Incident)
            if status != "all":
                query = query.filter(Incident.status == status)
            if request.args.get("needs_issue") == "1":
                # Issue'su olmayan ya da GitHub'da kapalıyken tekrar açılmış kayıtlar.
                query = query.filter(Incident.status == "open", or_(Incident.issue_number.is_(None), Incident.issue_state != "open"))
            rows = query.order_by(Incident.last_seen.desc()).all()
            return jsonify(items=[logstore.serialize(i) for i in rows])

    @app.get("/api/v1/incidents/<int:incident_id>")
    def get_incident(incident_id):
        denied = require_admin()
        if denied:
            return denied
        with server.SessionLocal() as session:
            incident = session.get(Incident, incident_id)
            if not incident:
                return jsonify(error="Hata kaydı bulunamadı."), 404
            recent = session.query(AppLog).filter_by(incident_id=incident_id).order_by(AppLog.id.desc()).limit(20).all()
            return jsonify(dict(logstore.serialize(incident, full=True), recent_logs=[row("app", r) for r in recent]))

    @app.post("/api/v1/incidents/<int:incident_id>")
    def update_incident(incident_id):
        denied = require_admin()
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        with server.SessionLocal() as session:
            incident = session.get(Incident, incident_id)
            if not incident:
                return jsonify(error="Hata kaydı bulunamadı."), 404
            if action == "link":
                number = body.get("issue_number")
                if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                    raise ValueError("issue_number pozitif tam sayı olmalı.")
                logstore.link_issue(incident, number)
            elif action == "resolve":
                logstore.resolve(incident, str(body.get("resolution") or "")[:2000], body.get("issue_number"))
            else:
                raise ValueError("action link veya resolve olmalı.")
            session.commit()
            return jsonify(logstore.serialize(incident, full=True))
