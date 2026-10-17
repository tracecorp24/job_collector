"""Parse raw LinkedIn card text into clean structured fields.

The old scraper mapped card lines positionally (line[0]=title, line[1]=company,
line[2]=location). LinkedIn actually emits::

    [title, "<title> with verification", company, "City, Country (Onsite)", ...noise]

so company/location came out shifted by one and pure-noise cards (e.g.
"2 former employees work here") became fake titles. This module drops the
verification duplicate + known noise lines, then reads company/location by
meaning rather than by index.
"""

import re

# --- Noise detection -------------------------------------------------------

# Substrings (case-insensitive) that mark a line as boilerplate, not data.
_NOISE_SUBSTRINGS = (
    "with verification",
    "aktif olarak inceleniyor",       # "Applications actively reviewed"
    "actively reviewing applicants",
    "eski şirket çalışanı burada çalışıyor",  # "N former employees work here"
    "former employee",
    "kolay başvuru",                   # "Easy Apply"
    "easy apply",
    "tanıtıldı",                       # "Promoted"
    "promoted",
    "görüntülenen",                    # "Viewed"
    "viewed",
    "başvuruldu",                      # "Applied"
    "applied",
    "yanıt veriyor",                   # "Responsive / responds"
    "response",
    "bağlantı",                        # "... connection works here"
    "connection",
    "school alum",
    "okuldan",
)

# Hesapsız kartta unvan satırı yalnızca birebir bu rozetlerden biriyse gürültüdür.
_GUEST_NOISE_TITLES = frozenset((
    "promoted", "tanıtıldı", "viewed", "görüntülendi", "applied", "başvuruldu",
    "easy apply", "kolay başvuru", "actively reviewing applicants",
))

# Workplace markers -> canonical label.
_WORKPLACE_MAP = (
    ("iş yerinde", "Onsite"),
    ("i̇ş yerinde", "Onsite"),
    ("ofisten", "Onsite"),
    ("on-site", "Onsite"),
    ("on site", "Onsite"),
    ("onsite", "Onsite"),
    ("hibrit", "Hybrid"),
    ("hybrid", "Hybrid"),
    ("uzaktan", "Remote"),
    ("remote", "Remote"),
)

# A line that "looks like a location": has a workplace marker, mentions a
# country we expect, or is a "City, Region" comma phrase ending in a country.
_LOCATION_HINTS = ("türkiye", "turkey", "remote", "united", "germany", "deutschland")


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", (line or "")).strip(" ·\t​")


def is_noise(line: str) -> bool:
    low = line.lower()
    if not low:
        return True
    for sub in _NOISE_SUBSTRINGS:
        if sub in low:
            return True
    return False


def detect_workplace(text: str) -> str:
    low = text.lower()
    for marker, label in _WORKPLACE_MAP:
        if marker in low:
            return label
    return ""


def _looks_like_location(line: str) -> bool:
    low = line.lower()
    if detect_workplace(line):
        return True
    if any(hint in low for hint in _LOCATION_HINTS):
        return True
    # "City, Country" style with a comma and no long words typical of titles.
    if "," in line and len(line) <= 60:
        return True
    return False


def _strip_workplace(location: str) -> str:
    """Remove a trailing "(...)" workplace parenthetical for a clean display."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", location).strip(" ,·")


def parse_card(card_lines, description: str = "") -> dict:
    """Turn raw card lines into ``{title, company, location, workplace_type,
    quality_ok}``.

    ``quality_ok`` is False when the card carries no real title (pure noise),
    so the UI can hide it.
    """
    lines = [_norm(l) for l in (card_lines or []) if _norm(l)]

    # Title = first line that isn't boilerplate.
    title = ""
    for line in lines:
        if not is_noise(line):
            title = line
            break

    if not title:
        return {
            "title": (lines[0] if lines else ""),
            "company": "",
            "location": "",
            "workplace_type": "",
            "quality_ok": False,
        }

    title_low = title.lower()

    # Meaningful lines: drop the title, its "with verification" duplicate, any
    # exact re-print of the title, and all noise lines.
    meaningful = []
    for line in lines:
        low = line.lower()
        if low == title_low:
            continue
        if low.startswith(title_low) and "verification" in low:
            continue
        if is_noise(line):
            continue
        meaningful.append(line)

    # Locate the location line (with workplace type), then company is what
    # comes before it (companies precede location on LinkedIn cards).
    location = ""
    workplace = ""
    location_idx = None
    for idx, line in enumerate(meaningful):
        if _looks_like_location(line):
            location_idx = idx
            workplace = detect_workplace(line)
            location = _strip_workplace(line)
            break

    if location_idx is not None:
        before = meaningful[:location_idx]
        company = before[0] if before else ""
    else:
        company = meaningful[0] if meaningful else ""

    # Fallback: pull workplace type from the description if the card lacked it.
    if not workplace and description:
        workplace = detect_workplace(description)

    return {
        "title": title,
        "company": company,
        "location": location,
        "workplace_type": workplace,
        "quality_ok": True,
    }


def parse_guest_card(card_lines, description: str = "") -> dict:
    """Hesapsız (guest) arama kartı: satırlar sabit sırada ``[unvan, şirket, konum]``.

    Konum anlamına göre aranmaz; "Maltepe" gibi tek kelimelik konumlar ve adında
    "Türkiye" geçen şirketler bu yüzden doğru alana düşer.
    """
    lines = [_norm(l) for l in (card_lines or [])] + ["", "", ""]
    title, company, location = lines[:3]
    # Unvan satırı seçiciden gelir; alt dizgi gürültü filtresi "Applied Scientist",
    # "Incident Response Analyst" gibi gerçek unvanları gizliyordu. Yalnızca boş satır ve
    # satırın tamamı bilinen bir rozet olduğunda reddedilir.
    if not title or title.lower() in _GUEST_NOISE_TITLES:
        return {"title": title, "company": "", "location": "", "workplace_type": "", "quality_ok": False}
    workplace = detect_workplace(location) or (detect_workplace(description) if description else "")
    return {"title": title, "company": company, "location": _strip_workplace(location),
            "workplace_type": workplace, "quality_ok": True}


def is_guest_card(raw: dict) -> bool:
    """Kartın hesapsız kazıyıcıdan geldiğini (eski kayıtlarda işaret yoksa biçiminden) anlar."""
    if raw.get("card_layout") == "guest":
        return True
    lines = raw.get("card_lines")
    return (isinstance(lines, list) and len(lines) == 3 and str(raw.get("external_id", "")).isdigit()
            and "linkedin.com/jobs/view/" in str(raw.get("url", "")))
