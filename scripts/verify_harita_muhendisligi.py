import sys
sys.stdout.reconfigure(encoding='utf-8')
import time
import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_API_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

session = requests.Session()
session.headers.update(HEADERS)

print("=== CANLI DOGRULAMA TESTI: 'HARITA MUHENDISLIGI' ===")
print("1. Asama: LinkedIn'de 'harita muhendisligi' aramasi yapiliyor...\n")

params = {"keywords": "harita mühendisliği", "location": "Turkey", "start": 0}
r = session.get(SEARCH_URL, params=params, timeout=20)

if r.status_code != 200:
    print(f"Arama hatasi: HTTP {r.status_code}")
    sys.exit(1)

soup = BeautifulSoup(r.text, "html.parser")
cards = soup.select("div.base-search-card")
print(f"[OK] {len(cards)} adet 'Harita Muhendisligi' ilan karti bulundu!\n")

jobs = []
for c in cards[:5]:
    urn = c.get("data-entity-urn") or ""
    job_id = urn.split(":")[-1] if ":" in urn else ""
    title_elem = c.select_one(".base-search-card__title")
    comp_elem = c.select_one(".base-search-card__subtitle")
    loc_elem = c.select_one(".job-search-card__location")
    
    title = title_elem.get_text(strip=True) if title_elem else "Bilinmiyor"
    company = comp_elem.get_text(strip=True) if comp_elem else "Bilinmiyor"
    location = loc_elem.get_text(strip=True) if loc_elem else "Bilinmiyor"
    
    if job_id:
        jobs.append({"id": job_id, "title": title, "company": company, "location": location})

print("Bulunan Ilanlar:")
for idx, j in enumerate(jobs):
    print(f"  [{idx+1}] ID: {j['id']} | {j['company']} - {j['title']} ({j['location']})")

print("\n" + "="*60)
print("2. Asama: Yeni Kesfedilen Hafif Misafir API'si ile Detay Cekme Testi")
print(f"Uc Nokta: {DETAIL_API_URL}")
print("="*60 + "\n")

# Ilk 2 ilanin detayini yeni API ile cekip test edelim
for idx, j in enumerate(jobs[:2]):
    job_id = j["id"]
    api_url = DETAIL_API_URL.format(job_id)
    
    print(f"[{idx+1}/2] Ilan: {j['company']} - {j['title']}")
    print(f"  -> Istek URL: {api_url}")
    
    t0 = time.time()
    res = session.get(api_url, timeout=20)
    dur = round(time.time() - t0, 2)
    
    print(f"  -> HTTP Durumu: {res.status_code}")
    print(f"  -> Yanit Suresi: {dur} saniye")
    print(f"  -> Yanit Boyutu: {len(res.content)} bayt ({round(len(res.content)/1024, 1)} KB)")
    
    if res.status_code == 200:
        d_soup = BeautifulSoup(res.text, "html.parser")
        box = d_soup.select_one(".show-more-less-html__markup, .description__text")
        if box:
            desc = box.get_text("\n", strip=True)
            print(f"  -> Aciklama Basariyla Cekildi! (Toplam {len(desc)} karakter)")
            print(f"  -> Ilan Aciklamasi Baslangici:\n{'-'*50}")
            print(desc[:300] + "...\n" + "-"*50)
        else:
            print("  [UYARI] Aciklama kutusu bulunamadi!")
            
    if idx < 1:
        print("10.5 saniye guvenli mola bekleniyor...")
        time.sleep(10.5)

print("\n[TAMAMLANDI] Harita muhendisligi dogrulama testi basariyla bitti!")
