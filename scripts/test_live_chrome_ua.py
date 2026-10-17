import requests
from bs4 import BeautifulSoup

url = "https://www.linkedin.com/jobs/view/4468150126"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

try:
    print(f"Testing URL: {url} with latest Chrome 131 UA...")
    r = requests.get(url, headers=headers, timeout=20)
    print("Status:", r.status_code)
    print("Content Length:", len(r.text))
    soup = BeautifulSoup(r.text, "html.parser")
    json_ld = soup.find_all("script", type="application/ld+json")
    print("Found application/ld+json count:", len(json_ld))
    for idx, s in enumerate(json_ld):
        print(f"  Script {idx+1} snippet: {(s.string or '')[:100]}...")
    scripts = soup.find_all("script")
    types = set(s.get("type") for s in scripts)
    print("All script types in page:", types)
    title = soup.select_one(".top-card-layout__title, .base-search-card__title, h1")
    print("Title found via DOM:", title.get_text(strip=True) if title else "None")
    markup = soup.select_one("div.show-more-less-html__markup")
    print("Description markup found via DOM:", bool(markup), f"({len(markup.get_text()) if markup else 0} chars)")
except Exception as e:
    print("Error:", e)
