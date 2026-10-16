"""Optional LLM classification via a local Ollama server.

Fully offline alternative to ``llm.py``'s Claude API call — no API key, no
per-job cost. Requires Ollama (https://ollama.com) running locally with
``config.OLLAMA_MODEL`` pulled. On any connection error, timeout, or bad
response it returns the rule-based result unchanged, so the pipeline never
breaks if Ollama isn't running.
"""

import json
import urllib.error
import urllib.request

from .. import config
from ._shared import INSTRUCTIONS, apply_fields, extract_json


def enrich(title: str, description: str, base: dict, model: str = None) -> dict:
    """Refine ``base`` (the rules result) with a local Ollama model."""
    job_text = f"TITLE: {title}\n\nDESCRIPTION:\n{(description or '')[:6000]}"
    payload = {
        "model": model or config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": job_text},
        ],
        "format": "json",
        "stream": False,
        # qwen3.5 is a hybrid-reasoning model that otherwise burns 10-15k
        # tokens of hidden "thinking" per job (~90s on CPU) before answering;
        # we only need the structured JSON, so turn that off.
        "think": False,
    }
    try:
        req = urllib.request.Request(
            f"{config.OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=config.OLLAMA_TIMEOUT_SECONDS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = body.get("message", {}).get("content", "")
        data = extract_json(text)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return base

    return apply_fields(base, data, "local", original_description=description)


def list_models() -> list:
    """Return the model names currently pulled in the local Ollama server.

    Raises on any connection error/timeout — callers decide how to degrade
    (e.g. server.py falls back to just the configured default)."""
    req = urllib.request.Request(f"{config.OLLAMA_HOST}/api/tags", method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return [m["name"] for m in body.get("models", []) if m.get("name")]
