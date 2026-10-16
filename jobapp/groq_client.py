"""Groq (OpenAI uyumlu) sohbet API'si için ortak istemci.

Ücretsiz katman dakikalık token ve günlük istek sınırı uygular. Yanıt başlıklarından kalan
kotayı izler: dakikalık kota bitmek üzereyse sıfırlanmasını bekler (en fazla `max_wait`
saniye), günlük kota bittiyse sıfırlanana kadar hiç istek göndermez. Anahtar yalnızca
`GROQ_API_KEY` ortam değişkeninden okunur.
"""
import json
import re
import threading
import time
import requests
from . import config

URL = "https://api.groq.com/openai/v1/chat/completions"
_lock = threading.Lock()
_quota = {"tokens_left": None, "tokens_reset_at": 0.0, "requests_left": None, "requests_reset_at": 0.0}


class GroqError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _seconds(value):
    """Groq sıfırlama süresi biçimleri: '7.66s', '2m59.56s', '1h2m3s', '120ms'."""
    if not value:
        return 0.0
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    total = 0.0
    for amount, unit in re.findall(r"([\d.]+)(ms|h|m|s)", text):
        total += float(amount) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


def _remember(headers, now):
    def number(name):
        try:
            return int(headers.get(name))
        except (TypeError, ValueError):
            return None
    with _lock:
        if number("x-ratelimit-remaining-tokens") is not None:
            _quota["tokens_left"] = number("x-ratelimit-remaining-tokens")
            _quota["tokens_reset_at"] = now + _seconds(headers.get("x-ratelimit-reset-tokens"))
        if number("x-ratelimit-remaining-requests") is not None:
            _quota["requests_left"] = number("x-ratelimit-remaining-requests")
            _quota["requests_reset_at"] = now + _seconds(headers.get("x-ratelimit-reset-requests"))


def _wait_for_quota(need, max_wait, sleep, clock):
    with _lock:
        quota = dict(_quota)
    now = clock()
    if quota["requests_left"] == 0 and quota["requests_reset_at"] > now:
        raise GroqError("Groq günlük istek kotası doldu; yarın tekrar denenecek.", 429)
    if quota["tokens_left"] is not None and quota["tokens_left"] < need and quota["tokens_reset_at"] > now:
        delay = quota["tokens_reset_at"] - now
        if delay > max_wait:
            raise GroqError("Groq dakikalık kotası dolu.", 429)
        sleep(delay + 0.2)


def chat(messages, model=None, max_tokens=800, max_wait=8.0, json_mode=True, post=None, sleep=time.sleep, clock=time.time):
    """Bir sohbet isteği gönderir ve modelin metin yanıtını döndürür.

    `max_wait`: kota beklemesi için en fazla bekleme. Tarama sırasında kısa tutulur (tarama
    yavaşlamasın, iş kurallara düşsün); toplu analizde uzun tutulur (kota açılınca devam eder)."""
    if not config.GROQ_API_KEY:
        raise GroqError("GROQ_API_KEY tanımlı değil.", 503)
    post = post or requests.post
    body = {"model": model or config.GROQ_MODEL, "messages": messages, "temperature": 0.2,
            "max_completion_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if str(body["model"]).startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"  # Gizli düşünme token'larını azaltır; kota daha çok işe yeter.
    need = max_tokens + sum(len(m.get("content", "")) for m in messages) // 3
    for attempt in range(3):
        _wait_for_quota(need, max_wait, sleep, clock)
        try:
            response = post(URL, json=body, timeout=60, headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"})
        except requests.RequestException:
            raise GroqError("Groq servisine ulaşılamadı.")
        _remember(response.headers or {}, clock())
        if response.status_code == 429:
            delay = _seconds((response.headers or {}).get("retry-after")) or 10.0
            if attempt == 2 or delay > max_wait:
                raise GroqError("Groq kotası şu an dolu. Biraz sonra tekrar deneyin.", 429)
            sleep(delay)
            continue
        if response.status_code != 200:
            raise GroqError(f"Groq hata döndürdü ({response.status_code}).")
        try:
            return response.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise GroqError("Groq yanıtı okunamadı.")
    raise GroqError("Groq kotası şu an dolu.", 429)


def chat_json(messages, **kwargs):
    content = chat(messages, **kwargs)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    try:
        return json.loads(match.group(0)) if match else {}
    except ValueError:
        return {}
