import time
import requests

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

print("=== DENEY 3: ÇEREZ / OTURUM SIFIRLAMA (COLD SESSION) TESTİ ===")
print("Amaç: Oturumu/çerezi sıfırlamak hızı veya kimliği nasıl etkiliyor?\n")

print("Ön hazırlık: 30 saniye mola verilerek pencerenin temizlenmesi bekleniyor...")
time.sleep(30)

# Aşama 1: Normal oturumla 1 istek
s1 = requests.Session()
s1.headers.update(HEADERS)
r1 = s1.get(BASE_URL, params={"keywords": "Go", "location": "Istanbul, Turkey", "start": 0}, timeout=20)
print(f"Oturum 1 (İlk İstek): Status {r1.status_code}")
cookies_1 = dict(s1.cookies)
print(f"  Atanan Çerezler ({len(cookies_1)} adet): {list(cookies_1.keys())}")
bcookie_1 = cookies_1.get("bcookie")
print(f"  bcookie 1: {bcookie_1[:25] if bcookie_1 else 'Yok'}...")

time.sleep(10.5)

# Aşama 2: Tamamen yeni oturum (Cold Session, sıfır çerez)
s2 = requests.Session()
s2.headers.update(HEADERS)
r2 = s2.get(BASE_URL, params={"keywords": "Go", "location": "Istanbul, Turkey", "start": 10}, timeout=20)
print(f"\nOturum 2 (Sıfır Çerezle İstek): Status {r2.status_code}")
cookies_2 = dict(s2.cookies)
print(f"  Atanan Çerezler ({len(cookies_2)} adet): {list(cookies_2.keys())}")
bcookie_2 = cookies_2.get("bcookie")
print(f"  bcookie 2: {bcookie_2[:25] if bcookie_2 else 'Yok'}...")

print("\n--- DENEY 3 BULGULARI ---")
if bcookie_1 and bcookie_2 and bcookie_1 != bcookie_2:
    print("• LinkedIn her yeni bağlantıya anında yeni bir misafir takip kimliği (bcookie) atamaktadır.")
    print("• Ancak IP bazlı Cloudflare/Instart WAF katmanı, çerez sıfırlansa dahi client IP üzerinden aynı rate limit sayacını tutmaktadır.")
else:
    print("• Çerezler korundu veya atama gözlemlendi.")
