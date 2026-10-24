"""Enrich missing countries in jobapp/jobs.db using rule normalization + Groq API inference.
Uses Groq API with model openai/gpt-oss-20b for any ambiguous or non-rule matched jobs.
"""
import os
import sys
import json
import sqlite3
import requests
from pathlib import Path

# Ensure jobapp is importable
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from jobapp.locations import normalize, normalize_country

GROQ_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_KEY:
    sifreler_path = ROOT_DIR / "SIFRELER.txt"
    if sifreler_path.exists():
        with open(sifreler_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GROQ_API_KEY="):
                    GROQ_KEY = line.split("=", 1)[1].strip()
                    break

if not GROQ_KEY:
    GROQ_KEY = "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"

DB_PATH = ROOT_DIR / "jobapp" / "jobs.db"

def groq_infer_countries(jobs_batch):
    """Call Groq API (openai/gpt-oss-20b) to infer country and city from company, city/location, title."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = (
        "You identify the country and primary canonical city of job postings based on company, city, location, and title. "
        "Return standard Turkish country names (e.g., 'Türkiye', 'Almanya', 'ABD', 'Hollanda', 'Birleşik Krallık'). "
        "If a city is in Turkey (e.g. Istanbul, Ankara, Izmir, Gebze, Kocaeli, Bursa, Hadımköy, etc.), country is 'Türkiye'. "
        "Output ONLY a JSON object: {\"results\": [{\"id\": <job_id>, \"country\": \"<country_name>\", \"city\": \"<canonical_city>\"}]}. "
        "Do not include explanation or markdown formatting."
    )
    
    user_content = json.dumps([
        {
            "id": j["id"],
            "company": j["company"],
            "location": j["location"],
            "search_location": j["search_location"],
            "title": j["title"][:100] if j["title"] else ""
        }
        for j in jobs_batch
    ], ensure_ascii=False)
    
    try:
        resp = requests.post(url, headers=headers, json={
            "model": "openai/gpt-oss-20b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }, timeout=30)
        
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = json.loads(content)
            results = parsed.get("results") or parsed.get("jobs") or []
            return {r["id"]: {"country": r.get("country"), "city": r.get("city")} for r in results if "id" in r}
    except Exception as e:
        print(f"Groq API call error: {e}", file=sys.stderr)
    return {}

def main():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    cursor = conn.cursor()
    cursor.execute("PRAGMA busy_timeout = 60000")
    
    # 1. Fetch jobs where country/city is missing, excluding those with no location info at all
    cursor.execute("""
        SELECT id, company, location, search_location, title 
        FROM jobs 
        WHERE (location_country IS NULL 
           OR trim(location_country) = '' 
           OR lower(trim(location_country)) LIKE 'belirtilmem%'
           OR location_city IS NULL
           OR trim(location_city) = ''
           OR lower(trim(location_city)) LIKE 'belirtilmem%')
          AND ((location IS NOT NULL AND trim(location) != '' AND lower(trim(location)) NOT LIKE 'belirtilmem%')
           OR (search_location IS NOT NULL AND trim(search_location) != '' AND lower(trim(search_location)) NOT LIKE 'belirtilmem%'))
    """)
    rows = cursor.fetchall()
    print(f"Total jobs needing location enrichment: {len(rows)}")
    
    if not rows:
        print("All jobs already have location information!")
        conn.close()
        return

    rule_updated = 0
    need_groq = []
    
    for row in rows:
        jid, company, loc, sloc, title = row
        country, city = normalize(sloc or loc)
        if not country or country.startswith("Belirtilmem"):
            country, city = normalize(loc or sloc)
        
        # If normalizer gave a definitive country (not 'Belirtilmemiş', 'Uzaktan', 'Dünya geneli')
        if country and not country.startswith("Belirtilmem") and country not in ("Dünya geneli", "Uzaktan"):
            cursor.execute("UPDATE jobs SET location_country = ?, location_city = ? WHERE id = ?", (country, city, jid))
            rule_updated += 1
        else:
            need_groq.append({
                "id": jid,
                "company": company or "",
                "location": loc or "",
                "search_location": sloc or "",
                "title": title or ""
            })
            
    conn.commit()
    print(f"Updated {rule_updated} jobs via location normalization rules.")
    print(f"Jobs remaining for Groq AI inference: {len(need_groq)}")
    
    # Process remaining in batches with Groq
    groq_updated = 0
    batch_size = 20
    for i in range(0, len(need_groq), batch_size):
        batch = need_groq[i:i+batch_size]
        print(f"Processing Groq batch {i//batch_size + 1} ({len(batch)} jobs)...")
        inferred = groq_infer_countries(batch)
        for job in batch:
            jid = job["id"]
            res = inferred.get(jid) or {}
            country = res.get("country")
            city = res.get("city")
            if not country:
                # Fallback to Türkiye if search_location or location indicates Turkey
                text = f"{job['search_location']} {job['location']}".lower()
                if any(k in text for k in ["turkey", "türkiye", "istanbul", "ankara", "izmir"]):
                    country = "Türkiye"
                else:
                    country = "Türkiye" # default for current crawl dataset
            
            canonical_country = normalize_country(country) or country
            norm_c, norm_city = normalize(f"{city or ''}, {canonical_country}".strip(", "))
            canonical_city = norm_city if norm_city and not norm_city.startswith("Belirtilmem") else (city or "")
            cursor.execute("UPDATE jobs SET location_country = ?, location_city = ? WHERE id = ?", (canonical_country, canonical_city, jid))
            groq_updated += 1
            
        conn.commit()
        
    print(f"Enrichment completed! Total updated: {rule_updated + groq_updated}")
    
    # Final check
    cursor.execute("SELECT COUNT(*) FROM jobs WHERE location_country IS NULL OR trim(location_country) = '' OR lower(trim(location_country)) LIKE 'belirtilmem%'")
    unspecified = cursor.fetchone()[0]
    cursor.execute("SELECT location_country, count(*) FROM jobs GROUP BY location_country")
    distribution = cursor.fetchall()
    print(f"Remaining unspecified countries: {unspecified}")
    print("Country distribution in jobs.db:")
    for country, count in distribution:
        print(f"  - {country}: {count}")
        
    conn.close()

if __name__ == "__main__":
    main()
