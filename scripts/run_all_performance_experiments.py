import os
import sys
import time
import json
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

all_results = {
    "timestamp": time.time(),
    "date": time.strftime("%Y-%m-%d %H:%M:%S"),
    "experiment_1_waf_tuning": {},
    "experiment_2_inline_details": {},
    "experiment_3_queue_multitask": {},
}

session = requests.Session()
session.headers.update(HEADERS)

print("=" * 70)
print("LINKO SCRAPPER LIGHT — KAPSAMLI PERFORMANS VE LİMİT DENEYLERİ")
print("=" * 70)

# ==============================================================================
# DENEY 1: MİLİMETRİK WAF EŞİK TESTİ (9s, 8s, 7s, 6s)
# ==============================================================================
print("\n" + "=" * 70)
print(">>> DENEY 1: MİLİMETRİK WAF EŞİK VE HIZ SINIRI TESTİ")
print("Amaç: 10s'nin altındaki bekleme sürelerinde (9.0s, 8.0s, 7.0s, 6.0s)")
print("      LinkedIn WAF'ının (Cloudflare) 429 tetikleme eşiğini bulmak.")
print("=" * 70 + "\n")

intervals = [9.0, 8.0, 7.0, 6.0]
exp1_results = {}

for interval in intervals:
    print(f"\n--- Test Aralığı: {interval} saniye ---")
    interval_data = []
    
    # 2 ardışık istek atalım
    for step in range(2):
        t0 = time.time()
        try:
            params = {"keywords": "Yazılım", "location": "Turkey", "start": step * 10}
            resp = session.get(SEARCH_URL, params=params, timeout=15)
            dur = round(time.time() - t0, 2)
            status = resp.status_code
            retry_after = resp.headers.get("retry-after")
            print(f"  [İstek #{step+1}] HTTP {status} | Süre: {dur}s | Boyut: {len(resp.content)}B | Retry-After: {retry_after}")
            interval_data.append({
                "step": step + 1,
                "status": status,
                "duration": dur,
                "bytes": len(resp.content),
                "retry_after": retry_after
            })
        except Exception as e:
            print(f"  [İstek #{step+1}] HATA: {e}")
            interval_data.append({"step": step + 1, "error": str(e)})
        
        if step == 0:
            print(f"  -> {interval}s mola bekleniyor...")
            time.sleep(interval)
            
    exp1_results[f"{interval}s"] = interval_data
    # Kademeler arasında WAF sıfırlansın diye 12s dinlenme verelim
    print("  -> WAF sayaç rahatlaması için 12s mola...")
    time.sleep(12.0)

all_results["experiment_1_waf_tuning"] = exp1_results

# ==============================================================================
# DENEY 2: CANLI INLINE HAFİF DETAY ÇEKİM BENCHMARK'I
# ==============================================================================
print("\n" + "=" * 70)
print(">>> DENEY 2: CANLI INLINE HAFİF DETAY ÇEKİM BENCHMARK'I")
print("Amaç: İlan kartı gelir gelmez Hafif API ile anında detay çekmenin")
print("      süresi, veri boyutu (KB) ve açıklama tamlığı ölçümü.")
print("=" * 70 + "\n")

# Canlı 4 adet ilan bulalım
search_resp = session.get(SEARCH_URL, params={"keywords": "Proje Yöneticisi", "location": "Turkey", "start": 0}, timeout=15)
soup = BeautifulSoup(search_resp.text, "html.parser")
cards = soup.select("div.base-search-card")

sample_jobs = []
for c in cards[:4]:
    urn = c.get("data-entity-urn") or ""
    jid = urn.split(":")[-1] if ":" in urn else ""
    title_el = c.select_one(".base-search-card__title")
    title = title_el.get_text(strip=True) if title_el else "Bilinmiyor"
    company_el = c.select_one(".base-search-card__subtitle")
    company = company_el.get_text(strip=True) if company_el else "Bilinmiyor"
    if jid:
        sample_jobs.append({"id": jid, "title": title, "company": company})

print(f"{len(sample_jobs)} adet ilan için anlık Hafif Detay API testi başlıyor...\n")

