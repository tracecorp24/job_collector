"""Tek süreç için sınırlı bellekli Prometheus metrikleri; harici servis gerekmez."""
from collections import Counter, deque
import json
from pathlib import Path
import threading
import time

from flask import Response, g, request

_lock = threading.Lock()
_requests = Counter()
_search_seconds = deque(maxlen=512)
_source_429 = 0


def source_status(status):
    global _source_429
    if status == 429:
        with _lock:
            _source_429 += 1


def observe(response):
    started = getattr(g, "request_started_at", None)
    route = request.url_rule.rule if request.url_rule else "unmatched"
    with _lock:
        _requests[(route, request.method, response.status_code)] += 1
        if started is not None and route in ("/api/jobs", "/api/facets"):
            _search_seconds.append(max(0, time.perf_counter() - started))
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


def install(app, server):
    app.after_request(observe)

    @app.get("/metrics")
    def metrics():
        from sqlalchemy import text
        from . import config
        with _lock:
            requests = list(_requests.items())
            values = sorted(_search_seconds)
            source_429 = _source_429
        lines = ["# TYPE linko_http_requests_total counter"]
        for (route, method, status), count in requests:
            route = route.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'linko_http_requests_total{{route="{route}",method="{method}",status="{status}"}} {count}')
        p95 = values[min(len(values) - 1, int((len(values) - 1) * 0.95))] if values else 0
        lines.extend(["# TYPE linko_search_p95_seconds gauge", f"linko_search_p95_seconds {p95}",
                      "# TYPE linko_search_window_samples gauge", f"linko_search_window_samples {len(values)}",
                      "# TYPE linko_source_429_total counter", f"linko_source_429_total {source_429}"])
        with server.SessionLocal() as session:
            depth = session.execute(text("SELECT COUNT(*) FROM search_runs WHERE status='queued' AND deleted_at IS NULL")).scalar()
        lines.extend(["# TYPE linko_queue_depth gauge", f"linko_queue_depth {depth}",
                      "# TYPE linko_database_bytes gauge", f"linko_database_bytes {Path(config.DB_PATH).stat().st_size if Path(config.DB_PATH).is_file() else 0}"])
        try:
            backup = json.loads(Path(config.BACKUP_STATUS_PATH).read_text(encoding="utf-8"))
            age = max(0, time.time() - float(backup["at"]))
            lines.extend(["# TYPE linko_backup_age_seconds gauge", f"linko_backup_age_seconds {age}"])
        except (OSError, ValueError, KeyError, TypeError):
            lines.extend(["# TYPE linko_backup_age_seconds gauge", "linko_backup_age_seconds NaN"])
        return Response("\n".join(lines) + "\n", content_type="text/plain; version=0.0.4; charset=utf-8")
