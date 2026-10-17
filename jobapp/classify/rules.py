"""Deterministic, offline keyword classifier (Turkish + English).

Turkish casing is locale-specific and Python's ``str.lower()`` mishandles it
(``"İ".lower()`` becomes ``"i̇"`` = i + combining dot, and ``"I".lower()`` becomes
dotted ``"i"``). To match reliably regardless of dotted/dotless I and other
Turkish letters, both the text and the keywords are passed through ``_fold``,
which ASCII-folds Turkish characters. **All keyword lists below are written in
that folded (ASCII, lowercase) form.**
"""

import re
from .. import professions

# Fold Turkish letters (both cases) to plain ASCII so matching is
# locale-independent: ı/İ/I/i -> i, ş/Ş -> s, ğ/Ğ -> g, ü/Ü -> u, ö/Ö -> o, ç/Ç -> c.
_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "I": "i", "i": "i",
    "ş": "s", "Ş": "s",
    "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u",
    "ö": "o", "Ö": "o",
    "ç": "c", "Ç": "c",
})


def _fold(text: str) -> str:
    text = (text or "").replace("̇", "")   # drop combining dot from İ.lower()
    text = text.translate(_TR_MAP)
    return text.lower()


def _pad(text: str) -> str:
    # Fold, collapse whitespace, and wrap in spaces so edge keywords
    # (" ai ", " hr ", " sr ") can match at word boundaries.
    return " " + re.sub(r"\s+", " ", _fold(text)) + " "


# --- Category --------------------------------------------------------------
# Highest-scoring category wins; ties broken by order. Keywords are folded ASCII.
_CATEGORY_KEYWORDS = [
    ("Engineering", [
        "developer", "gelistirici", "yazilim", "software", "engineer", "muhendis",
        "backend", "frontend", "full stack", "fullstack", "full-stack", "devops",
        "mobile", "android", "ios", "programci", "programmer", " qa ", "test muhendisi",
        "robotic", "robotik", "otomasyon", "automation", "gomulu", "embedded",
    ]),
    ("Data", [
        "data scientist", "veri bilimci", "data analyst", "veri analisti",
        "data engineer", "veri muhendisi", "machine learning", "makine ogrenmesi",
        "yapay zeka", "artificial intelligence", " ai ", "istatistik", "statistics",
        "business intelligence", "power bi", "big data", "veri analiz",
    ]),
    ("Design", [
        "designer", "tasarim", "tasarimci", " ux", " ui", "ux/ui", "graphic",
        "grafik", "creative", "kreatif", "illustrator",
    ]),
    ("Product", [
        "product manager", "urun yoneticisi", "product owner", "urun muduru",
        "urun sahibi", "product specialist",
    ]),
    ("Finance", [
        "finance", "finans", "muhasebe", "accounting", "accountant", "mali ",
        "denetim", "audit", "auditor", "kontrol", "controller", "kontrolor",
        "butce", "budget", "treasury", "hazine", "yatirim", "investment",
        " risk ", "vergi", " tax ", "raporlama",
    ]),
    ("Sales", [
        "sales", "satis", "account executive", "account manager", "musteri temsilcisi",
        "is gelistirme", "business development", "bayi", "ihracat", "export",
    ]),
    ("Marketing", [
        "marketing", "pazarlama", " seo ", " sem ", "social media", "sosyal medya",
        "icerik", "content", "brand", "marka", "reklam", "advertising",
        "dijital pazarlama", "digital marketing", "growth", "iletisim",
    ]),
    ("HR", [
        "insan kaynaklari", "human resources", " hr ", "recruiter", "ise alim",
        "talent", "yetenek", "bordro", "payroll", "ozluk",
    ]),
    ("Operations", [
        "operasyon", "operations", "lojistik", "logistics", "tedarik",
        "supply chain", "uretim", "production", "planlama", "planning",
        "depo", "warehouse", "envanter", "inventory", "satin alma", "procurement",
        "kalite", "quality",
    ]),
]

# --- Seniority -------------------------------------------------------------
# First match wins (so "Senior Manager" -> Manager). Folded ASCII keywords.
# Note: Turkish "uzman" = specialist (Mid, the default) and "uzman yardimcisi"
# = assistant specialist (Junior, via "yardimcisi").
_SENIORITY_KEYWORDS = [
    ("Intern", ["intern", "stajyer", "staj ", "trainee", "bursiyer"]),
    ("Manager", [
        "manager", "mudur", "yonetici", " sef ", "head of", "director",
        "direktor", "chief", "genel mudur",
    ]),
    ("Lead", ["lead", "principal", "staff engineer", "takim lideri", "team lead"]),
    ("Senior", ["senior", "kidemli", " sr ", "sr."]),
    ("Junior", [
        "junior", " jr ", "jr.", "yardimcisi", "assistant", "asistan",
        "yeni mezun", "new grad", "entry level", "entry-level", "associate",
        "baslangic",
    ]),
]

