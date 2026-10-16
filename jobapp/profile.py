"""Stores the user's resume/profile text and its embedding (via ``embed.py``)
so ``/api/jobs?sort=fit`` can rank jobs by similarity to it. Persisted in the
``settings`` key/value table rather than the ``jobs`` table since it's a
single app-level value, not per-job data."""

import json

from .models import Setting

_KEY_TEXT = "profile_text"
_KEY_EMBEDDING = "profile_embedding"


def get_profile(session) -> dict:
    text_row = session.get(Setting, _KEY_TEXT)
    embedding_row = session.get(Setting, _KEY_EMBEDDING)
    embedding = None
    if embedding_row and embedding_row.value:
        try:
            embedding = json.loads(embedding_row.value)
        except (ValueError, TypeError):
            embedding = None
    return {
        "text": text_row.value if text_row else "",
        "embedding": embedding,
    }


def set_profile(session, text: str) -> bool:
    """Save the profile text and (re)compute its embedding. Returns whether
    the embedding succeeded (``False`` if Ollama was unreachable — the text
    is still saved either way)."""
    from . import embed

    text = (text or "").strip()
    text_row = session.get(Setting, _KEY_TEXT)
    if text_row is None:
        text_row = Setting(key=_KEY_TEXT, value=text)
        session.add(text_row)
    else:
        text_row.value = text

    vector = embed.embed_text(text) if text else None

    embedding_row = session.get(Setting, _KEY_EMBEDDING)
    embedding_value = json.dumps(vector) if vector is not None else ""
    if embedding_row is None:
        embedding_row = Setting(key=_KEY_EMBEDDING, value=embedding_value)
        session.add(embedding_row)
    else:
        embedding_row.value = embedding_value

    session.commit()
    return vector is not None
