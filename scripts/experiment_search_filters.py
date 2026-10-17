import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

session = requests.Session()
session.headers.update(HEADERS)

tests = [
    {
        "name": "Baz Arama (Filtresiz)",
        "params": {"keywords": "Python", "location": "Turkey", "start": 0}
    },
    {
        "name": "Uzaktan / Remote Filtresi (f_WT=2)",
        "params": {"keywords": "Python", "location": "Turkey", "start": 0, "f_WT": "2"}
    },
    {
        "name": "Hibrit Filtresi (f_WT=3)",
        "params": {"keywords": "Python", "location": "Turkey", "start": 0, "f_WT": "3"}
    },
    {
        "name": "Kıdem / Mid-Senior Filtresi (f_E=4)",
        "params": {"keywords": "Python", "location": "Turkey", "start": 0, "f_E": "4"}
    },
    {
        "name": "Tam Zamanlı Filtresi (f_JT=F)",
        "params": {"keywords": "Python", "location": "Turkey", "start": 0, "f_JT": "F"}
    }
]

print("=== DENEY 2: LINKEDIN URL GİZLİ ARAMA FİLTRELERİ TESTİ ===")
print("İstekler arası 10.5 saniye bekleniyor...\n")

results = []

for i, t in enumerate(tests):
    name = t["name"]
    params = t["params"]
    print(f"[{i+1}/{len(tests)}] Test: {name}...")
    t0 = time.time()
    try:
        r = session.get(BASE_URL, params=params, timeout=20)
        dur = round(time.time() - t0, 2)
        status = r.status_code
        card_titles = []
        card_locations = []
        if status == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("div.base-search-card")
            for c in cards:
                title_elem = c.select_one(".base-search-card__title")
                loc_elem = c.select_one(".job-search-card__location")
                if title_elem:
                    card_titles.append(title_elem.get_text(strip=True))
                if loc_elem:
                    card_locations.append(loc_elem.get_text(strip=True))
        
        print(f"  -> Durum: {status} | Süre: {dur}s | Kart Sayısı: {len(card_titles)}")
        print(f"  -> Örnek Konumlar: {card_locations[:3]}")
        print(f"  -> Örnek Başlıklar: {card_titles[:2]}")
        results.append({
            "name": name,
            "status": status,
            "card_count": len(card_titles),
            "sample_locations": card_locations[:4],
            "sample_titles": card_titles[:3],
            "first_card_id": cards[0].get("data-entity-urn") if cards else None
        })
    except Exception as e:
        print(f"  -> Hata: {e}")
        results.append({"name": name, "error": str(e)})

    if i < len(tests) - 1:
        time.sleep(10.5)

print("\n--- DENEY 2 ÖZET SONUÇLARI ---")
for res in results:
    print(f"• {res['name']}: {res.get('card_count')} kart | İlk URN: {res.get('first_card_id')}")
    print(f"  Konumlar: {res.get('sample_locations')}")
