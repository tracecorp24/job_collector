"""Shared, language-neutral profession taxonomy for postings and search queries.

Categories are broad filter roots. Subgroups stay specific enough to make the
UI useful, while canonical occupation keys let English and Turkish queries
share a comparison cohort.
"""
import re
import unicodedata


OCCUPATIONS = (
    ("Teknoloji ve Mühendislik", "Yazılım Geliştirme", "software_engineering", ("software engineer", "software developer", "software development", "yazilim muhendisi", "yazilim muhendis", "bilgisayar muhendisi", "bilgisayar muhendis", "computer engineer", "yazilim gelistirici", "yazilim gelistirme", "web developer", "web gelistirici", "backend developer", "backend engineer", "frontend developer", "front end developer", "frontend engineer", "full stack developer", "full-stack developer", "fullstack developer", "mobile developer", "mobile engineer", "android developer", "ios developer", "application developer", "programmer", "programci", "yazilim uzmani", "yazilimci")),
    ("Teknoloji ve Mühendislik", "Veri ve Analitik", "data_analytics", ("data analyst", "data analytics", "data engineer", "data scientist", "veri analisti", "veri analist", "veri muhendisi", "veri muhendis", "veri bilimci", "veri bilimi", "business intelligence", "business analyst", "is analisti", "is analist", "bi analyst", "bi developer", "reporting analyst", "istatistikci")),
    ("Teknoloji ve Mühendislik", "Yapay Zeka", "artificial_intelligence", ("machine learning engineer", "machine learning scientist", "machine learning", "artificial intelligence", "ai engineer", "ai researcher", "ai developer", "yapay zeka muhendisi", "yapay zeka muhendis", "yapay zeka uzman", "makine ogrenmesi", "makine ogrenmesi muhendisi", "makine ogrenmesi muhendis", "ml engineer", "deep learning")),
    ("Teknoloji ve Mühendislik", "Siber Güvenlik", "cybersecurity", ("cyber security", "cybersecurity", "security engineer", "security analyst", "information security", "siber guvenlik", "bilgi guvenligi", "soc analyst", "penetration tester", "pentester")),
    ("Teknoloji ve Mühendislik", "Sistem, Ağ ve Bulut", "it_infrastructure", ("devops", "site reliability engineer", " sre ", "cloud engineer", "cloud architect", "system administrator", "systems administrator", "network engineer", "network administrator", "it support", "help desk", "sistem yoneticisi", "ag muhendisi", "ag muhendis", "bulut muhendisi", "bulut muhendis", "it uzman", "system engineer", "systems engineer", "sistem muhendisi", "sistem muhendis", "sistem muhendisligi")),
    ("Teknoloji ve Mühendislik", "Test ve Kalite", "software_testing", ("qa engineer", "quality assurance engineer", "software tester", "test engineer", "test analyst", "software qa", "kalite guvence", "yazilim test", "test muhendisi", "test muhendis", "yazilim test muhendisi", "yazilim test muhendis", "otomasyon test")),
    ("Teknoloji ve Mühendislik", "Makine Mühendisliği", "mechanical_engineering", ("mechanical engineer", "mechanical design engineer", "makine muhendisi", "makine muhendis", "makina muhendisi", "makina muhendis", "mekanik muhendisi", "mekanik muhendis", "mechatronics engineer", "mekatronik muhendisi", "mekatronik muhendis", "hvac engineer", "cad designer", "cad technician")),
    ("Teknoloji ve Mühendislik", "Elektrik ve Elektronik", "electrical_engineering", ("electrical engineer", "electronics engineer", "electrical design engineer", "electrician", "electric engineer", "elektrik muhendisi", "elektrik muhendis", "elektronik muhendisi", "elektronik muhendis", "elektrik elektronik muhendisi", "elektrik elektronik muhendis", "elektrik teknisyeni", "elektronik teknisyeni", "elektrikci")),
    ("Teknoloji ve Mühendislik", "Endüstri ve Otomasyon", "industrial_engineering", ("industrial engineer", "automation engineer", "control systems engineer", "robotics engineer", "process engineer", "endustri muhendisi", "endustri muhendis", "otomasyon muhendisi", "otomasyon muhendis", "robotik muhendisi", "robotik muhendis", "kontrol muhendisi", "kontrol muhendis", "surec muhendisi", "surec muhendis", "calibration engineer", "kalibrasyon muhendisi", "kalibrasyon muhendis", "kalibrasyon muhendisligi")),
    ("Teknoloji ve Mühendislik", "İnşaat ve Altyapı", "civil_engineering", ("civil engineer", "construction engineer", "structural engineer", "site engineer", "insaat muhendisi", "insaat muhendis", "yapi muhendisi", "yapi muhendis", "geotechnical engineer", "survey engineer", "harita muhendisi", "harita muhendis")),
    ("Teknoloji ve Mühendislik", "Üretim ve Proses", "manufacturing_engineering", ("manufacturing engineer", "production engineer", "quality engineer", "plant engineer", "uretim muhendisi", "uretim muhendis", "imalat muhendisi", "imalat muhendis", "kalite muhendisi", "kalite muhendis", "proses muhendisi", "proses muhendis")),
    ("Finans ve Muhasebe", "Muhasebe ve Bordro", "accounting", ("accountant", "accounting specialist", "accounting manager", "bookkeeper", "payroll specialist", "payroll administrator", "muhasebeci", "muhasebe uzmani", "muhasebe muduru", "bordro uzmani", "mali musavir")),
    ("Finans ve Muhasebe", "Finansal Analiz ve Bütçe", "financial_analysis", ("finance", "finans", "financial analyst", "finance analyst", "financial planning", "fp&a", "financial controller", "treasury analyst", "finans analisti", "finans uzmani", "butce analisti", "finansal planlama", "hazine uzmani")),
    ("Finans ve Muhasebe", "Denetim ve Vergi", "audit_tax", ("internal auditor", "external auditor", "audit manager", "tax accountant", "tax specialist", "denetci", "ic denetim", "bagimsiz denetim", "vergi uzmani", "vergi danismani")),
    ("Finans ve Muhasebe", "Bankacılık ve Yatırım", "banking_investment", ("investment analyst", "investment banker", "banker", "portfolio manager", "equity analyst", "bankacilik uzmani", "yatirim analisti", "portfoy yoneticisi")),
    ("Finans ve Muhasebe", "Risk ve Sigorta", "risk_insurance", ("risk analyst", "actuary", "actuarial analyst", "insurance analyst", "risk analisti", "aktuer", "sigorta uzmani", "hasar uzmani")),
    ("Ticaret ve Müşteri", "Satış ve İş Geliştirme", "sales_business_development", ("sales", "satis", "sales representative", "sales executive", "sales manager", "account executive", "business development", "business development manager", "field sales", "satis temsilcisi", "satis uzmani", "satis muduru", "is gelistirme uzmani", "ihracat uzmani")),
    ("Ticaret ve Müşteri", "Müşteri Hizmetleri", "customer_service", ("customer service", "customer support", "client services", "customer success", "call center", "contact center", "musteri hizmetleri", "musteri temsilcisi", "cagri merkezi", "musteri deneyimi")),
    ("Ticaret ve Müşteri", "Satın Alma", "procurement", ("procurement specialist", "procurement manager", "purchasing manager", "buyer", "purchasing agent", "satin alma uzmani", "satin alma muduru", "tedarik uzmani")),
    ("Pazarlama ve İletişim", "Dijital Pazarlama", "digital_marketing", ("marketing", "pazarlama", "digital marketing", "performance marketing", "seo specialist", "sem specialist", "growth marketer", "paid media", "dijital pazarlama", "performans pazarlama", "seo uzmani", "dijital reklam")),
    ("Pazarlama ve İletişim", "İçerik ve Marka", "content_brand", ("content writer", "content strategist", "content marketer", "brand manager", "copywriter", "social media", "icerik uzmani", "marka yoneticisi", "sosyal medya uzmani", "metin yazari")),
    ("Pazarlama ve İletişim", "Kurumsal İletişim ve Halkla İlişkiler", "communications_pr", ("public relations", "communications specialist", "communications manager", "media relations", "kurumsal iletisim", "halkla iliskiler", "basin danismani")),
    ("Ürün ve Tasarım", "Ürün Yönetimi", "product_management", ("product manager", "product owner", "product specialist", "urun yoneticisi", "urun sahibi", "urun uzmani", "product operations")),
    ("Ürün ve Tasarım", "UX ve UI Tasarımı", "ux_ui_design", ("ux designer", "ui designer", "ux researcher", "interaction designer", "user experience", "user interface", "ux tasarimci", "ui tasarimci", "kullanici deneyimi tasarim")),
    ("Ürün ve Tasarım", "Görsel ve Grafik Tasarım", "visual_design", ("graphic designer", "visual designer", "web designer", "motion designer", "illustrator", "grafik tasarimci", "gorsel tasarimci", "animator", "multimedia designer")),
    ("İnsan ve Eğitim", "İnsan Kaynakları", "human_resources", ("human resources", "hr specialist", "hr manager", "recruiter", "recruitment specialist", "talent acquisition", "people operations", "insan kaynaklari", "ise alim uzmani", "ik uzmani", "ik muduru", "yetenėk kazanimi")),
    ("İnsan ve Eğitim", "Eğitim ve Öğretim", "education", ("teacher", "educator", "lecturer", "professor", "school counselor", "instructional designer", "ogretmen", "egitmen", "ogretim gorevlisi", "akademisyen", "egitim uzmani")),
    ("Sağlık ve Yaşam Bilimleri", "Doktor ve Uzman Hekim", "physician", ("physician", "medical doctor", "medical officer", "surgeon", "doctor", "hekim", "doktor", "uzman doktor", "dis hekimi", "veterinarian", "veteriner")),
    ("Sağlık ve Yaşam Bilimleri", "Hemşirelik ve Hasta Bakımı", "nursing_patient_care", ("registered nurse", "nurse", "nursing assistant", "caregiver", "midwife", "hemsire", "hasta bakici", "ebe", "paramedic", "acil tip teknisyeni")),
    ("Sağlık ve Yaşam Bilimleri", "Eczacılık ve İlaç", "pharmacy", ("pharmacist", "pharmacy technician", "clinical pharmacist", "eczaci", "eczane teknisyeni", "farmakovijilans", "medical representative", "ilac ruhsatlandirma")),
    ("Sağlık ve Yaşam Bilimleri", "Laboratuvar ve Biyomedikal", "clinical_laboratory", ("lab technician", "laboratory technician", "medical laboratory", "biomedical engineer", "clinical research associate", "lab technician", "laboratuvar teknisyeni", "biyomedikal muhendisi", "klinik arastirma")),
    ("Sağlık ve Yaşam Bilimleri", "Moleküler Biyoloji ve Genetik", "molecular_biology", ("molecular biology", "molecular biologist", "molekuler biyoloji", "molekuler biyolog", "molekuler biyoloji ve genetik", "genetik muhendisi", "genetic engineer", "biyolog", "biologist")),
    ("Lojistik ve Operasyon", "Lojistik ve Taşımacılık", "logistics_transport", ("logistics coordinator", "logistics specialist", "transport planner", "fleet manager", "customs specialist", "lojistik uzmani", "lojistik planlama", "tasimacilik", "gümrük uzmani")),
    ("Lojistik ve Operasyon", "Tedarik Zinciri ve Planlama", "supply_chain", ("supply chain", "demand planner", "supply planner", "inventory planner", "supply chain analyst", "tedarik zinciri", "talep planlama", "stok planlama")),
    ("Lojistik ve Operasyon", "Depo ve Envanter", "warehouse_inventory", ("warehouse associate", "warehouse manager", "inventory specialist", "inventory control", "forklift operator", "depo sorumlusu", "depo elemani", "envanter uzmani", "forklift operatoru")),
    ("Lojistik ve Operasyon", "İş ve Saha Operasyonları", "business_operations", ("operations", "operasyon", "operations specialist", "operations manager", "operations coordinator", "project coordinator", "program coordinator", "operasyon uzmani", "operasyon muduru", "saha operasyon")),
    ("Hukuk ve Uyum", "Hukuk", "law", ("attorney", "lawyer", "legal counsel", "legal assistant", "paralegal", "associate attorney", "avukat", "hukuk danismani", "hukuk musaviri", "stajyer avukat")),
    ("Hukuk ve Uyum", "Uyum ve Veri Gizliliği", "compliance", ("compliance officer", "compliance analyst", "compliance specialist", "privacy officer", "data protection officer", "uyum uzmani", "mevzuat uzmani", "veri koruma uzman")),
    ("Yönetim ve İdari İşler", "İdari Destek ve Asistanlık", "administrative_assistance", ("administrative assistant", "executive assistant", "office administrator", "office manager", "receptionist", "executive secretary", "idari isler", "yonetici asistani", "ofis yoneticisi", "sekreter", "resepsiyonist")),
    ("Yönetim ve İdari İşler", "Proje ve Program Yönetimi", "project_program_management", ("project manager", "program manager", "project management", "project lead", "proje yoneticisi", "program yoneticisi", "proje uzmani", "pmO")),
    ("Turizm ve Yiyecek Hizmetleri", "Yiyecek ve İçecek", "food_beverage", ("chef", "cook", "barista", "restaurant manager", "food service", "asci", "sef", "garson", "barista", "mutfak elemani")),
    ("Turizm ve Yiyecek Hizmetleri", "Turizm ve Konaklama", "hospitality_tourism", ("hotel manager", "hotel receptionist", "front desk agent", "travel consultant", "tour guide", "otel muduru", "otel resepsiyon", "turizm uzmani", "seyahat danismani")),
    ("Gayrimenkul ve Sigorta", "Gayrimenkul", "real_estate", ("real estate agent", "real estate broker", "property manager", "real estate consultant", "emlak danismani", "emlak uzmani", "gayrimenkul danismani")),
    ("Güvenlik ve Teknik Hizmetler", "Fiziksel Güvenlik", "physical_security", ("security guard", "security officer", "loss prevention", "guvenlik gorevlisi", "ozel guvenlik")),
    ("Tarım ve Çevre", "Tarım ve Hayvancılık", "agriculture", ("agronomist", "farm manager", "agricultural engineer", "crop specialist", "ziraat muhendisi", "ziraat teknikeri", "tarim uzmani", "veterinary technician")),
    ("Tarım ve Çevre", "Çevre ve Sürdürülebilirlik", "environment_sustainability", ("environmental engineer", "environmental scientist", "sustainability specialist", "sustainability manager", "cevre muhendisi", "cevre uzmani", "surdurulebilirlik uzman")),
    ("Genel Meslekler", "Diğer / Belirtilmemiş", "other", ()),
)

