#!/usr/bin/env python3
"""knee_probe.py - Ampirik Taban Hız ve WAF Eşik Ölçüm Aracı

Bu araç, mevcut IP'nin LinkedIn misafir uç noktalarında HTTP 429 almadan
inebileceği en düşük istek aralığını (diz-noktası / knee-point) güvenli şekilde ölçer.

Güvenlik Emniyeti (Circuit Breaker):
- İlk HTTP 429 / 403 / 999 yanıtında testi DERHAL durdurur.
- Kaynağa asla ardışık ceza yüklemesi yapmaz, IP'yi riske atmaz.
"""

import sys
import time
import random
import argparse
from pathlib import Path

# Proje kökünü sys.path'e ekle
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def run_probe(intervals=None, requests_per_step=15, jitter=0.15):
    if intervals is None:
        intervals = [12.0, 10.0, 9.0, 8.0, 7.0, 6.0]

    session = requests.Session()
    session.headers.update(HEADERS)

    print("=" * 70)
    print("LINKO SCRAPPER LIGHT — GÜVENLİ DİZ-NOKTASI (KNEE-POINT) PROBE")
    print(f"Test Kademeleri: {intervals} saniye")
    print(f"Kademe Başına İstek: {requests_per_step} adet (Jitter: ±%{int(jitter*100)})")
    print("Emniyet Kilidi: İlk 429/403 hatasında test DERHAL durdurulacaktır.")
    print("=" * 70 + "\n")

    # Warmup
    print("[1/2] Oturum ısıtılıyor (warmup)...")
    try:
        t0 = time.time()
        resp = session.get(SEARCH_URL, params={"keywords": "Yazılım", "location": "Turkey", "start": 0}, timeout=15)
        dur = round(time.time() - t0, 2)
        print(f"  Warmup yanıtı: HTTP {resp.status_code} ({dur}s, {len(resp.content)} bayt)\n")
        if resp.status_code == 429:
            print("  [DURDURULDU] IP şu anda zaten blokajda (HTTP 429)! Test iptal edildi.")
            return {"safe_floor": None, "reason": "already_blocked"}
    except Exception as exc:
        print(f"  [HATA] Isınma isteği başarısız: {exc}")
        return {"safe_floor": None, "reason": str(exc)}

    # Kademeli İniş
    print("[2/2] Kademeli hız testi başlıyor...")
    clean_floor = 12.0
    total_successful = 0

    for step_idx, interval in enumerate(intervals, 1):
        print(f"\n--- [Kademe {step_idx}/{len(intervals)}] Hedef Aralık: {interval:.1f}s ---")
        step_successes = 0

        for req_idx in range(1, requests_per_step + 1):
            # Jitter'lı bekleme süresi
            actual_wait = interval * (1.0 + random.uniform(-jitter, jitter))
            time.sleep(actual_wait)

            start_offset = (total_successful % 10) * 10
            t0 = time.time()
            try:
                resp = session.get(
                    SEARCH_URL,
                    params={"keywords": "Mühendislik", "location": "Istanbul, Turkey", "start": start_offset},
                    timeout=15
                )
                dur = round(time.time() - t0, 2)
                status = resp.status_code
                retry_after = resp.headers.get("Retry-After")

                if status == 200:
                    step_successes += 1
                    total_successful += 1
                    print(f"  [{req_idx:02d}/{requests_per_step}] HTTP 200 OK | Yanıt: {dur}s | Beklenen: {actual_wait:.1f}s")
                elif status in (429, 401, 403, 999):
                    print("\n  [!!! DEVRE KESİCİ DEVREDE !!!]")
                    print(f"  İstek #{req_idx} HTTP {status} aldı! (Retry-After: {retry_after})")
                    print("  IP koruması için test anında durduruldu.")
                    print("=" * 70)
                    print(f"SONUÇ: Güvenli tavan diz-noktası: {clean_floor:.1f} saniyedir.")
                    print(f"       {interval:.1f}s aralıkta WAF penceresi doldu (HTTP {status}).")
                    print("=" * 70)
                    return {
                        "safe_floor": clean_floor,
                        "broken_at": interval,
                        "reason": f"HTTP_{status}",
                        "total_successful": total_successful
                    }
                else:
                    print(f"  [{req_idx:02d}/{requests_per_step}] Beklenmeyen Durum: HTTP {status}")
            except Exception as exc:
                print(f"  [{req_idx:02d}/{requests_per_step}] Ağ Hatası: {exc}")

        # Bu kademe temiz bitti
        clean_floor = interval
        print(f"  -> Kademe {interval:.1f}s başarıyla tamamlandı ({step_successes}/{requests_per_step} başarılı).")

    print("\n" + "=" * 70)
    print("TEBRİKLER: Tüm kademeler başarıyla tamamlandı!")
    print(f"En düşük temiz taban: {clean_floor:.1f} saniyedir. Toplam başarılı: {total_successful}")
    print("=" * 70)
    return {"safe_floor": clean_floor, "broken_at": None, "total_successful": total_successful}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Linko Knee-Point Hız Testi")
    parser.add_argument("--steps", type=int, default=10, help="Kademe başına istek sayısı (varsayılan: 10)")
    parser.add_argument("--fast", action="store_true", help="Hızlı kontrol (kademe başına 5 istek)")
    args = parser.parse_args()

    steps = 5 if args.fast else args.steps
    run_probe(requests_per_step=steps)
