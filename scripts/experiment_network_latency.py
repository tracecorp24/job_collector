import time
import requests

URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

print("=== DENEY 4: AĞ GECİKMESİ VE TCP/TLS BAĞLANTI SÜRESİ BENCHMARK'I ===")

# Test 1: Cold Connection (Yeni TCP + TLS El Sıkışması)
t0 = time.perf_counter()
s_cold = requests.Session()
s_cold.headers.update(HEADERS)
r_cold = s_cold.get(URL, params={"keywords": "Python", "location": "Istanbul, Turkey", "start": 0}, timeout=20)
dur_cold = round((time.perf_counter() - t0) * 1000, 2)
print(f"Cold İstek (TCP + TLS + HTTP): {dur_cold} ms | Status: {r_cold.status_code} | Boyut: {len(r_cold.content)}B")

time.sleep(10.5)

# Test 2: Warm Connection (Aynı Session ve Keep-Alive TCP kanalı üzerinden)
t1 = time.perf_counter()
r_warm = s_cold.get(URL, params={"keywords": "Python", "location": "Istanbul, Turkey", "start": 10}, timeout=20)
dur_warm = round((time.perf_counter() - t1) * 1000, 2)
print(f"Warm İstek (Keep-Alive TCP):   {dur_warm} ms | Status: {r_warm.status_code} | Boyut: {len(r_warm.content)}B")

diff = round(dur_cold - dur_warm, 2)
saving_pct = round((diff / dur_cold) * 100, 1)

print("\n--- DENEY 4 BULGULARI ---")
print(f"• TCP/TLS El Sıkışma Ek Maliyeti (Overhead): ~{diff} ms")
print(f"• Keep-Alive Oturum Tasarrufu: %{saving_pct} daha hızlı yanıt")
s_cold.close()