MAIN_GROUPS = tuple(dict.fromkeys(row[0] for row in OCCUPATIONS))
SUBGROUPS = tuple(dict.fromkeys(row[1] for row in OCCUPATIONS))
LABELS = tuple(row[1] for row in OCCUPATIONS)


def fold(value):
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.translate(str.maketrans({"ı": "i", "ß": "ss"}))


_PARENT_BY_SUBGROUP = {fold(subgroup): group for group, subgroup, _, _ in OCCUPATIONS}


def _pattern(alias):
    folded = fold(alias).strip()
    if not folded:
        return None
    return re.compile(r"(?<![\w])" + re.escape(folded).replace(r"\ ", r"\s+") + r"(?![\w])")


_COMPILED = [(group, subgroup, code, [_pattern(alias) for alias in aliases if _pattern(alias)])
             for group, subgroup, code, aliases in OCCUPATIONS]


def normalize_skill_tags(tags):
    aliases = {
        "js": "javascript", "ecmascript": "javascript", "ts": "typescript",
        "node.js": "node", "nodejs": "node", "golang": "go", "c sharp": "c#",
        "c-sharp": "c#", "dotnet": ".net", "dot net": ".net", "postgres": "postgresql",
        "postgre sql": "postgresql", "powerbi": "power bi", "amazon web services": "aws",
        "google cloud platform": "gcp", "k8s": "kubernetes", "ms excel": "excel",
        "machine-learning": "machine learning", "ml": "machine learning",
    }
    result = []
    seen = set()
    for raw in tags or []:
        value = re.sub(r"\s+", " ", str(raw or "").strip()).casefold()
        value = aliases.get(fold(value), value)
        key = fold(value)
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def classify(title, description=""):
    title_text, description_text = fold(title), fold(description)
    title_hits = []
    body_hits = []
    for group, subgroup, code, patterns in _COMPILED:
        if not patterns:
            continue
        if any(pattern.search(title_text) for pattern in patterns):
            title_hits.append((group, subgroup, code))
        elif any(pattern.search(description_text) for pattern in patterns):
            body_hits.append((group, subgroup, code))

    # A clear title is the strongest occupation signal. Description matches
    # may add specialisms in the same field but must not misclassify a stray
    # mention of an unrelated department as the job's profession.
    selected = list(title_hits)
    if title_hits:
        main = title_hits[0][0]
        selected.extend(hit for hit in body_hits if hit[0] == main)
    else:
        selected.extend(body_hits[:5])
    if not selected:
        return {"profession_groups": ["Genel Meslekler"],
                "profession_subgroups": ["Diğer / Belirtilmemiş"],
                "profession_code": "other", "normalized_title": re.sub(r"\s+", " ", str(title or "")).strip()}

    groups = list(dict.fromkeys(group for group, _, _ in selected))
    subgroups = list(dict.fromkeys(subgroup for _, subgroup, _ in selected))
    primary = title_hits[0] if title_hits else selected[0]
    canonical_title = primary[1]
    return {"profession_groups": groups[:4], "profession_subgroups": subgroups[:8],
            "profession_code": primary[2], "normalized_title": canonical_title}