# --- Skill tags ------------------------------------------------------------
_TAG_PATTERNS = [
    ("python", r"\bpython\b"),
    ("java", r"\bjava\b"),
    ("javascript", r"\bjavascript\b|\bjs\b"),
    ("typescript", r"\btypescript\b|\bts\b"),
    ("react", r"\breact\b"),
    ("angular", r"\bangular\b"),
    ("vue", r"\bvue\b"),
    ("node", r"\bnode\.?js\b|\bnode\b"),
    ("c#", r"\bc#|\bc sharp\b"),
    (".net", r"\.net\b|\bdotnet\b"),
    ("php", r"\bphp\b"),
    ("go", r"\bgolang\b"),
    ("sql", r"\bsql\b"),
    ("mysql", r"\bmysql\b"),
    ("postgresql", r"\bpostgres(?:ql)?\b"),
    ("mongodb", r"\bmongo(?:db)?\b"),
    ("sap", r"\bsap\b"),
    ("excel", r"\bexcel\b|\bms office\b"),
    ("power bi", r"\bpower ?bi\b"),
    ("tableau", r"\btableau\b"),
    ("aws", r"\baws\b|\bamazon web services\b"),
    ("azure", r"\bazure\b"),
    ("gcp", r"\bgcp\b|\bgoogle cloud\b"),
    ("docker", r"\bdocker\b"),
    ("kubernetes", r"\bkubernetes\b|\bk8s\b"),
    ("linux", r"\blinux\b"),
    ("git", r"\bgit\b"),
    ("django", r"\bdjango\b"),
    ("flask", r"\bflask\b"),
    ("spring", r"\bspring\b"),
    ("machine learning", r"\bmachine learning\b|\bmakine [oö]{1}[gğ]{1}renmesi\b"),
    ("tensorflow", r"\btensorflow\b"),
    ("pytorch", r"\bpytorch\b"),
    ("figma", r"\bfigma\b"),
    ("seo", r"\bseo\b"),
    ("salesforce", r"\bsalesforce\b"),
    ("jira", r"\bjira\b"),
]
_TAG_COMPILED = [(label, re.compile(pat, re.IGNORECASE)) for label, pat in _TAG_PATTERNS]

# --- Offline scam heuristic --------------------------------------------------
# Cheap, free detection for the most common upfront-payment/MLM scam phrasing
# so scam flagging still works with no LLM configured. Deliberately narrow —
# it only catches blatant cases; anything subtler needs an LLM backend, where
# "ghost" (evergreen/staffing-agency) listings are also detected — rules can't
# reliably approximate that judgment call.
_SCAM_KEYWORDS = [
    "kayit ucreti", "registration fee", "application fee", "training fee",
    "investment required", "para yatir", "yatirim gerektirir",
    "piramit", "pyramid scheme", "network marketing", " mlm ",
    "western union", "money gram", "bank details", "banka bilgilerinizi",
    "get rich quick", "earn $$$", "make money from home", "evden kazan",
]


def classify_flag(description: str) -> tuple:
    d = _pad(description)
    for kw in _SCAM_KEYWORDS:
        if kw in d:
            return "scam", f"description mentions '{kw}'"
    return "", ""


def classify_category(title: str, description: str) -> str:
    t = _pad(title)
    d = _pad(description)
    best, best_score = "Other", 0
    for category, keywords in _CATEGORY_KEYWORDS:
        score = 0
        for kw in keywords:
            score += 3 * t.count(kw)   # title hits weigh more
            score += 1 * d.count(kw)
        if score > best_score:
            best, best_score = category, score
    return best


def classify_seniority(title: str) -> str:
    t = _pad(title)
    for level, keywords in _SENIORITY_KEYWORDS:
        if any(kw in t for kw in keywords):
            return level
    return "Mid"  # sensible default for a titled professional posting


def extract_tags(title: str, description: str) -> list:
    text = f"{title}\n{description}"
    return [label for label, rx in _TAG_COMPILED if rx.search(text)]


def classify(title: str, description: str, workplace_type: str = "") -> dict:
    flag, flag_reason = classify_flag(description)
    role = professions.classify(title, description)
    return {
        "category": classify_category(title, description),
        "seniority": classify_seniority(title),
        "tags": professions.normalize_skill_tags(extract_tags(title, description)),
        **role,
        "summary": "",
        "about_company": "",
        "offerings": [],
        "salary": "",
        "formatted_description": "",
        "flag": flag,
        "flag_reason": flag_reason,
        "classified_by": "rules",
        "workplace_type": workplace_type,
    }
