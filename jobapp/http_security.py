"""Her yönetim isteğinde anahtar doğrulama ve sınırlı IP başına token bütçesi."""
from collections import OrderedDict
import hmac
import ipaddress
import math
import threading
import time
from urllib.parse import urlsplit

from flask import g, jsonify, request
from . import config

RATE = 30
BURST = 60
_buckets = OrderedDict()
_lock = threading.Lock()


def client_ip():
    peer = request.remote_addr or "unknown"
    if peer in ("127.0.0.1", "::1"):
        # Caddy bu başlığı istemci değerinden bağımsız olarak yeniden yazar.
        try:
            return str(ipaddress.ip_address(request.headers.get("X-Real-IP", "")))
        except ValueError:
            pass
    return peer


def consume(address, now=None):
    now = time.monotonic() if now is None else now
    with _lock:
        tokens, previous = _buckets.pop(address, (float(BURST), now))
        tokens = min(BURST, tokens + max(0, now - previous) * RATE)
        allowed = tokens >= 1
        _buckets[address] = (tokens - 1 if allowed else tokens, now)
        while len(_buckets) > 16384:
            _buckets.popitem(last=False)
    return allowed, max(1, math.ceil((1 - tokens) / RATE)) if not allowed else 0


def authorize():
    g.request_started_at = time.perf_counter()
    if request.path in ("/", "/healthz") and request.method in ("GET", "HEAD"):
        return None
    versioned = request.path.startswith("/api/v1/")
    allowed = [config.API_KEY, config.ADMIN_KEY] if versioned and request.method in ("GET", "HEAD") else [config.ADMIN_KEY]
    if request.path.startswith(("/api/v1/logs", "/api/v1/incidents")) or request.path == "/metrics":
        allowed.append(config.LOG_KEY)
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not any(key and hmac.compare_digest(supplied, key) for key in allowed):
        return jsonify(error="Geçerli Bearer anahtarı gerekli.", code="unauthorized"), 401
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            safe = parsed.scheme in ("http", "https") and parsed.netloc.casefold() == request.host.casefold()
        else:
            safe = request.headers.get("Sec-Fetch-Site") == "same-origin"
        if not safe:
            return jsonify(error="Yönetim isteği aynı kaynaktan gelmeli."), 403
    accepted, retry = consume(client_ip())
    if not accepted:
        response = jsonify(error="İstek hızı sınırı aşıldı.", code="rate_limited")
        response.headers["Retry-After"] = str(retry)
        return response, 429
    return None
