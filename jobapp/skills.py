"""
Light sürümün bağımsız, kural tabanlı yetenek/deneyim/çalışma tipi çıkarımı.

js/data/constants.js icindeki SKILL_TRACK_MAP + SKILL_ALIASES'in Python
karsiligi, artı havuzdaki muhendislik/uretim ilanlarinda gorulen ek terimler
(PLC, SCADA, AutoCAD, SolidWorks, MATLAB, SAP vb.). LLM anahtari olmadan da
(--rules-only) veya LLM sonucunu tamamlamak icin (union) kullanilir.

Bu liste kasitli olarak js tarafiyla ayni ama Python'da tutuluyor; ikisini
elle senkronize tutmak, ortak bir JSON dosyasindan okumaktan daha basit ve
mevcut "duz script, paylasilan kapsam" mimarisine (bkz. README) daha uygun.
"""

import re

# Kanonik ad -> gorunen (title-case) etiket. Anahtarlar kucuk harf, kelime siniri ile aranir.
SKILL_KEYWORDS = {
    # backend
    'go': 'Go', 'golang': 'Go', 'java': 'Java', 'spring': 'Spring',
    'c#': 'C#', '.net': '.NET', 'dotnet': '.NET', 'php': 'PHP',
    'grpc': 'gRPC', 'kafka': 'Kafka', 'postgresql': 'PostgreSQL', 'postgres': 'PostgreSQL',
    'mysql': 'MySQL', 'sql server': 'SQL Server', 'redis': 'Redis', 'microservices': 'Microservices',
    'mikroservis': 'Microservices', 'node.js': 'Node.js', 'nodejs': 'Node.js', 'express': 'Express',
    'mongodb': 'MongoDB', 'django': 'Django', 'flask': 'Flask', 'fastapi': 'FastAPI',
    # devops
    'kubernetes': 'Kubernetes', 'k8s': 'Kubernetes', 'docker': 'Docker', 'aws': 'AWS',
    'gcp': 'GCP', 'azure': 'Azure', 'terraform': 'Terraform', 'jenkins': 'Jenkins',
    'ci/cd': 'CI/CD', 'prometheus': 'Prometheus', 'linux': 'Linux', 'ansible': 'Ansible',
    'grafana': 'Grafana', 'nginx': 'Nginx',
    # frontend
    'react': 'React', 'vue.js': 'Vue.js', 'vue': 'Vue.js', 'angular': 'Angular',
    'javascript': 'JavaScript', 'typescript': 'TypeScript', 'html5': 'HTML5', 'css': 'CSS',
    'next.js': 'Next.js', 'nextjs': 'Next.js', 'nuxt.js': 'Nuxt.js', 'nuxtjs': 'Nuxt.js',
    'redux': 'Redux', 'pinia': 'Pinia', 'tailwindcss': 'TailwindCSS', 'tailwind': 'TailwindCSS',
    'flutter': 'Flutter', 'dart': 'Dart', 'swift': 'Swift',
    'kotlin': 'Kotlin', 'bloc': 'BLoC', 'ios': 'iOS', 'android': 'Android',
    # data
    'python': 'Python', 'tensorflow': 'TensorFlow', 'pytorch': 'PyTorch', 'pandas': 'Pandas',
    'scikit-learn': 'scikit-learn', 'nlp': 'NLP', 'llm': 'LLM', 'sql': 'SQL', 'r': 'R',
    'machine learning': 'Machine Learning', 'data science': 'Data Science', 'excel': 'Excel',
    'power bi': 'Power BI', 'tableau': 'Tableau',
    # muhendislik / uretim / diger (scraper havuzunda sikca gorulen terimler)
    'plc': 'PLC', 'scada': 'SCADA', 'autocad': 'AutoCAD', 'solidworks': 'SolidWorks',
    'matlab': 'MATLAB', 'catia': 'CATIA', 'sap': 'SAP', 'iso 9001': 'ISO 9001',
    'lean manufacturing': 'Lean Manufacturing', 'six sigma': 'Six Sigma', 'kaizen': 'Kaizen',
    'c++': 'C++', 'embedded': 'Embedded Systems', 'gomulu sistem': 'Embedded Systems',
    'salesforce': 'Salesforce', 'sas': 'SAS', 'crm': 'CRM', 'erp': 'ERP',
}

# Regex derlemeleri lazy: modul import edildiginde bir kez hesaplanir.
_SKILL_PATTERNS = None


def _get_patterns():
    global _SKILL_PATTERNS
    if _SKILL_PATTERNS is None:
        patterns = []
        for key, label in SKILL_KEYWORDS.items():
            # '.', '#', '+' gibi regex-ozel karakterleri escape et; kelime siniri kullan.
            escaped = re.escape(key)
            patterns.append((re.compile(r'(?<![\w])' + escaped + r'(?![\w])', re.IGNORECASE), label))
        _SKILL_PATTERNS = patterns
    return _SKILL_PATTERNS


