"""Flask app: a read-only jobs viewer plus a button-triggered scrape.

Endpoints:
  GET  /                -> jobs viewer UI
  GET  /api/jobs        -> filtered, paginated jobs
  GET  /api/jobs/<id>   -> one job (with description)
  GET  /api/facets      -> distinct categories/seniorities/etc. for filters
  POST /api/scrape      -> start a background scrape
  POST /api/embed       -> backfill embeddings for existing jobs (no re-scrape)
  POST /api/classify    -> re-classify existing jobs with local/Claude LLM (no re-scrape)
  GET  /api/ollama/models -> models pulled in the local Ollama server
  POST /api/scrape/stop -> request the running scrape or maintenance task to stop
  GET  /api/scrape/status
  GET  /events          -> SSE progress stream

``/api/embed``, ``/api/classify`` and ``/api/scrape`` all share the same
single-run ``state``/``/events`` stream/stop endpoint below — only one of them
can run at a time.
"""

import json
import queue
from collections import deque
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request
from sqlalchemy import distinct, func, or_

from . import config
from .db import SessionLocal, init_db
from .models import Job

app = Flask(__name__)


# --- Scrape run state (single run at a time) -------------------------------

class ScrapeState:
    def __init__(self):
        self.running = False
        self.stop_flag = False
        self.thread = None
        self.scraper = None
        self.kind = "scrape"  # "scrape" | "embed" | "classify" - which run owns event_queue
        self.event_queue = queue.Queue()
        self.last = {"state": "idle", "new": 0, "updated": 0, "skipped": 0}
        self.run_id = None
        self.sequence = 0
        self.messages = deque(maxlen=1000)
        self.condition = threading.Condition()

    def emit(self, event_type, data):
        event = {
            "type": event_type,
            "data": data,
            "ts": datetime.now().strftime("%H:%M:%S"),
        }
        with self.condition:
            self.sequence += 1
            event["id"] = self.sequence
            self.messages.append(event)
            self.condition.notify_all()
        if event_type == "finished":
            self.last = {"state": "finished", **(data or {})}
        elif event_type == "error":
            self.last = {"state": "error", **(data or {})}


state = ScrapeState()


# --- Pages -----------------------------------------------------------------

@app.route("/")
def index():
    # Sayfa her açılışta yeniden doğrulanır; deploy sonrası tarayıcı eski arayüzde kalmaz.
    return Response(render_template("index.html", detail_cache_hours=round(config.DETAIL_CACHE_TTL_SECONDS/3600, 2)), headers={"Cache-Control": "no-cache"})


# --- Jobs API --------------------------------------------------------------

def _rank_by_embedding(query, target):
    """Rank every row of ``query`` (a Job query already filtered) by cosine
    similarity to ``target`` (an embedding vector). Returns
    ``(ranked_ids_in_order, scores_by_id)`` — a full re-sort, not a cutoff,
    since callers are choosing an order for an already-filtered set rather
    than searching for a hard match."""
    from . import embed

    candidates = [
        (row.id, json.loads(row.embedding))
        for row in query.filter(Job.embedding.isnot(None)).with_entities(Job.id, Job.embedding).all()
    ]
    ranked = embed.top_similar(target, candidates, limit=len(candidates))
    return [cid for cid, _ in ranked], dict(ranked)


