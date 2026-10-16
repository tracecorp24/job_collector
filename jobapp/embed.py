"""Optional local embeddings via Ollama, used for the "Find similar jobs" feature.

Requires Ollama (https://ollama.com) running locally with
``config.OLLAMA_EMBED_MODEL`` pulled. On any connection error, timeout, or bad
response ``embed_text`` returns ``None`` so callers can skip storing an
embedding without breaking the scrape pipeline.
"""

import json
import math
import urllib.error
import urllib.request

from . import config

_TIMEOUT_SECONDS = 30


def embed_text(text: str) -> list | None:
    payload = {
        "model": config.OLLAMA_EMBED_MODEL,
        "prompt": (text or "")[:8000],
    }
    try:
        req = urllib.request.Request(
            f"{config.OLLAMA_HOST}/api/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        vector = body.get("embedding")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None

    if not isinstance(vector, list) or not vector:
        return None
    return vector


def cosine_similarity(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_similar(target: list, candidates: list, limit: int = 6) -> list:
    """``candidates``: [(id, embedding), ...]. Returns [(id, score), ...] sorted desc."""
    scored = [(cid, cosine_similarity(target, vec)) for cid, vec in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]
