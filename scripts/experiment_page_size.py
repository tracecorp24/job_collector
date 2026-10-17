import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

test_variations = [
    {"name": "Varsayılan (Parametresiz)", "params": {"keywords": "Python", "location": "Istanbul, Turkey", "start": 0}},
    {"name": "count=25", "params": {"keywords": "Python", "location": "Istanbul, Turkey", "start": 0, "count": 25}},
    {"name": "count=50", "params": {"keywords": "Python", "location": "Istanbul, Turkey", "start": 0, "count": 50}},
    {"name": "num=25", "params": {"keywords": "Python", "location": "Istanbul, Turkey", "start": 0, "num": 25}},
    {"name": "size=50", "params": {"keywords": "Python", "location": "Istanbul, Turkey", "start": 0, "size": 50}},
]

results = []
session = requests.Session()
session.headers.update(HEADERS)

print("=== DENEY 1: SAYFA BAŞINA KART SAYISI (PAGE SIZE / COUNT) TESTİ ===")
print("İstekler arasında 10 saniye beklenerek WAF tetiklenmeyecektir.\n")

for i, test in enumerate(test_variations):
    name = test["name"]
    params = test["params"]
    print(f"[{i+1}/{len(test_variations)}] Test ediliyor: {name}...")
    t0 = time.time()
    try:
        resp = session.get(BASE_URL, params=params, timeout=20)
        duration = round(time.time() - t0, 2)
        status = resp.status_code
        card_count = 0
        if status == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("div.base-search-card, li")
            card_count = len(cards)
        print(f"  -> Durum: {status} | Süre: {duration}s | Dönen Kart/Öğe: {card_count} | Boyut: {len(resp.text)} bayt")
        results.append({
            "name": name,
            "params": params,
            "status": status,
            "duration": duration,
            "card_count": card_count,
            "size": len(resp.text)
        })
    except Exception as e:
        print(f"  -> Hata: {e}")
        results.append({"name": name, "error": str(e)})

    if i < len(test_variations) - 1:
        print("  10 saniye güvenli mola veriliyor...")
        time.sleep(10.5)

print("\n--- ÖZET SONUÇLAR ---")
for r in results:
    print(f"• {r.get('name')}: Status {r.get('status')}, Kart: {r.get('card_count')}, Boyut: {r.get('size')}B")