@app.route("/api/jobs")
def api_jobs():
    session = SessionLocal()
    try:
        q = session.query(Job).filter(Job.quality_ok.is_(True))

        search = (request.args.get("search") or "").strip()
        semantic_requested = (request.args.get("semantic") or "").strip() in ("1", "true", "True")
        semantic_target = None
        semantic_fallback = False

        if search and semantic_requested:
            from . import embed
            semantic_target = embed.embed_text(search)
            if semantic_target is None:
                semantic_fallback = True

        if search and semantic_target is None:
            like = f"%{search}%"
            q = q.filter(or_(
                Job.title.ilike(like),
                Job.company.ilike(like),
                Job.tags.ilike(like),
            ))

        for field, column in (
            ("category", Job.category),
            ("seniority", Job.seniority),
            ("workplace", Job.workplace_type),
            ("company", Job.company),
            ("source", Job.source),
            ("search_term", Job.search_term),
            ("search_location", Job.search_location),
        ):
            val = (request.args.get(field) or "").strip()
            if val:
                q = q.filter(column == val)

        flag = (request.args.get("flag") or "").strip()
        if flag == "clean":
            q = q.filter(Job.flag == "")
        elif flag in ("scam", "ghost"):
            q = q.filter(Job.flag == flag)

        try:
            page = max(1, int(request.args.get("page", 1)))
        except ValueError:
            page = 1
        try:
            per_page = min(100, max(1, int(request.args.get("per_page", 24))))
        except ValueError:
            per_page = 24

        sort = request.args.get("sort", "recent")

        rank_mode = None
        if semantic_target is not None:
            rank_mode = "semantic"
        if rank_mode is not None:
            ranked_ids, scores = _rank_by_embedding(q, semantic_target)
            total = len(ranked_ids)
            page_ids = ranked_ids[(page - 1) * per_page: page * per_page]
            rows_by_id = {r.id: r for r in session.query(Job).filter(Job.id.in_(page_ids)).all()} if page_ids else {}
            jobs = [
                dict(rows_by_id[cid].to_dict(), score=round(scores[cid], 4))
                for cid in page_ids if cid in rows_by_id
            ]
            return jsonify({
                "jobs": jobs,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page,
                "mode": rank_mode,
            })

        total = q.count()

        if sort == "salary_high":
            order = (Job.salary_max.is_(None), Job.salary_max.desc())
        elif sort == "salary_low":
            order = (Job.salary_min.is_(None), Job.salary_min.asc())
        else:
            order = (Job.scraped_at.desc(), Job.id.desc())

        rows = (
            q.order_by(*order)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return jsonify({
            "jobs": [j.to_dict() for j in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
            **({"semantic_fallback": True} if semantic_fallback else {}),
        })
    finally:
        session.close()


@app.route("/api/jobs/<int:job_id>")
def api_job(job_id):
    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        return jsonify(job.to_dict(include_description=True))
    finally:
        session.close()


@app.route("/api/jobs/<int:job_id>/fetch-detail", methods=["POST"])
def api_fetch_job_detail(job_id):
    # Manual detail requests share the priority queue and its single worker.
    return app.view_functions["repair_job"](job_id)


@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def api_job_delete(job_id):
    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        session.delete(job)
        session.commit()
        return jsonify({"ok": True})
    finally:
        session.close()


@app.route("/api/jobs", methods=["DELETE"])
def api_jobs_delete_all():
    session = SessionLocal()
    try:
        count = session.query(Job).delete()
        session.commit()
        return jsonify({"ok": True, "deleted": count})
    finally:
        session.close()


@app.route("/api/jobs/<int:job_id>/similar")
def api_job_similar(job_id):
    from . import embed

    session = SessionLocal()
    try:
        job = session.get(Job, job_id)
        if not job or not job.embedding:
            return jsonify({"jobs": [], "reason": "no_embedding"})

        try:
            limit = min(20, max(1, int(request.args.get("limit", 6))))
        except ValueError:
            limit = 6

        target = json.loads(job.embedding)
        candidates = [
            (row.id, json.loads(row.embedding))
            for row in session.query(Job.id, Job.embedding)
            .filter(Job.quality_ok.is_(True), Job.deleted_at.is_(None), Job.embedding.isnot(None), Job.id != job_id)
            .all()
        ]
        ranked = embed.top_similar(target, candidates, limit=limit)
        scores = dict(ranked)
        rows = session.query(Job).filter(Job.id.in_(scores.keys())).all() if scores else []
        results = sorted(
            (dict(j.to_dict(), score=round(scores[j.id], 4)) for j in rows),
            key=lambda d: d["score"],
            reverse=True,
        )
        return jsonify({"jobs": results})
    finally:
        session.close()


@app.route("/api/facets")
def api_facets():
    session = SessionLocal()
    try:
        base = session.query(Job).filter(Job.quality_ok.is_(True))

        def counts(column):
            rows = (
                session.query(column, func.count(Job.id))
                .filter(Job.quality_ok.is_(True))
                .group_by(column)
                .all()
            )
            return [
                {"value": v, "count": c}
                for v, c in sorted(rows, key=lambda r: -r[1]) if v
            ]

        companies = [
            r[0] for r in session.query(distinct(Job.company))
            .filter(Job.quality_ok.is_(True), Job.company != "")
            .order_by(Job.company).all()
        ]
        return jsonify({
            "total": base.count(),
            "category": counts(Job.category),
            "seniority": counts(Job.seniority),
            "workplace": counts(Job.workplace_type),
            "flag": counts(Job.flag),
            "companies": companies,
            "missing_embeddings": base.filter(Job.embedding.is_(None)).count(),
            "not_locally_classified": base.filter(Job.classified_by != "local").count(),
        })
    finally:
        session.close()


# --- Scrape control --------------------------------------------------------

_CLASSIFY_BACKENDS = ("rules", "claude", "local", "groq")


def _run_scrape(keywords, locations, limit, classify_backend, use_embeddings, require_login):
    from .pipeline import run_scrape
    try:
        run_scrape(
            keywords=keywords,
            locations=locations,
            limit=limit,
            classify_backend=classify_backend,
            use_embeddings=use_embeddings,
            require_login=require_login,
            emit=state.emit,
            should_stop=lambda: state.stop_flag,
            on_scraper_ready=lambda s: setattr(state, "scraper", s),
        )
    finally:
        state.running = False
        state.stop_flag = False
        state.scraper = None


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    if state.running:
        return jsonify({"ok": False, "error": "A scrape is already running."}), 400

    body = request.get_json(force=True, silent=True) or {}
    raw_keywords = body.get("keywords", [])
    raw_locations = body.get("locations") or []
    locations = [str(l).strip() for l in raw_locations if str(l).strip()]
    if not locations:
        locations = [config.DEFAULT_LOCATION]
    classify_backend = body.get("classify_backend", "rules")
    if classify_backend not in _CLASSIFY_BACKENDS:
        classify_backend = "rules"
    use_embeddings = bool(body.get("use_embeddings", False))
    require_login = body.get("require_login", False)
    if require_login is not False:
        return jsonify({"ok": False, "error": "Light supports accountless search only."}), 400

    def to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    keywords = []
    for kw in raw_keywords:
        if isinstance(kw, dict):
            keywords.append({
                "keyword": kw.get("keyword", ""),
                "location": kw.get("location"),
                "limit": to_int(kw.get("limit")),
            })
        elif str(kw).strip():
            keywords.append({"keyword": str(kw).strip(), "limit": to_int(body.get("limit"))})
    keywords = [k for k in keywords if k["keyword"].strip()]

    if not keywords:
        return jsonify({"ok": False, "error": "At least one keyword is required."}), 400

    if not require_login:
        raw_limits = [kw.get("limit") for kw in raw_keywords if isinstance(kw, dict)]
        raw_limits.append(body.get("limit"))
        if any(v not in (None, "") and (to_int(v) is None or to_int(v) <= 0)
               for v in raw_limits):
            return jsonify({"ok": False, "error": "Accountless limit must be a positive integer."}), 400

    state.event_queue = queue.Queue()
    state.running = True
    state.stop_flag = False
    state.kind = "scrape"
    state.last = {"state": "running", "new": 0, "updated": 0, "skipped": 0}
    state.thread = threading.Thread(
        target=_run_scrape,
        args=(keywords, locations, to_int(body.get("limit")), classify_backend, use_embeddings, require_login),
        daemon=True,
    )
    state.thread.start()
    return jsonify({"ok": True})



def _run_embed(limit, force):
    from .pipeline import run_embed_backfill
    try:
        run_embed_backfill(
            limit=limit,
            emit=state.emit,
            should_stop=lambda: state.stop_flag,
            force=force,
        )
    finally:
        from .runs import lock
        with lock:
            state.running = False
            state.stop_flag = False


@app.route("/api/embed", methods=["POST"])
def api_embed():
    if state.running:
        return jsonify({"ok": False, "error": "A scrape or backfill is already running."}), 400

    body = request.get_json(force=True, silent=True) or {}

    def to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    force = bool(body.get("force"))
    state.event_queue = queue.Queue()
    state.running = True
    state.stop_flag = False
    state.kind = "embed"
    state.last = {"state": "running", "embedded": 0, "skipped": 0, "total": 0}
    state.thread = threading.Thread(
        target=_run_embed, args=(to_int(body.get("limit")), force), daemon=True,
    )
    state.thread.start()
    return jsonify({"ok": True})


def _run_classify(backend, limit, model, force):
    from .pipeline import run_classify_backfill
    try:
        run_classify_backfill(
            backend=backend,
            limit=limit,
            model=model,
            emit=state.emit,
            should_stop=lambda: state.stop_flag,
            force=force,
        )
    finally:
        from .runs import lock
        with lock:
            state.running = False
            state.stop_flag = False


@app.route("/api/classify", methods=["POST"])
def api_classify():
    if state.running:
        return jsonify({"ok": False, "error": "A scrape or backfill is already running."}), 400

    body = request.get_json(force=True, silent=True) or {}
    backend = body.get("backend", "local")
    if backend not in ("local", "claude", "groq"):
        backend = "local"
    model = (body.get("model") or "").strip() or None

    def to_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    force = bool(body.get("force"))
    state.event_queue = queue.Queue()
    state.running = True
    state.stop_flag = False
    state.kind = "classify"
    state.last = {"state": "running", "classified": 0, "skipped": 0, "total": 0}
    state.thread = threading.Thread(
        target=_run_classify, args=(backend, to_int(body.get("limit")), model, force), daemon=True,
    )
    state.thread.start()
    return jsonify({"ok": True})


@app.route("/api/ollama/models")
def api_ollama_models():
    from .classify.local_llm import list_models

    try:
        models = list_models()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "default": config.OLLAMA_MODEL, "models": []})
    return jsonify({"ok": True, "models": models, "default": config.OLLAMA_MODEL})


