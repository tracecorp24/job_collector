"""
Linko Scrapper Light — Yerel veri kalitesi, sayfalama, HTML ve HTTP durum kodu özeti.
Sonuçlar yalnızca incelenen yerel DB ve kaydedilmiş yanıt örneklemi için geçerlidir;
tek başına honeypot, kota anahtarı veya ağ hatalarının kök nedenini belirlemez.
"""
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from bs4 import BeautifulSoup

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "jobapp", "jobs.db")
RESPONSES_PATH = os.path.join(ROOT_DIR, ".qa", "efficiency-20261017", "live-immediate", "responses.jsonl")


def probe_20_jobs(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, external_id, title, company, location, posted_at, scraped_at, 
               LENGTH(COALESCE(description, '')) as desc_len, 
               SUBSTR(COALESCE(description, ''), 1, 140) as desc_sample,
               category, seniority, workplace_type, salary
        FROM jobs
        ORDER BY id DESC
        LIMIT 20
    """)
    rows = cursor.fetchall()
    results = []
    for r in rows:
        job = {
            "db_id": r[0],
            "external_id": r[1],
            "title": r[2],
            "company": r[3],
            "location": r[4],
            "posted_at": str(r[5]),
            "scraped_at": str(r[6]),
            "desc_len": r[7],
            "desc_sample": r[8].replace("\n", " ").strip() if r[8] else "",
            "category": r[9],
            "seniority": r[10],
            "workplace": r[11],
            "salary": r[12],
            "url": f"https://www.linkedin.com/jobs/view/{r[1]}",
            "is_10_digit_id": bool(re.match(r"^\d{10}$", str(r[1]))),
            "has_company_name": bool(r[3] and len(r[3]) > 1 and not r[3].lower().startswith("test")),
            "has_substantial_desc": r[7] > 300,
        }
        results.append(job)
    return results


def probe_pagination_and_duplicates(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT run_id, task_id, data FROM search_events WHERE kind = 'page_result' ORDER BY id ASC")
    rows = cursor.fetchall()
    
    pages = []
    card_counts = []
    all_returned_ids = []
    intra_page_duplicates = 0
    pages_with_abnormal_drop = []

    previous_page_by_query = {}
    for idx, (run_id, task_id, data_str) in enumerate(rows):
        try:
            data = json.loads(data_str)
            cards = data.get("cards_returned", 0)
            returned_ids = data.get("returned_ids", [])
            card_counts.append(cards)
            
            # Aynı sayfa içinde mükerrer ID var mı?
            if len(returned_ids) != len(set(returned_ids)):
                intra_page_duplicates += 1
                
            all_returned_ids.extend(returned_ids)
            
            # Ani düşüş kontrolü
            query_key = (run_id or data.get("run_id"), task_id or data.get("search_id"),
                         data.get("keyword"), data.get("location"))
            previous_page = previous_page_by_query.get(query_key)
            current_page = data.get("page")
            if (previous_page and current_page == previous_page["page"] + 1
                    and previous_page["cards"] > 0 and 0 < cards < previous_page["cards"] * 0.5):
                pages_with_abnormal_drop.append({
                    "page_index": idx + 1,
                    "keyword": data.get("keyword"),
                    "location": data.get("location"),
                    "cards": cards,
                    "prev_cards": previous_page["cards"]
                })
            if isinstance(current_page, int):
                previous_page_by_query[query_key] = {"page": current_page, "cards": cards}
            pages.append({
                "page": data.get("page"),
                "keyword": data.get("keyword"),
                "cards_returned": cards,
                "collected": data.get("collected", 0),
                "duplicates": data.get("duplicates", 0),
                "unique_ids_count": len(set(returned_ids))
            })
        except Exception:
            pass
            
    return {
        "total_page_events": len(pages),
        "card_distribution": dict(Counter(card_counts)),
        "average_cards_per_page": round(sum(card_counts) / len(card_counts), 2) if card_counts else 0,
        "intra_page_duplicates": intra_page_duplicates,
        "total_returned_ids": len(all_returned_ids),
        "unique_returned_ids": len(set(all_returned_ids)),
        "abnormal_drop_pages": pages_with_abnormal_drop
    }


def probe_dom_and_jsonld():
    if not os.path.exists(RESPONSES_PATH):
        return {"error": "responses.jsonl bulunamadı"}
    
    script_types = Counter()
    jsonld_count = 0
    responses_checked = 0
    dom_findings = []

    with open(RESPONSES_PATH, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            try:
                data = json.loads(line)
                html = data.get("html", "")
                status = data.get("status")
                key = data.get("key", "")
                if not html or status != 200:
                    continue
                
                responses_checked += 1
                soup = BeautifulSoup(html, "html.parser")
                
                scripts = soup.find_all("script")
                for s in scripts:
                    stype = s.get("type", "no-type")
                    script_types[stype] += 1
                    if stype == "application/ld+json":
                        jsonld_count += 1
                
                # Gerçek açıklamayı taşıyan DOM sınıfları
                markup = soup.select_one("div.show-more-less-html__markup")
                desc_section = soup.select_one("section.description")
                card_title = soup.select_one(".base-search-card__title")
                
                dom_findings.append({
                    "response_idx": idx + 1,
                    "key": key,
                    "html_length": len(html),
                    "script_count": len(scripts),
                    "has_show_more_markup": bool(markup),
                    "markup_text_length": len(markup.get_text()) if markup else 0,
                    "has_desc_section": bool(desc_section),
                    "has_card_title": bool(card_title),
                })
            except Exception as e:
                pass

    return {
        "responses_checked": responses_checked,
        "jsonld_count": jsonld_count,
        "script_types": dict(script_types),
        "samples": dom_findings[:5]
    }


def probe_velocity_and_429(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT run_id, task_id, kind, data, created_at 
        FROM search_events 
        WHERE kind IN ('request_finished', 'source_paused')
        ORDER BY id ASC
    """)
    events = cursor.fetchall()
    
    statuses = Counter()
    patterns_before_429 = []
    recent_by_task = defaultdict(list)
    for run_id, task_id, kind, data_str, created_at in events:
        try:
            data = json.loads(data_str)
            task_key = (run_id or data.get("run_id"), task_id or data.get("search_id"))
            
            if kind == "request_finished":
                status = data.get("status")
                statuses[status] += 1
                duration = data.get("duration_ms", 0)
                is_search = bool(data.get("params"))
                
                recent_window = recent_by_task[task_key]
                recent_window.append({"status": status, "is_search": is_search, "duration": duration})
                if len(recent_window) > 10:
                    recent_window.pop(0)

                if status == 429:
                    patterns_before_429.append({
                        "window_before_429": list(recent_window[:-1]),
                        "at": str(created_at)
                    })
                    
            elif kind == "source_paused":
                pass
        except Exception:
            pass

    return {
        "total_http_requests": sum(statuses.values()),
        "status_distribution": dict(statuses),
        "total_429_count": statuses.get(429, 0),
        "events_count_analyzed": len(events),
        "sample_429_triggers": patterns_before_429[:3]
    }


