"""Deterministic parsing of the free-text ``salary`` field into a sortable
numeric range.

The ``salary`` column already holds LLM-produced free text (e.g. ``"$80k-100k"``,
``"25.000-30.000 TL"``, ``"45000 TRY/month"``) — the input pattern space is
small and bounded, so a regex parser is more reliable than asking an LLM to
also get numeric formatting right, and it's free (no extra API/Ollama call).
"""

import re

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₺": "TRY"}
_CURRENCY_WORDS = {
    "usd": "USD", "dollars": "USD", "dollar": "USD",
    "eur": "EUR", "euros": "EUR", "euro": "EUR",
    "gbp": "GBP", "pounds": "GBP", "pound": "GBP",
    "try": "TRY", "tl": "TRY", "lira": "TRY",
}
_PERIOD_HINTS = [
    ("year", [r"/\s*y(e|i)ar", r"/\s*yr", r"per year", r"y[ıi]ll[ıi]k", r"/\s*year"]),
    ("month", [r"/\s*mo(nth)?\b", r"per month", r"ayl[ıi]k"]),
    ("hour", [r"/\s*h(ou)?r\b", r"per hour", r"saatlik"]),
]

_NUM_RE = r"(\d[\d.,]*)\s*(k)?"


def _to_number(digits: str, has_k: bool) -> float:
    # Ambiguous between thousands-groupings ("25.000" Turkish, "25,000" US,
    # "87,400.00" US-with-cents, "25.000,50" European) since both '.' and ','
    # are used as either separator depending on locale. Heuristic: the LAST
    # '.'/',' in the string is the decimal point only if 1-2 digits follow it
    # (i.e. looks like cents); a trailing group of exactly 3 digits is a
    # thousands group, not decimals. Every other separator is a thousands
    # marker and gets stripped.
    cleaned = digits
    last_sep = max(cleaned.rfind("."), cleaned.rfind(","))
    if last_sep != -1:
        frac = cleaned[last_sep + 1:]
        int_part = cleaned[:last_sep]
        if len(frac) in (1, 2):
            cleaned = re.sub(r"[.,]", "", int_part) + "." + frac
        else:
            cleaned = re.sub(r"[.,]", "", cleaned)
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if has_k:
        value *= 1000
    return value


def _detect_currency(text: str) -> str:
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    lowered = text.lower()
    for word, code in _CURRENCY_WORDS.items():
        if re.search(r"\b" + re.escape(word) + r"\b", lowered):
            return code
    return ""


def _detect_period(text: str) -> str:
    lowered = text.lower()
    for period, patterns in _PERIOD_HINTS:
        for pat in patterns:
            if re.search(pat, lowered):
                return period
    return ""


def parse_salary(raw: str) -> dict:
    """Parse a free-text salary string into a numeric range.

    Returns ``{"min": float|None, "max": float|None, "currency": str, "period": str}``.
    Never raises; returns all-empty/None on anything it can't confidently parse.
    """
    empty = {"min": None, "max": None, "currency": "", "period": ""}
    text = (raw or "").strip()
    if not text:
        return empty

    numbers = list(re.finditer(_NUM_RE, text, re.IGNORECASE))
    if not numbers:
        return empty

    values = []
    for m in numbers:
        val = _to_number(m.group(1), bool(m.group(2)))
        if val is not None:
            values.append(val)
    if not values:
        return empty

    currency = _detect_currency(text)
    period = _detect_period(text)

    if len(values) == 1:
        return {"min": values[0], "max": values[0], "currency": currency, "period": period}

    low, high = min(values[:2]), max(values[:2])
    return {"min": low, "max": high, "currency": currency, "period": period}
