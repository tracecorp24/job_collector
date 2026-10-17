import os
import sys
import time
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_API_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"

print("=" * 60)
print("HAFİF API COLLECTOR — LİMİT VE KUYRUK HABERLEŞME TESTİ")
print("=" * 60)

# ==============================================================================
# BÖLÜM 1: Hafif API Pacing ve Hız Limitleri Testi
# ==============================================================================
print("\n--- BÖLÜM 1: Hafif API (jobPosting) Hız Sınırı Testi ---")
print("Amaç: Hafif API ile istek aralığını 10s'den daha aşağıya (örn: 5s ve 3s) çekebilir miyiz?\n")

session = requests.Session()
session.headers.update(HEADERS)

# Canlı ilan ID'leri alalım
params = {"keywords": "Harita Mühendisi", "location": "Turkey", "start": 0}
r = session.get(SEARCH_URL, params=params, timeout=20)
if r.status_code != 200:
    print(f"Arama başlatılamadı: HTTP {r.status_code}")
    sys.exit(1)

soup = BeautifulSoup(r.text, "html.parser")
cards = soup.select("div.base-search-card")
job_ids = []
for c in cards:
    urn = c.get("data-entity-urn") or ""
    if ":" in urn:
        jid = urn.split(":")[-1]
        if jid:
            job_ids.append(jid)

print(f"Test için {len(job_ids)} adet canlı ilan kimliği tespit edildi.")
sample_ids = job_ids[:4]
print(f"Örnek ID'ler: {sample_ids}\n")

# Test 1: 5.0 saniye aralıkla 2 istek
print("[Test 1.1] 5.0 saniye aralıkla hafif API isteği gönderiliyor...")
for i, jid in enumerate(sample_ids[:2]):
    t0 = time.time()
    resp = session.get(DETAIL_API_URL.format(jid), timeout=15)
    dur = round(time.time() - t0, 2)
    print(f"  -> İstek #{i+1} (ID: {jid}): HTTP {resp.status_code} | Boyut: {len(resp.content)}B | Süre: {dur}s")
    if i == 0:
        print("  -> 5.0s bekleniyor...")
        time.sleep(5.0)

# 10s güvenlik molası
print("\n[Güvenlik Molası] 10s mola...")
time.sleep(10.0)

# Test 2: 3.0 saniye aralıkla 2 istek
print("\n[Test 1.2] 3.0 saniye aralıkla hafif API isteği gönderiliyor...")
for i, jid in enumerate(sample_ids[2:4]):
    t0 = time.time()
    resp = session.get(DETAIL_API_URL.format(jid), timeout=15)
    dur = round(time.time() - t0, 2)
    print(f"  -> İstek #{i+1} (ID: {jid}): HTTP {resp.status_code} | Boyut: {len(resp.content)}B | Süre: {dur}s")
    if i == 0:
        print("  -> 3.0s bekleniyor...")
        time.sleep(3.0)

# ==============================================================================
# BÖLÜM 2: Uçtan Uca Kuyruk ve Haberleşme Protokolü Testi
# ==============================================================================
print("\n" + "=" * 60)
print("--- BÖLÜM 2: Kuyruk Protokolü ve Pipeline Entegrasyon Testi ---")
print("Amaç: Sistem haberleşme protokolü (SSE emit olayları, görev geçişleri,")
print("      Hafif API detay çekimi ve DB upsert) kuyruk altında nasıl çalışıyor?")
print("=" * 60 + "\n")

print("WAF penceresi için 15 saniye dinlenme molası veriliyor...")
time.sleep(15.0)

qa_dir = ROOT / ".qa" / "queue_test"
qa_dir.mkdir(parents=True, exist_ok=True)
os.environ["JOBAPP_DB_PATH"] = str(qa_dir / "test_queue.db")
os.environ["JOBAPP_ACCOUNTLESS_OUTPUT_DIR"] = str(qa_dir / "searches")

from jobapp import pipeline, db
db.init_db()

events_log = []
def capture_event(kind, data):
    events_log.append((kind, data))
    if kind == "task_start":
        print(f"📡 [EVENT: task_start] Görev Başladı: '{data.get('keyword')}' | Hedef: {data.get('limit')} ilan")
    elif kind == "task_done":
        print(f"📡 [EVENT: task_done] Görev Bitti: '{data.get('keyword')}' | Toplanan: {data.get('count')} ilan | Sebep: {data.get('reason')}")
    elif kind == "request_started":
        url = data.get("url", "")
        short_url = url.split("?")[0]
        print(f"  🌐 [HTTP Req #{data.get('request_number')}] {short_url}")
    elif kind == "request_finished":
        dur = data.get("duration_ms")
        bytes_len = data.get("response_bytes", 0)
        status = data.get("status")
        print(f"  ⬅️ [HTTP Resp #{data.get('request_number') or ''}] Durum: {status} | Süre: {dur}ms | Boyut: {bytes_len} bayt")
    elif kind == "job":
        print(f"    ⭐ [İLAN KAYDEDİLDİ] #{data.get('id')} - {data.get('title')} ({data.get('company')})")
    elif kind == "source_paused":
        print(f"  ⚠️ [KAYNAK DURAKLADI] {data.get('reason')} - Kalan süre: {data.get('remaining_seconds')}s")

# 2 görevli gerçek kuyruk: Harita Mühendisi (limit=2), Geomatik Mühendisi (limit=2)
search_queue = [
    {"keyword": "Harita Mühendisi", "location": "Turkey", "limit": 2},
    {"keyword": "Geomatik Mühendisi", "location": "Turkey", "limit": 2}
]

print("Kuyruk başlatılıyor (2 görev, her biri 2 ilan limiti)...")
t_start = time.time()
stats = pipeline.run_scrape(
    keywords=search_queue,
    locations=["Turkey"],
    emit=capture_event,
    mode="full",
    search_options={"stop_when_known": False, "defer_details": False}
)
total_dur = round(time.time() - t_start, 2)

print("\n" + "=" * 60)
print("--- KUYRUK ÇALIŞMA SONUCU ---")
print("=" * 60)
print(f"Toplam Süre: {total_dur} saniye")
print(f"Toplanan İlan: {stats.get('collected', 0)}")
print(f"İşlenen/Kaydedilen İlan: {stats.get('created', 0) + stats.get('updated', 0)}")
print(f"Duraklatıldı mı: {stats.get('paused', False)}")
print(f"Olay Sayısı (Events): {len(events_log)}")
print("\nTest Başarıyla Tamamlandı!")