_TURKISH_WORDS = frozenset("uzmani uzman muhendis muhendisi muhendislik yazilim yazilimci gelistirici gelistirme yoneticisi yonetici mudur analisti analist veri operasyon operasyonu satis finans muhasebe pazarlama tasarim urun lojistik tedarik musteri guvenlik egitim saglik hukuk tarim sorumlusu teknisyeni ogretmen hemsire avukat muhasebeci egitmen eczaci calisan kalibrasyon biyoloji biyolog molekuler".split())
_ENGLISH_WORDS = frozenset("engineer engineering developer software analyst data manager director specialist technician teacher nurse accountant accounting attorney recruiter designer design consultant coordinator associate assistant administrator executive scientist researcher operations sales finance marketing product logistics supply customer security education healthcare lawyer calibration biology biologist molecular".split())


def query_metadata(keyword, location=""):
    text = fold(keyword)
    tokens = set(re.findall(r"[a-z0-9+#.]+", text))
    if any(char in str(keyword or "") for char in "çğıöşüÇĞİÖŞÜ") or tokens & _TURKISH_WORDS:
        language = "tr"
    elif tokens & _ENGLISH_WORDS:
        language = "en"
    else:
        language = "other"
    role = classify(keyword, "")
    loc = fold(location).split(",", 1)[0]
    loc = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", loc)).strip()
    return {"keyword_language": language, "profession_group": role["profession_groups"][0],
            "profession_code": role["profession_code"], "location_key": loc}


def tree():
    result = {group: [] for group in MAIN_GROUPS}
    for group, subgroup, _, _ in OCCUPATIONS:
        if subgroup not in result[group]:
            result[group].append(subgroup)
    return result


def clean_suggestions(groups, subgroups):
    def ordered(values, allowed):
        wanted = {fold(value) for value in values if isinstance(value, str)}
        return [label for label in allowed if fold(label) in wanted]
    selected_groups = ordered(groups, MAIN_GROUPS)
    selected_subgroups = ordered(subgroups, SUBGROUPS)
    group_keys = {fold(group) for group in selected_groups}
    selected_subgroups = [subgroup for subgroup in selected_subgroups
                          if not group_keys or fold(_PARENT_BY_SUBGROUP[fold(subgroup)]) in group_keys]
    parent_groups = [_PARENT_BY_SUBGROUP[fold(subgroup)] for subgroup in selected_subgroups]
    return list(dict.fromkeys(selected_groups + parent_groups)), selected_subgroups