@app.route("/api/scrape/stop", methods=["POST"])
def api_scrape_stop():
    if not state.running:
        return jsonify({"ok": False, "error": "No scrape running."}), 400
    state.stop_flag = True
    return jsonify({"ok": True})


@app.route("/api/scrape/status")
def api_scrape_status():
    return jsonify({"running": state.running, "kind": state.kind, **state.last})


@app.route("/events")
def events():
    try:
        initial_cursor = min(int(request.headers.get("Last-Event-ID", state.sequence)), state.sequence)
    except ValueError:
        initial_cursor = state.sequence
    def stream():
        cursor = initial_cursor
        while True:
            with state.condition:
                messages = [event for event in state.messages if event["id"] > cursor]
                if not messages:
                    state.condition.wait(timeout=15)
                    messages = [event for event in state.messages if event["id"] > cursor]
            if not messages:
                yield 'data: {"type":"heartbeat"}\n\n'
            for event in messages:
                cursor = event["id"]
                yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Past searches history API ---------------------------------------------

@app.route("/api/searches")
def api_searches():
    """Return list of past searches stored on disk."""
    import json
    from pathlib import Path
    out_dir = Path(config.ACCOUNTLESS_OUTPUT_DIR)
    results = []
    if out_dir.exists():
        for p in out_dir.iterdir():
            if p.is_dir():
                meta_file = p / "search.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        data["folder"] = p.name
                        data["hasLog"] = (p / "search.log").exists()
                        if not data.get("deletedAt"):
                            results.append(data)
                    except Exception:
                        pass
    results.sort(key=lambda x: x.get("startedAt", ""), reverse=True)
    return jsonify({"searches": results, "total": len(results)})


