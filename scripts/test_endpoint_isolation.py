"""
Linko Scrapper Light — Endpoint İzolasyonu ve Pacing Ritim Karşılaştırma Analizi
Bu betik:
1. Veritabanındaki istek kayıtlarında Search ve Detail yanıtlarının sıralamasını (endpoint ilişkisi)
   inceler; olay sırası tek başına kota paylaşımını göstermez.
2. Dört pacing senaryosunu açıkça belirtilen eşik/bekleme varsayımları altında simüle eder.
   Sonuçlar LinkedIn'in canlı kotasını ölçmez ve üretim performansı tahmini sayılmamalıdır.
"""
import json
import os
import sqlite3
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "jobapp", "jobs.db")


def analyze_endpoint_isolation(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, run_id, task_id, kind, data, created_at 
        FROM search_events 
        WHERE kind IN ('request_finished', 'source_paused')
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    
    events = []
    groups = {}
    for r in rows:
        try:
            d = json.loads(r[4])
            event = {
                "id": r[0],
                "run_id": r[1] or d.get("run_id"),
                "task_id": r[2] or d.get("search_id"),
                "kind": r[3],
                "data": d,
                "created_at": r[5],
                "type": ("search" if d.get("params") else "detail") if r[3] == "request_finished" else "pause",
                "status": d.get("status") if r[3] == "request_finished" else d.get("reason"),
            }
            events.append(event)
            groups.setdefault((event["run_id"], event["task_id"]), []).append(event)
        except Exception:
            pass

    # 429 sonrası çapraz uç nokta etkilenme analizi
    detail_429_then_search_429 = 0
    detail_429_then_detail_429 = 0
    search_429_then_search_429 = 0
    cross_endpoint_cascades = []

    for task_events in groups.values():
        for i, e1 in enumerate(task_events[:-1]):
            if e1["kind"] == "request_finished" and e1["status"] == 429:
                # Yalnızca aynı run/task içindeki sonraki istekle karşılaştır.
                for j in range(i + 1, min(len(task_events), i + 6)):
                    e2 = task_events[j]
                    if e2["kind"] == "request_finished":
                        cross_endpoint_cascades.append({
                            "from_type": e1["type"],
                            "from_id": e1["id"],
                            "to_type": e2["type"],
                            "to_status": e2["status"],
                            "to_id": e2["id"],
                            "had_pause_between": any(task_events[k]["kind"] == "source_paused" for k in range(i + 1, j))
                        })
                        if e1["type"] == "detail" and e2["type"] == "search" and e2["status"] == 429:
                            detail_429_then_search_429 += 1
                        break

    return {
        "total_events": len(events),
        "cascades": cross_endpoint_cascades,
        "detail_429_to_search_429_count": detail_429_then_search_429
    }


def compare_pacing_strategies():
    """
    Dört varsayımsal stratejinin bir saatlik model karşılaştırması.
    Eşikler canlı ölçüm değildir; özellikle 429'u devre dışı bırakan stratejiler
    gerçek kota veya başarı oranı hakkında çıkarım sağlamaz.
    """
    strategies = [
        {
            "name": "Strateji A: Mevcut Sistem (6 sn + %0-30 Jitter + 429 Sonrası 60s/120s Bekleme)",
            "interval_avg": 6.9,  # 6 * 1.15
            "burst_limit_before_429": 5, # 5 istek sonra 429
            "cooldown_on_429": 65,  # 60s pause + acquire delay
            "description": "Hızlı istek atar (6.9s), her 5 istekte bir 429 alıp 65s donar."
        },
        {
            "name": "Strateji B: 10 sn deneme ayarı (+ %0-15 Jitter)",
            "interval_avg": 10.75, # 10 * 1.075
            "burst_limit_before_429": 999999, # modelde 429 eşiği devre dışı
            "cooldown_on_429": 0,
            "description": "Modelde 429 eşiği devre dışı; çıktı canlı kotanın altında kalındığını kanıtlamaz."
        },
        {
            "name": "Strateji C: 12 sn karşılaştırma senaryosu (+ %0-15 Jitter)",
            "interval_avg": 12.9,
            "burst_limit_before_429": 999999, # modelde 429 eşiği devre dışı
            "cooldown_on_429": 0,
            "description": "Modelde 429 eşiği devre dışı; çıktı canlı kotanın altında kalındığını kanıtlamaz."
        },
        {
            "name": "Strateji D: Kova Ayrımı (AI Önerisi: Kart 5s, Detay 3s Paralel)",
            "interval_avg": 2.5, # Birleşik efektif aralık (aynı IP)
            "burst_limit_before_429": 5,
            "cooldown_on_429": 120, # Paralel yükte kümülatif ihlal -> 120s veya 900s blok
            "description": "Aynı IP'den iki kanaldan istek yağdırır; ilk 15 saniyede 429 yer ve katlanarak donar."
        }
    ]

    results = []
    SIMULATION_SECONDS = 3600  # 1 Saat

    for strat in strategies:
        t = 0
        requests_sent = 0
        paused_seconds = 0
        error_429_count = 0
        consecutive_reqs = 0

        while t < SIMULATION_SECONDS:
            if consecutive_reqs >= strat["burst_limit_before_429"]:
                # 429 yendi
                error_429_count += 1
                cooldown = strat["cooldown_on_429"]
                paused_seconds += cooldown
                t += cooldown
                consecutive_reqs = 0
            else:
                t += strat["interval_avg"]
                if t <= SIMULATION_SECONDS:
                    requests_sent += 1
                    consecutive_reqs += 1

        successful_requests = requests_sent
        frozen_ratio = round(paused_seconds / SIMULATION_SECONDS, 4)
        throughput_per_hour = successful_requests

        results.append({
            "name": strat["name"],
            "hourly_requests": throughput_per_hour,
            "errors_429": error_429_count,
            "total_pause_seconds": paused_seconds,
            "frozen_ratio": f"%{frozen_ratio * 100:.1f}",
            "ip_risk": "Model varsayımına bağlı; canlı risk ölçülmedi",
            "description": strat["description"]
        })

    return results


def main():
    if not os.path.exists(DB_PATH):
        print(f"Hata: {DB_PATH} bulunamadı.")
        return 1

    conn = sqlite3.connect(DB_PATH)
    
    print("=" * 75)
    print("LINKO SCRAPPER LIGHT — ENDPOINT İZOLASYONU VE PACING ANALİZİ")
    print("=" * 75)

    # 1. Endpoint İzolasyonu Analizi
    iso = analyze_endpoint_isolation(conn)
    print("\n[1] ENDPOINT İZOLASYONU TEST BULGULARI:")
    print(f"  - Toplam İncelenen Olay: {iso['total_events']}")
    print("  - 429 Sonrası İlk İstek Geçişleri:")
    for c in iso["cascades"][:10]:
        pause_note = " (Arada pause beklemesi oldu)" if c["had_pause_between"] else " (BEKLEMEDEN)"
        print(f"    * {c['from_type'].upper()} (429) ---> {c['to_type'].upper()} ({c['to_status']}){pause_note}")
    
    print("\n  >> Bu olay sıralaması tek başına LinkedIn'in kota anahtarını (IP/uç nokta/oturum) kanıtlamaz.")
    print("     Paylaşılan Coordinator beklemeleri de sonraki isteğin sonucunu etkileyebilir.")

    # 2. Pacing Ritim Karşılaştırması
    pacing_results = compare_pacing_strategies()
    print("\n[2] PACING STRATEJİLERİ İÇİN 1 SAATLİK VARSAYIMLI MODEL:")
    for p in pacing_results:
        print(f"\n  * {p['name']}")
        print(f"    - Saatte Başarılı İstek: {p['hourly_requests']}")
        print(f"    - Alınan 429 Hata Sayısı: {p['errors_429']}")
        print(f"    - Toplam Boş Bekleme Süresi: {p['total_pause_seconds']} sn ({p['total_pause_seconds']//60} dakika)")
        print(f"    - Donma Oranı (frozen_ratio): {p['frozen_ratio']}")
        print(f"    - Model riski notu: {p['ip_risk']}")
        print(f"    - Açıklama: {p['description']}")

    conn.close()
    print("\n" + "=" * 75)
    print("VARSAYIMLI SİMÜLASYON TAMAMLANDI; CANLI KOTA ÖLÇÜLMEDİ")
    print("=" * 75)
    return 0


if __name__ == "__main__":
    sys.exit(main())
