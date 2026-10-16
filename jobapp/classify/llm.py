"""Optional LLM classification via the Claude API.

Only used when the caller passes ``use_llm=True``. Requires ``ANTHROPIC_API_KEY``
and the ``anthropic`` package; on any missing dependency, missing key, or API
error it returns the rule-based result unchanged so the pipeline never breaks.

Prompt caching is applied to the (static) instruction block so repeated
per-job calls reuse the cached prefix and stay cheap.
"""

from .. import config
from ._shared import INSTRUCTIONS, apply_fields, extract_json


def _client():
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
    except ImportError:
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
    except Exception:
        return base

    return apply_fields(base, data, "llm", original_description=description)