@app.route("/api/searches/<path:folder_name>/log")
def api_search_log(folder_name):
    """Return raw search.log content for inspection."""
    from pathlib import Path
    out_dir = Path(config.ACCOUNTLESS_OUTPUT_DIR).resolve()
    target = (out_dir / folder_name / "search.log").resolve()
    if not target.is_relative_to(out_dir):
        return jsonify({"ok": False, "error": "Geçersiz arama klasörü"}), 400
    if not target.exists():
        return jsonify({"ok": False, "error": "Bu arama için log dosyası bulunamadı."}), 404
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return jsonify({"ok": True, "log": content})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/searches/<path:folder_name>", methods=["DELETE"])
def api_search_delete(folder_name):
    """Delete a past search folder."""
    import shutil
    from pathlib import Path
    out_dir = Path(config.ACCOUNTLESS_OUTPUT_DIR).resolve()
    target = (out_dir / folder_name).resolve()
    if target == out_dir or not target.is_relative_to(out_dir):
        return jsonify({"ok": False, "error": "Invalid folder path"}), 400
    if target.exists() and target.is_dir():
        try:
            shutil.rmtree(target)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": False, "error": "Folder not found"}), 404


def create_app():
    init_db()
    if not state.running:
        from .runs import recover
        recover(SessionLocal)
    return app


from .enhanced import install
import sys
install(sys.modules[__name__])
from .service_api import install as install_service_api
install_service_api(sys.modules[__name__])
from .watches import install as install_watches
install_watches(sys.modules[__name__])
from .routine_cities import install as install_routine_cities
install_routine_cities(sys.modules[__name__])
from .titles import install as install_titles
install_titles(sys.modules[__name__])
from .logs_api import install as install_logs_api
install_logs_api(sys.modules[__name__])
from .dashboard import install as install_dashboard
install_dashboard(sys.modules[__name__])