exp2_results = []
t_exp2_start = time.time()
for idx, job in enumerate(sample_jobs):
    jid = job["id"]
    t0 = time.time()
    resp = session.get(DETAIL_API_URL.format(jid), timeout=15)
    dur = round(time.time() - t0, 2)
    
    desc_len = 0
    desc_preview = ""
    if resp.status_code == 200:
        d_soup = BeautifulSoup(resp.text, "html.parser")
        box = d_soup.select_one(".show-more-less-html__markup, .description__text")
        if box:
            text = box.get_text("\n", strip=True)
            desc_len = len(text)
            desc_preview = text[:90].replace("\n", " ")
            
    print(f"[{idx+1}/{len(sample_jobs)}] #{jid} - {job['title']} ({job['company']})")
    print(f"    HTTP {resp.status_code} | Süre: {dur}s | Boyut: {len(resp.content):,} bayt | Açıklama: {desc_len} karakter")
    if desc_preview:
        print(f"    Özet: {desc_preview}...")
        
    exp2_results.append({
        "job_id": jid,
        "title": job["title"],
        "company": job["company"],
        "status": resp.status_code,
        "duration": dur,
        "bytes": len(resp.content),
        "desc_chars": desc_len
    })
    
    if idx < len(sample_jobs) - 1:
        time.sleep(10.0) # Güvenli 10s aralık

exp2_total_dur = round(time.time() - t_exp2_start, 2)
all_results["experiment_2_inline_details"] = {
    "total_duration": exp2_total_dur,
    "jobs": exp2_results
}

# ==============================================================================
# DENEY 3: ÇOKLU GÖREV KUYRUĞU VE GEÇİŞ PERFORMANSI BENCHMARK'I
# ==============================================================================
print("\n" + "=" * 70)
print(">>> DENEY 3: ÇOKLU GÖREV KUYRUĞU VE GÖREV GEÇİŞ PERFORMANSI TESTİ")
print("Amaç: 3 farklı unvan ('Veri Analisti', 'Sistem Mühendisi', 'İş Analisti')")
print("      peş peşe kuyrukta koşturulurken görev geçiş hızı ve DB performansı.")
print("=" * 70 + "\n")

print("WAF sayaç temizliği için 15s dinlenme molası...")
time.sleep(15.0)

qa_dir = ROOT / ".qa" / "multitask_test"
qa_dir.mkdir(parents=True, exist_ok=True)
os.environ["JOBAPP_DB_PATH"] = str(qa_dir / "benchmark.db")
os.environ["JOBAPP_ACCOUNTLESS_OUTPUT_DIR"] = str(qa_dir / "searches")

from jobapp import pipeline, db
db.init_db()

queue_events = []
def on_event(kind, data):
    queue_events.append((kind, time.time(), data))
    if kind == "task_start":
        print(f"🚀 [KUYRUK GÖREV BAŞLADI] '{data.get('keyword')}' (Hedef: {data.get('limit')} ilan)")
    elif kind == "task_done":
        print(f"✅ [KUYRUK GÖREV BİTTİ] '{data.get('keyword')}' | Toplanan: {data.get('count')} | Sebep: {data.get('reason')}")
    elif kind == "job":
        print(f"   ⭐ İlan: #{data.get('id')} - {data.get('title')} ({data.get('company')})")

multi_queue = [
    {"keyword": "Veri Analisti", "location": "Turkey", "limit": 2},
    {"keyword": "Sistem Mühendisi", "location": "Turkey", "limit": 2},
    {"keyword": "İş Analisti", "location": "Turkey", "limit": 2}
]

t_exp3_start = time.time()
stats = pipeline.run_scrape(
    keywords=multi_queue,
    locations=["Turkey"],
    emit=on_event,
    mode="full", # Detayları hemen çek
    search_options={"stop_when_known": False, "defer_details": False}
)
exp3_total_dur = round(time.time() - t_exp3_start, 2)

all_results["experiment_3_queue_multitask"] = {
    "total_duration": exp3_total_dur,
    "collected": stats.get("collected", 0),
    "created": stats.get("created", 0),
    "updated": stats.get("updated", 0),
    "paused": stats.get("paused", False),
    "total_events": len(queue_events)
}

# Sonuçları JSON dosyasına kaydedelim
out_json = ROOT / ".qa" / "performance_experiments_summary.json"
out_json.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
print("\n" + "=" * 70)
print(f"TÜM DENEYLER TAMAMLANDI! Sonuçlar kaydedildi: {out_json}")
print("=" * 70)
