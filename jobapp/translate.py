"""Isolated, non-breaking translation service for job postings.

Translates ONLY the job's title, description, and summary to Turkish.
Keeps UI, metadata, company names, URLs and tags completely untouched.
Includes thread-safe in-memory caching to eliminate redundant external requests.
"""

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)

# Thread-safe in-memory cache for translations: key = (text, target_lang)
_CACHE: Dict[str, str] = {}
_CACHE_LOCK = threading.Lock()
_MAX_CACHE_ENTRIES = 5000

# Endpoint for fast, free client-agnostic translation
_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target}&dt=t&q={text}"


def _clean_text(text: Optional[str]) -> str:
    return (text or "").strip()


def translate_text(text: str, target: str = "tr") -> str:
    """Translates a text block into the target language, preserving paragraph breaks."""
    text = _clean_text(text)
    if not text:
        return ""

    # Check cache first
    cache_key = f"{target}::{hash(text)}::{text[:64]}"
    with _CACHE_LOCK:
        if cache_key in _CACHE:
            return _CACHE[cache_key]

    paragraphs = text.split("\n")
    translated_paras = []
    chunk = []
    chunk_len = 0

    for p in paragraphs:
        # Keep chunk size under 1500 chars to avoid URL length constraints
        if chunk_len + len(p) > 1400 and chunk:
            c_text = "\n".join(chunk)
            translated_paras.append(_fetch_translation(c_text, target))
            chunk = [p]
            chunk_len = len(p)
        else:
            chunk.append(p)
            chunk_len += len(p)

    if chunk:
        c_text = "\n".join(chunk)
        translated_paras.append(_fetch_translation(c_text, target))

    result = "\n".join(translated_paras)

    # Save to cache
    with _CACHE_LOCK:
        if len(_CACHE) >= _MAX_CACHE_ENTRIES:
            _CACHE.clear()
        _CACHE[cache_key] = result

    return result


def _fetch_translation(chunk_text: str, target: str) -> str:
    if not chunk_text.strip():
        return chunk_text
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target}&dt=t&q={urllib.parse.quote(chunk_text)}"
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and data and isinstance(data[0], list):
                return "".join([part[0] for part in data[0] if part and len(part) > 0 and part[0]])
    except Exception as exc:
        log.warning("Çeviri isteği başarısız oldu: %s", exc)
        return chunk_text
    return chunk_text


def translate_job_fields(job_dict: Dict[str, Any], target: str = "tr") -> Dict[str, Any]:
    """Translates only title, description, and summary of a job dictionary."""
    orig_title = job_dict.get("title") or ""
    orig_desc = job_dict.get("formatted_description") or job_dict.get("description") or ""
    orig_summary = job_dict.get("summary") or ""

    trans_title = translate_text(orig_title, target=target) if orig_title else ""
    trans_desc = translate_text(orig_desc, target=target) if orig_desc else ""
    trans_summary = translate_text(orig_summary, target=target) if orig_summary else ""

    return {
        "ok": True,
        "job_id": job_dict.get("id"),
        "title": trans_title or orig_title,
        "description": trans_desc or orig_desc,
        "summary": trans_summary or orig_summary,
        "original_title": orig_title,
        "original_description": orig_desc,
        "original_summary": orig_summary,
        "target_lang": target
    }
