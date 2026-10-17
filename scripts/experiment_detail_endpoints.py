import time
import requests
from bs4 import BeautifulSoup

JOB_ID = "4446487195" # Fresh live job from Deney 2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

session = requests.Session()
session.headers.update(HEADERS)

endpoints = [
    {
        "name": "Standart Misafir Detay Sayfası (/jobs/view/<id>)",
        "url": f"https://www.linkedin.com/jobs/view/{JOB_ID}"
    },
    {
        "name": "Guest API jobPosting (/jobs-guest/jobs/api/jobPosting/<id>)",
        "url": f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{JOB_ID}"
    },
    {
        "name": "Guest API jobDetail (/jobs-guest/jobs/api/jobDetail/<id>)",
        "url": f"https://www.linkedin.com/jobs-guest/jobs/api/jobDetail/{JOB_ID}"
    },
    {
        "name": "Guest API jobCard (/jobs-guest/jobs/api/jobCard/{JOB_ID})",
        "url": f"https://www.linkedin.com/jobs-guest/jobs/api/jobCard/{JOB_ID}"
    },
    {
        "name": "Guest API jobPostings (/jobs-guest/jobs/api/jobPostings/{JOB_ID})",
        "url": f"https://www.linkedin.com/jobs-guest/jobs/api/jobPostings/{JOB_ID}"
    }
]

print("=== DENEY 3B: ALTERNATİF DETAY VE AÇIKLAMA (DESCRIPTION) UÇ NOKTASI TESTİ ===")
print(f"Hedef İlan ID: {JOB_ID}\n")

results = []

for i, ep in enumerate(endpoints):
    name = ep["name"]
    url = ep["url"]
    print(f"[{i+1}/{len(endpoints)}] Test: {name} -> {url}")
    t0 = time.time()
    try:
        r = session.get(url, timeout=15)
        dur = round(time.time() - t0, 2)
        has_desc = False
        desc_len = 0
        desc_preview = ""
        
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            box = soup.select_one(".show-more-less-html__markup, .description__text, .decoratedJobPosting")
            if box:
                text = box.get_text(strip=True)
                has_desc = bool(text)
                desc_len = len(text)
                desc_preview = text[:80]
        
        print(f"  -> HTTP {r.status_code} | Süre: {dur}s | Boyut: {len(r.content)}B | Açıklama Var mı: {has_desc} ({desc_len} karakter)")
        if desc_preview:
            print(f"  -> Önizleme: {desc_preview}...")
            
        results.append({
            "name": name,
            "url": url,
            "status": r.status_code,
            "duration": dur,
            "size": len(r.content),
            "has_description": has_desc,
            "desc_len": desc_len
        })
    except Exception as e:
        print(f"  -> Hata: {e}")
        results.append({"name": name, "error": str(e)})

    if i < len(endpoints) - 1:
        time.sleep(10.5)

print("\n--- ÖZET SONUÇLAR ---")
for res in results:
    print(f"• {res['name']}: HTTP {res.get('status')} | Boyut: {res.get('size')}B | Açıklama: {res.get('has_description')} ({res.get('desc_len')} kar.)")
