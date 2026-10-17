import time
import requests

BASE_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

session = requests.Session()
session.headers.update(HEADERS)

print("=== DENEY 2: BURST (PATLAMA) PACING DİNAMİĞİ TESTİ ===")
print("Amaç: LinkedIn ani patlamaya (1.5s arayla ardışık istekler) izin veriyor mu?\n")

burst_results = []
# 4 rapid requests with 1.5s interval
for i in range(4):
    start_offset = i * 10
    params = {"keywords": "Java", "location": "Istanbul, Turkey", "start": start_offset}
    t0 = time.time()
    try:
        resp = session.get(BASE_URL, params=params, timeout=20)
        dur = round(time.time() - t0, 2)
        status = resp.status_code
        retry_after = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
        print(f"İstek #{i+1} (start={start_offset}): HTTP {status} | Süre: {dur}s | Retry-After: {retry_after}")
        burst_results.append({"req": i+1, "status": status, "duration": dur, "retry_after": retry_after})
    except Exception as e:
        print(f"İstek #{i+1}: Hata {e}")
        burst_results.append({"req": i+1, "error": str(e)})
    
    if i < 3:
        time.sleep(1.5)

print("\n--- DENEY 2 SONUÇLARI ---")
statuses = [r.get("status") for r in burst_results]
print("Durum Kodları:", statuses)
if all(s == 200 for s in statuses):
    print("BULGU: LinkedIn en az 4 istek burst (ani patlama) toleransına sahip! (Token Bucket)")
else:
    print("BULGU: LinkedIn ardışık hızlı isteklere (1.5s) izin vermiyor, 429 tetikliyor. (Leaky Bucket / Sabit Aralık Şart)")
