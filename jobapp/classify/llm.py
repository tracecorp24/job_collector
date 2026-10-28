"""Optional LLM classification via the Claude API.

Only used when the caller passes ``use_llm=True``. Requires ``ANTHROPIC_API_KEY``
and the ``anthropic`` package; on any missing dependency, missing key, or API
error it returns the rule-based result unchanged so the pipeline never breaks.

Prompt caching is applied to the (static) instruction block so repeated
per-job calls reuse the cached prefix and stay cheap.
"""

import logging
from functools import lru_cache

from .. import config
from ._shared import INSTRUCTIONS, apply_fields, extract_json

log = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _warn_unavailable(reason):
    # Aynı eksik ayar için her ilanda tekrar uyarı üretme.
    log.warning("Claude sınıflandırması kullanılamıyor: %s; kural sonucu korunuyor.", reason)


def _client():
    if not config.ANTHROPIC_API_KEY:
        _warn_unavailable("ANTHROPIC_API_KEY ayarlanmamış")
        return None
    try:
        import anthropic
    except ImportError:
        _warn_unavailable("anthropic paketi kurulu değil")
        return None
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def enrich(title: str, description: str, base: dict) -> dict:
    """Refine ``base`` (the rules result) with Claude; fall back on any failure."""
    client = _client()
    if client is None:
        return base

    job_text = f"TITLE: {title}\n\nDESCRIPTION:\n{(description or '')[:6000]}"
    try:
        resp = client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=3000,
            system=[{
                "type": "text",
                "text": INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": job_text}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        data = extract_json(text)
    except Exception as exc:
        # Sağlayıcı yanıtı, ilan metni ve anahtarlar loga taşınmaz.
        log.warning("Claude yanıtı işlenemedi (%s); kural sonucu korunuyor.", type(exc).__name__)
        return base

    return apply_fields(base, data, "llm", original_description=description)
