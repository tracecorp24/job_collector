"""Alan adından LinkedIn'de aranacak unvan önerileri (Groq).

Yalnızca öneri üretir; tarama kuyruğu, bekleme ve hız sınırı politikası değişmez.
"""
import re
from flask import jsonify, request
from . import config, groq_client

MAX_FIELD, MAX_COUNT, MAX_TITLE = 120, 5, 80
PROMPT = (
    "Sen deneyimli bir teknik işe alım ve yetenek uzmanısın. Kullanıcı bir meslek alanı, teknoloji "
    "veya iş unvanı verecek. Bu alanla doğrudan ilgili, ancak birbiriyle çakışmayan (ortogonal), "
    "farklı uzmanlık ve rol ailelerini temsil eden tam {count} adet özgün LinkedIn arama unvanı üret.\n"
    "KRİTİK KURALLAR:\n"
    "1. Birbirinin kopyası, eş anlamlısı veya İngilizce-Türkçe çevirisi olan unvanları KESİNLİKLE birlikte üretme "
    "(Örn: 'Python Developer' ile 'Python Geliştirici' veya 'Data Analyst' ile 'Veri Analisti' gibi aynı unvanı "
    "farklı dilde veya sinonim kelimelerle tekrarlama).\n"
    "2. Her bir unvan o alanın farklı bir dalını, uzmanlığını veya rolünü hedeflemelidir (Örn: Veri için -> "
    "'Data Engineer', 'Machine Learning Engineer', 'BI Specialist', 'Data Analyst', 'Analytics Engineer' gibi).\n"
    "3. Kıdem (Junior/Senior/Lead vb.), şirket adı, konum veya açıklama ekleme; doğrudan saf unvan adı yaz.\n"
    "4. Yalnızca şu JSON formatında yanıt ver:\n"
    '{{"titles": ["...", "..."]}}'
)


class TitleError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _clean(titles, count):
    result, seen = [], set()
    for item in titles if isinstance(titles, list) else []:
        text = re.sub(r"\s+", " ", str(item or "")).strip(" \"'-•.0123456789)")
        if text and len(text) <= MAX_TITLE and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)
    return result[:count]


def suggest(field, count=5, post=None):
    field = re.sub(r"\s+", " ", str(field or "")).strip()
    if not field:
        raise TitleError("Önce bir alan yazın (örn. veri bilimi, elektrik mühendisliği).", 400)
    if len(field) > MAX_FIELD:
        raise TitleError(f"Alan en fazla {MAX_FIELD} karakter olabilir.", 400)
    if not config.GROQ_API_KEY:
        raise TitleError("Unvan önerisi için GROQ_API_KEY tanımlı değil.", 503)
    messages = [{"role": "system", "content": PROMPT.format(count=count)}, {"role": "user", "content": field}]
    try:
        data = groq_client.chat_json(messages, max_tokens=600, max_wait=15, post=post)
    except groq_client.GroqError as error:
        raise TitleError(f"Öneri alınamadı: {error}", error.status)
    titles = _clean(data.get("titles"), count)
    if not titles:
        raise TitleError("Öneri servisinden geçerli unvan alınamadı. Tekrar deneyin.")
    return titles


def install(server):
    app = server.app

    @app.post("/api/title-suggestions")
    def title_suggestions():
        data = request.get_json(silent=True) or {}
        try:
            count = max(1, min(MAX_COUNT, int(data.get("count") or 5)))
            return jsonify(ok=True, titles=suggest(data.get("field"), count))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="Unvan sayısı geçersiz."), 400
        except TitleError as error:
            return jsonify(ok=False, error=str(error)), error.status