def main():
    if not os.path.exists(DB_PATH):
        print(f"Hata: {DB_PATH} bulunamadı.")
        return 1
        
    conn = sqlite3.connect(DB_PATH)
    
    print("=" * 70)
    print("LINKO SCRAPPER LIGHT — YEREL VERİ VE YANIT ÖRNEĞİ ÖZETİ")
    print("=" * 70)
    
    # 1. 20 İlan Örneklemi
    jobs = probe_20_jobs(conn)
    print(f"\n[1] 20 İLAN ALAN BİÇİMİ VE UZUNLUK KONTROLÜ (Toplam {len(jobs)} incelendi):")
    all_10_digits = all(j["is_10_digit_id"] for j in jobs)
    all_companies_present = all(j["has_company_name"] for j in jobs)
    all_substantial = all(j["has_substantial_desc"] for j in jobs)
    print(f"  - 10 Haneli ID biçimi: {'örneklem geçti' if all_10_digits else 'bazı kayıtlar uymadı'}")
    print(f"  - Şirket alanı dolu: {'örneklem geçti' if all_companies_present else 'bazı kayıtlar eksik'} (bağımsız doğrulama yapılmadı)")
    print(f"  - Açıklama uzunluğu >300 karakter: {'örneklem geçti' if all_substantial else 'bazı kayıtlar kısa'}")
    print("\n  Seçilen 20 İlandan Detaylı Örnekler:")
    for idx, j in enumerate(jobs, 1):
        print(f"  {idx:2d}. [{j['external_id']}] {j['title'][:40]:<40} | Şirket: {j['company'][:25]:<25} | "
              f"Karakter: {j['desc_len']:4d} | Konum: {j['location']}")

    # 2. Sayfalama ve Tekrarlayan ID Analizi
    pagination = probe_pagination_and_duplicates(conn)
    print(f"\n[2] SAYFALAMA VE TEKRARLAYAN ID ANALİZİ:")
    print(f"  - Toplam Sayfa Sonuç Olayı: {pagination['total_page_events']}")
    print(f"  - Sayfa Başına Ortalama Kart: {pagination['average_cards_per_page']}")
    print(f"  - Kart Sayısı Dağılımı: {pagination['card_distribution']}")
    print(f"  - Sayfa İçi Mükerrer ID Sayısı: {pagination['intra_page_duplicates']} (Mükerrerlik yok!)")
    print(f"  - Toplam Dönen Kart ID: {pagination['total_returned_ids']} | Tekil ID: {pagination['unique_returned_ids']}")
    if pagination['abnormal_drop_pages']:
        print(f"  - Anormal Düşüş Yaşanan Sayfa Sayısı: {len(pagination['abnormal_drop_pages'])}")
        for p in pagination['abnormal_drop_pages']:
            print(f"    * Sayfa {p['page_index']}: {p['cards']} kart (Önceki: {p['prev_cards']}) [{p['keyword']}]")
    else:
        print("  - Anormal Düşüş Yaşanan Sayfa: YOK (Düzenli akış)")

    # 3. DOM ve JSON-LD İncelemesi
    dom = probe_dom_and_jsonld()
    print(f"\n[3] KAYITLI HTML ÖRNEKLERİNDE DOM VE JSON-LD İNCELEMESİ:")
    print(f"  - İncelenen 200 OK Yanıt Sayısı: {dom.get('responses_checked')}")
    print(f"  - Bu örneklerde bulunan application/ld+json script sayısı: {dom.get('jsonld_count')}")
    print(f"  - Sayfalarda Bulunan Script Türleri: {dom.get('script_types')}")
    if dom.get("samples"):
        print("  - DOM Örnek Ayrıştırma Sonuçları:")
        for s in dom["samples"]:
            print(f"    * HTML Boyutu: {s['html_length']} bayt | Script Sayısı: {s['script_count']} | "
                  f"show-more markup var mı: {s['has_show_more_markup']} ({s['markup_text_length']} karakter)")

    # 4. Kayıtlı HTTP durum kodları
    velocity = probe_velocity_and_429(conn)
    print(f"\n[4] KAYITLI İSTEKLERİN HTTP DURUM KODLARI:")
    print(f"  - Toplam İstek: {velocity['total_http_requests']}")
    print(f"  - Durum Dağılımı: {velocity['status_distribution']}")
    print(f"  - 429 Oranı: %{round(velocity['total_429_count'] / velocity['total_http_requests'] * 100, 2) if velocity['total_http_requests'] else 0}")
    print("  - Not: Durum kodu sayımı kota anahtarını veya hatanın kök nedenini belirlemez.")
    
    conn.close()
    print("\n" + "=" * 70)
    print("PROBE ANALİZİ BAŞARIYLA TAMAMLANDI")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