def extract_skills(title, desc=''):
    """Baslik + aciklama metninden bilinen yetenek anahtar kelimelerini tarar; kanonik (title-case)
    liste doner. Buyuk/kucuk harf duyarsiz, kelime sinirli tarama; alias'lar kanonik gorunen ada
    katlanir (or. 'k8s' bulunursa listeye 'Kubernetes' yazilir, ayni etiket iki kez eklenmez).

    Not: `desc` geriye donuk uyumluluk icin opsiyoneldir; tek argumanla cagirinca (eski kullanim)
    o argumanin tamami taranir. Python tarafinda skill sozlugunun tek dogruluk kaynagi bu dosyadir
    (frontend js/data/constants.js SKILL_TRACK_MAP + SKILL_ALIASES ile elle hizali tutulur)."""
    text = f'{title or ""} {desc or ""}'
    if not text.strip():
        return []
    found = []
    seen = set()
    for pattern, label in _get_patterns():
        if pattern.search(text) and label not in seen:
            seen.add(label)
            found.append(label)
    return found


# Deneyim yalnız adaydan istenen süreyi anlatan cümlelerden okunur. Şirketin yaşı ("30 yılı aşkın
# deneyimiyle", "more than 35 years of industry experience") ve açıklamada geçen kıdem kelimeleri
# ("we lead...", "mentor junior engineers") deneyim sayılmaz. Aralıkta alt sınır alınır ("3-5 yıl" → 3).
_N = r'(?<![\d.,])(\d{1,2})(?![\d])'
_RANGE = _N + r'(?:\s*(?:-|–|—|ila|to)\s*(\d{1,2}))?'
_YEAR = r'(?:y[ıi]l\w*|years?|yrs?)'
_EXP = r'(?:deneyim\w*|tecr[üu]be\w*|experience|exp\b)'
_REQUIREMENT_PREFIX = re.compile(r'(?:en\s*az|minimum(?:\s+of)?|min\.|asgari|at\s+least)\s*' + _RANGE + r'\s*\+?\s*' + _YEAR, re.IGNORECASE)
_REQUIREMENT_SUFFIX = (
    re.compile(_RANGE + r'\s*(?:\+|plus)?\s*' + _YEAR + r"(?:'s?|’s?)?\b[^.\n;]{0,40}?" + _EXP, re.IGNORECASE),
    re.compile(_N + r'\s*\+\s*' + _YEAR, re.IGNORECASE),
    re.compile(_N + r'\s*(?:-|–|—|to)\s*(\d{1,2})\s*' + _YEAR, re.IGNORECASE),
)
_COMPANY_CONTEXT = re.compile(
    r'y[ıi]l[ıi]\s*a[şs](?:k[ıi]n|an)|y[ıi]ld[ıi]r|tecr[üu]besi\s*(?:yle|ile)|deneyimi\s*(?:yle|ile)|birikim'
    r'|since|founded|established|kurulu[şs]|kurulan|history|heritage|legacy|industry experience'
    r'|in the industry|track record', re.IGNORECASE)
_UP_TO = re.compile(r'(?:up\s+to|en\s+fazla|maksimum)\s*$', re.IGNORECASE)
_TITLE_LEVELS = (  # yalnız unvandan, Türkçe harfler sadeleştirilmiş metinde
    (re.compile(r'\b(?:intern|interns|internship|trainee|bursiyer|staj\w*|yeni mezun|new grad\w*)\b'), 0),
    (re.compile(r'\b(?:junior|jr)\b'), 1),
    (re.compile(r'\b(?:senior|sr|kidemli)\b'), 5),
    (re.compile(r'\b(?:lead|leader|lider\w*|mudur\w*|manager|director|head of)\b'), 7),
)
_FOLD = str.maketrans('ıİIşŞğĞüÜöÖçÇ', 'iiissgguuoocc')


def requirement_years(text):
    candidates = []
    for pattern, limit, check_company in [(_REQUIREMENT_PREFIX, 25, False)] + [(p, 15, True) for p in _REQUIREMENT_SUFFIX]:
        for match in pattern.finditer(text):
            years = int(match.group(1))
            if years > limit:
                continue
            if check_company and _COMPANY_CONTEXT.search(text[max(0, match.start() - 40):match.end() + 30]):
                continue
            if _UP_TO.search(text[max(0, match.start() - 15):match.start()]):
                years = 0
            candidates.append((match.start(), years))
    return min(candidates)[1] if candidates else None  # metinde ilk geçen şart


def extract_experience_years(description, title=''):
    """İlanın adaydan istediği deneyim yılını döndürür; bulunamazsa None.

    Önce açıklamadaki şart cümlelerine bakılır; yoksa unvandaki kıdem kelimesinden kaba bir tahmin yapılır.
    """
    years = requirement_years(description or '')
    if years is not None:
        return years
    folded = (title or '').translate(_FOLD).lower()
    for pattern, level in _TITLE_LEVELS:
        if pattern.search(folded):
            return level
    return None


def extract_work_type(text):
    """'Remote' / 'Hybrid' / 'Office' tahmini; belirsizse None."""
    if not text:
        return None
    lowered = text.lower()
    if 'uzaktan' in lowered or 'remote' in lowered:
        return 'Remote'
    if 'hibrit' in lowered or 'hybrid' in lowered:
        return 'Hybrid'
    if 'iş yerinde' in lowered or 'ofiste' in lowered or 'office' in lowered:
        return 'Office'
    return None
