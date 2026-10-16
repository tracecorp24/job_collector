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


_EXPERIENCE_PATTERNS = [
    re.compile(r'(\d+)\s*\+?\s*y[ıi]l', re.IGNORECASE),
    re.compile(r'en\s*az\s*(\d+)\s*y[ıi]l', re.IGNORECASE),
]

_SENIORITY_YEARS = {
    'intern': 0, 'stajyer': 0,
    'junior': 1, 'jr': 1,
    'mid': 3, 'orta': 3,
    'senior': 5, 'sr': 5, 'kıdemli': 5,
    'lead': 7, 'lider': 7, 'başkan': 7, 'yönetici': 7, 'müdür': 7,
}


def extract_experience_years(text):
    """Metinde acikca gecen yil sayisini veya kidem kelimesini deneyim yiline cevirir. Bulunamazsa None.

    "2016 yılından bu yana" gibi takvim yili ifadelerini deneyim suresiyle
    karistirmamak icin makul olmayan (>50) degerler elenir.
    """
    if not text:
        return None
    for pattern in _EXPERIENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                years = int(match.group(1))
            except ValueError:
                continue
            if 0 <= years <= 50:
                return years
    lowered = text.lower()
    for keyword, years in _SENIORITY_YEARS.items():
        if re.search(r'(?<![\w])' + re.escape(keyword) + r'(?![\w])', lowered):
            return years
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
