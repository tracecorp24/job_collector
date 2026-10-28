"""Çok dilli arama ve meslek eşleştirme motoru (Trace / NextStep uyumlu).

Türkçe ve yabancı dillerdeki meslek unvanlarını, yetenekleri ve eşdeğerleri
birbirine bağlar; çok dilli genişletme ve hızlı çeviri desteği sağlar.
"""
from collections import OrderedDict
import hashlib
import json
import logging
import re
import threading
import urllib.parse
import urllib.request
from sqlalchemy import or_, and_, func

log = logging.getLogger(__name__)

# Önbellek ve Google Translate yapılandırması
_TRANSLATE_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_MAX_CACHE = 512
_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target}&dt=t&q={text}"

# Genel unvan aileleri (yalnızca kullanıcı spesifik meslek yerine genel kelimeyi girdiğinde eşleşir)
GENERAL_ROLES = {
    "engineer_general",
    "developer_general",
    "manager_general",
    "specialist_general",
    "analyst_general",
    "designer_general",
}

# Trace / NextStep uyumlu çok dilli meslek eşdeğerleri
JOB_ROLE_EQUIVALENTS = [
    ["software_engineer", "yazılım mühendisi", "yazılım mühendisliği", "yazılım geliştirici", "yazılım geliştiricisi", "yazılım uzmanı", "yazılımcı", "yazılım", "software engineer", "software developer", "softwareentwickler", "softwareentwicklerin", "développeur logiciel", "ingeniero de software", "software dev", "sw engineer", "swe", "software"],
    ["computer_engineer", "bilgisayar mühendisi", "bilgisayar mühendisliği", "computer engineer"],
    ["mechanical_engineer", "makine mühendisi", "makine mühendisliği", "makina mühendisi", "makina mühendisliği", "mechanical engineer", "maschinenbauingenieur", "ingeniero mecánico"],
    ["mechanical_design", "mekanik tasarım mühendisi", "mekanik tasarım mühendisliği", "mekanik tasarım uzmanı", "mekanik tasarımcı", "mekanik tasarım", "makine tasarım mühendisi", "makine tasarımı", "mechanical design engineer", "mechanical designer", "mechanical design", "mechanische konstruktion", "conception mécanique"],
    ["electrical_engineer", "elektrik mühendisi", "elektrik mühendisliği", "electrical engineer", "elektroingenieur"],
    ["electronics_engineer", "elektronik mühendisi", "elektronik mühendisliği", "electronics engineer"],
    ["industrial_engineer", "endüstri mühendisi", "endüstri mühendisliği", "industrial engineer", "wirtschaftsingenieur"],
    ["civil_engineer", "inşaat mühendisi", "inşaat mühendisliği", "civil engineer", "bauingenieur"],
    ["chemical_engineer", "kimya mühendisi", "kimya mühendisliği", "chemical engineer", "chemieingenieur"],
    ["data_engineer", "veri mühendisi", "veri mühendisliği", "data engineer", "dateningenieur"],
    ["data_scientist", "veri bilimci", "veri bilimcisi", "data scientist", "datenwissenschaftler"],
    ["cloud_engineer", "bulut mühendisi", "bulut bilişim mühendisliği", "cloud engineer"],
    ["devops_engineer", "devops mühendisi", "devops mühendisliği", "devops engineer"],
    ["sre_engineer", "sre", "site reliability engineer", "site reliability", "sre mühendisi", "site reliability engineering", "reliability engineer"],
    ["ml_engineer", "makine öğrenmesi mühendisi", "machine learning engineer"],
    ["ai_engineer", "yapay zeka mühendisi", "yapay zeka mühendisliği", "yapay zeka uzmanı", "yapay zeka geliştirici", "yapay zeka", "ai engineer", "ai developer", "ai specialist", "artificial intelligence engineer", "artificial intelligence", "ai", "ki ingenieur", "ki entwickler"],
    ["cybersecurity_engineer", "siber güvenlik mühendisi", "siber güvenlik mühendisliği", "cybersecurity engineer", "cyber security engineer"],
    ["robotics_engineer", "robotik mühendisi", "robotik mühendisliği", "robotics engineer"],
    ["mechatronics_engineer", "mekatronik mühendisi", "mekatronik mühendisliği", "mechatronics engineer"],
    ["aerospace_engineer", "havacılık ve uzay mühendisi", "havacılık ve uzay mühendisliği", "aerospace engineer"],
    ["frontend_developer", "ön yüz geliştirici", "ön yüz geliştiricisi", "frontend developer", "front-end developer", "frontend geliştirici", "frontend", "front-end", "front end", "ön yüz", "önyüz", "önyüz geliştirici"],
    ["backend_developer", "arka uç geliştirici", "arka uç geliştiricisi", "backend developer", "back-end developer", "backend geliştirici", "backend", "back-end", "back end", "arka uç", "arka yüz", "arka yüz geliştirici"],
    ["fullstack_developer", "full stack developer", "full-stack developer", "fullstack developer", "fullstack geliştirici", "fullstack", "full stack", "full-stack", "tam yığın geliştirici"],
    ["consultant", "danışman", "danışmanı", "danışmanlık", "consultant", "consulting", "berater", "conseiller", "consultor"],
    ["sales_manager", "satış müdürü", "sales manager", "vertriebsleiter"],
    ["project_manager", "proje yöneticisi", "project manager", "projektmanager"],
    ["product_manager", "ürün yöneticisi", "product manager", "produktmanager"],
    ["qa_engineer", "test mühendisi", "yazılım test mühendisi", "software test engineer", "qa engineer", "quality assurance engineer", "testingenieur", "ingénieur test", "kalite güvence"],
    ["qa_tester", "yazılım test uzmanı", "software tester", "qa tester", "test uzmanı"],
    ["automation_engineer", "otomasyon mühendisi", "automation engineer", "automatisierungsingenieur", "ingénieur automatisme"],
    ["network_engineer", "ağ mühendisi", "network engineer", "netzwerkingenieur", "ingénieur réseau"],
    ["system_administrator", "sistem yöneticisi", "system administrator", "systems administrator", "sysadmin", "systemadministrator", "administrateur système"],
    ["database_administrator", "veritabanı yöneticisi", "veri tabanı yöneticisi", "database administrator", "datenbankadministrator", "administrateur de bases de données"],
    ["business_analyst", "iş analisti", "business analyst", "iş analiz uzmanı", "analyste métier"],
    ["data_analyst", "veri analisti", "veri analistliği", "veri analizi", "data analyst", "datenanalyst", "analyste de données", "analista de datos"],
    ["mobile_developer", "mobil geliştirici", "mobil uygulama geliştirici", "mobile developer", "mobile application developer", "développeur mobile", "mobil", "mobile"],
    ["android_developer", "android geliştirici", "android developer", "android entwickler", "développeur android"],
    ["ios_developer", "ios geliştirici", "ios developer", "ios entwickler", "développeur ios"],
    ["game_developer", "oyun geliştirici", "game developer", "spieleentwickler", "développeur de jeux"],
    ["embedded_engineer", "gömülü yazılım mühendisi", "embedded software engineer", "gömülü sistem mühendisi", "embedded systems engineer"],
    ["electrical_electronics_engineer", "elektrik elektronik mühendisi", "elektrik-elektronik mühendisi", "elektrik elektronik mühendisliği", "elektrik-elektronik mühendisliği", "electrical and electronics engineer"],
    ["environmental_engineer", "çevre mühendisi", "çevre mühendisliği", "environmental engineer", "umweltingenieur", "ingénieur environnement"],
    ["biomedical_engineer", "biyomedikal mühendisi", "biyomedikal mühendisliği", "biomedical engineer", "biomedizintechniker"],
    ["quality_engineer", "kalite mühendisi", "quality engineer", "qualitätsingenieur", "ingénieur qualité"],
    ["production_engineer", "üretim mühendisi", "production engineer", "manufacturing engineer", "produktionsingenieur", "ingénieur production"],
    ["software_architect", "yazılım mimarı", "software architect", "softwarearchitekt", "architecte logiciel"],
    ["building_architect", "mimar", "architect", "architekt", "architecte", "arquitecto"],
    ["graphic_designer", "grafik tasarımcı", "grafik tasarımcısı", "graphic designer", "grafikdesigner", "graphiste", "diseñador gráfico"],
    ["ux_designer", "kullanıcı deneyimi tasarımcısı", "ux designer", "user experience designer", "designer ux"],
    ["ui_designer", "arayüz tasarımcısı", "ui designer", "user interface designer", "designer ui"],
    ["accountant", "muhasebeci", "muhasebe uzmanı", "accountant", "buchhalter", "comptable", "contable"],
    ["financial_analyst", "finans analisti", "finansal analist", "financial analyst", "finanzanalyst", "analyste financier", "analista financiero"],
    ["hr_specialist", "insan kaynakları uzmanı", "hr specialist", "human resources specialist", "personalreferent"],
    ["recruiter", "işe alım uzmanı", "recruiter", "recruitment specialist", "talent acquisition specialist"],
    ["marketing_specialist", "pazarlama uzmanı", "marketing specialist", "marketingspezialist"],
    ["digital_marketing_specialist", "dijital pazarlama uzmanı", "digital marketing specialist", "online marketing specialist"],
    ["sales_representative", "satış temsilcisi", "sales representative", "sales rep", "vertriebsmitarbeiter", "représentant commercial"],
    ["customer_support", "müşteri destek uzmanı", "müşteri temsilcisi", "customer support specialist", "customer service representative", "kundenbetreuer"],
    ["logistics_specialist", "lojistik uzmanı", "logistics specialist", "logistikspezialist"],
    ["procurement_specialist", "satın alma uzmanı", "procurement specialist", "purchasing specialist", "einkäufer"],
    ["nurse", "hemşire", "nurse", "krankenpfleger", "krankenpflegerin", "infirmier", "infirmière", "enfermero", "enfermera"],
    ["pharmacist", "eczacı", "pharmacist", "apotheker", "pharmacien", "farmacéutico"],
    ["electrician", "elektrikçi", "electrician", "elektriker", "électricien", "electricista"],
    ["welder", "kaynakçı", "welder", "schweißer", "soudeur", "soldador"],
    ["warehouse_worker", "depo görevlisi", "depo elemanı", "warehouse worker", "warehouse operative", "lagermitarbeiter"],
    ["chef", "aşçı", "chef", "cook", "koch", "cuisinier", "cocinero"],
    ["intern_role", "stajyer", "staj", "stajı", "staj programı", "intern", "internship", "praktikant", "praktikum", "werkstudent", "working student", "trainee"],
    ["developer_general", "geliştirici", "geliştiricisi", "developer", "entwickler", "développeur", "desarrollador", "programcı", "programmer"],
    ["engineer_general", "mühendis", "mühendisi", "mühendisliği", "engineer", "ingenieur", "ingénieur", "ingeniero"],
    ["designer_general", "tasarımcı", "tasarımcısı", "tasarım", "designer", "concepteur", "diseñador"],
    ["manager_general", "yönetici", "yöneticisi", "müdür", "müdürü", "manager", "leiter"],
    ["specialist_general", "uzman", "uzmanı", "specialist", "spezialist"],
    ["analyst_general", "analist", "analisti", "analyst", "analyste"],
    ["it_specialist", "bilgi işlem", "it uzmanı", "it specialist", "it support", "it administrator", "teknik destek"],
    ["hardware_engineer", "donanım mühendisi", "donanım uzmanı", "donanım", "hardware engineer", "hardware designer", "hardwareentwickler"],
    ["system_engineer", "sistem mühendisi", "sistem mühendisliği", "system engineer", "systems engineer", "systemingenieur"],
    ["product_owner", "product owner", "ürün sahibi", "po"],
    ["scrum_master", "scrum master", "agile coach", "çevik koç"],
    ["remote_work", "uzaktan", "evden", "remote", "homeoffice", "telearbeit", "teletravail"]
]

# Çok dilli teknoloji / yetenek eşdeğerleri
JOB_SKILL_EQUIVALENTS = [
    ["python", "python", "py"],
    ["java", "java"],
    ["sql", "sql"],
    ["rust", "rust"],
    ["docker", "docker"],
    ["javascript", "javascript", "js"],
    ["typescript", "typescript", "ts"],
    ["nodejs", "node.js", "nodejs", "node"],
    ["reactjs", "react.js", "reactjs", "react"],
    ["vuejs", "vue.js", "vuejs", "vue"],
    ["nextjs", "next.js", "nextjs"],
    ["dotnet", ".net", "dotnet"],
    ["csharp", "c#", "c sharp"],
    ["cpp", "c++", "cplusplus"],
    ["golang", "golang", "go"],
    ["kubernetes", "kubernetes", "k8s"],
    ["postgresql", "postgresql", "postgres"],
    ["mssql", "microsoft sql server", "ms sql server", "sql server", "mssql"],
    ["aws", "amazon web services", "aws"],
    ["gcp", "google cloud platform", "google cloud", "gcp"],
    ["azure", "microsoft azure", "azure"],
    ["cicd", "ci/cd", "ci cd", "cicd"],
    ["machine_learning", "makine öğrenmesi", "machine learning", "maschinelles lernen", "apprentissage automatique"],
    ["artificial_intelligence", "yapay zeka", "artificial intelligence", "künstliche intelligenz", "intelligence artificielle"],
    ["deep_learning", "derin öğrenme", "deep learning"],
    ["nlp", "doğal dil işleme", "natural language processing", "nlp"],
    ["computer_vision", "bilgisayarlı görü", "computer vision"],
    ["powerbi", "power bi", "powerbi"],
    ["excel", "microsoft excel", "ms excel", "excel"]
]


def search_fold(text: str) -> str:
    """Türkçe ve uluslararası karakterleri arama için katlar/küçültür."""
    if not text:
        return ""
    text = str(text).replace("İ", "i").replace("I", "ı").lower()
    mapping = {
        "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
        "ä": "a", "é": "e", "è": "e", "ê": "e", "ë": "e", "à": "a", "â": "a",
        "î": "i", "ï": "i", "ô": "o", "û": "u", "ù": "u", "ß": "ss",
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    text = re.sub(r"[^\w\s+#.-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def folded_column(col):
    """SQLAlchemy sütununu Türkçe karakterlerden arındırıp küçültür."""
    for a, b in (("İ", "i"), ("ı", "i"), ("Ş", "s"), ("ş", "s"), ("Ğ", "g"), ("ğ", "g"),
                 ("Ü", "u"), ("ü", "u"), ("Ö", "o"), ("ö", "o"), ("Ç", "c"), ("ç", "c")):
        col = func.replace(col, a, b)
    return func.lower(col)


def translate_query(text: str, target: str = "en", timeout: float = 2.5) -> str:
    """Metni hızlı ve ücretsiz Google Translate servisi üzerinden hedef dile çevirir."""
    text = (text or "").strip()
    if not text or len(text) > 400:
        return text
    key = (target, hashlib.sha256(text.encode("utf-8")).hexdigest())
    with _CACHE_LOCK:
        if key in _TRANSLATE_CACHE:
            _TRANSLATE_CACHE.move_to_end(key)
            return _TRANSLATE_CACHE[key]
    url = _TRANSLATE_URL.format(target=urllib.parse.quote(target), text=urllib.parse.quote(text))
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read(50000).decode("utf-8"))
        if isinstance(data, list) and data and isinstance(data[0], list):
            res = "".join(seg[0] for seg in data[0] if seg and isinstance(seg[0], str)).strip()
            if res:
                with _CACHE_LOCK:
                    _TRANSLATE_CACHE[key] = res
                    while len(_TRANSLATE_CACHE) > _MAX_CACHE:
                        _TRANSLATE_CACHE.popitem(last=False)
                return res
    except Exception as e:
        log.debug("Arama çevirisi zaman aşımı veya hata: %s", e)
    return text


def expand_search_terms(search_query: str, country: str = None) -> list[str]:
    """Arama sorgusunu eşanlamlılar, rol eşdeğerleri ve yabancı dil çevirileriyle genişletir."""
    raw = (search_query or "").strip()
    if not raw:
        return []

    terms = OrderedDict()
    terms[raw] = True

    folded_query = search_fold(raw)
    terms[folded_query] = True

    # 1. Öncelikle spesifik (özel) meslek rollerinde ara
    matched_specific_role = False
    for entry in JOB_ROLE_EQUIVALENTS:
        role_id = entry[0]
        if role_id in GENERAL_ROLES:
            continue
        aliases = entry[1:]
        folded_aliases = [search_fold(a) for a in aliases]
        for a, fa in zip(aliases, folded_aliases):
            if fa == folded_query or (len(fa) >= 5 and fa in folded_query) or (len(folded_query) >= 5 and folded_query in fa):
                matched_specific_role = True
                for alias in aliases:
                    terms[alias] = True
                break

    # 2. Eğer spesifik bir rol bulunamadıysa, genel unvanları kontrol et (tam eşleşme gerekir)
    if not matched_specific_role:
        for entry in JOB_ROLE_EQUIVALENTS:
            role_id = entry[0]
            if role_id not in GENERAL_ROLES:
                continue
            aliases = entry[1:]
            folded_aliases = [search_fold(a) for a in aliases]
            if folded_query in folded_aliases:
                for alias in aliases:
                    terms[alias] = True
                break

    # 3. Yetenek eşdeğerlerinde ara
    for entry in JOB_SKILL_EQUIVALENTS:
        aliases = entry[1:]
        folded_aliases = [search_fold(a) for a in aliases]
        for a, fa in zip(aliases, folded_aliases):
            if fa == folded_query:
                for alias in aliases:
                    terms[alias] = True
                break

    # 4. Türkçe karakter varsa veya eşleşme az ise İngilizceye çevir
    has_tr_chars = bool(re.search(r"[çğıöşüÇĞİÖŞÜ]", raw))
    if has_tr_chars or not matched_specific_role:
        en_trans = translate_query(raw, target="en")
        if en_trans and en_trans.casefold() != raw.casefold():
            terms[en_trans] = True
            folded_en = search_fold(en_trans)
            # Çevrilen İngilizce terim rol listesinde var mı?
            for entry in JOB_ROLE_EQUIVALENTS:
                if entry[0] in GENERAL_ROLES:
                    continue
                aliases = entry[1:]
                folded_aliases = [search_fold(a) for a in aliases]
                if any(fa == folded_en or (len(fa) >= 5 and fa in folded_en) for fa in folded_aliases):
                    for alias in aliases:
                        terms[alias] = True
                    break

    # 5. Ülke filtresi varsa ilgili ülkenin diline de çevir (Almanya -> de, Fransa -> fr vb.)
    if country:
        c_low = country.lower()
        target_lang = None
        if any(w in c_low for w in ("almanya", "germany", "deutschland", "austria", "avusturya", "isviçre", "switzerland")):
            target_lang = "de"
        elif any(w in c_low for w in ("fransa", "france")):
            target_lang = "fr"
        elif any(w in c_low for w in ("ispanya", "spain", "espana")):
            target_lang = "es"
        elif any(w in c_low for w in ("hollanda", "netherlands", "nederland")):
            target_lang = "nl"
        elif any(w in c_low for w in ("italya", "italy", "italia")):
            target_lang = "it"

        if target_lang:
            loc_trans = translate_query(raw, target=target_lang)
            if loc_trans and loc_trans.casefold() != raw.casefold():
                terms[loc_trans] = True

    # Temizlenmiş ve katlanmış terim listesi
    result = []
    seen = set()
    for t in terms.keys():
        t_clean = t.strip()
        f = search_fold(t_clean)
        if f and f not in seen:
            seen.add(f)
            result.append(t_clean)
    return result


def build_search_filter(model_cls, search_text: str, country: str = None):
    """SQLAlchemy Job sorgusu için genişletilmiş arama filtre ifadesi oluşturur."""
    raw = (search_text or "").strip()
    if not raw:
        return None

    terms = expand_search_terms(raw, country=country)
    f_raw = search_fold(raw)

    or_conditions = []
    # 1. Ham sorgu şirket adı, başlık, açıklama ve etiketlerde aranır
    or_conditions.append(folded_column(model_cls.company).like(f"%{f_raw}%"))
    or_conditions.append(folded_column(model_cls.title).like(f"%{f_raw}%"))
    or_conditions.append(folded_column(model_cls.tags).like(f"%{f_raw}%"))
    or_conditions.append(folded_column(model_cls.description).like(f"%{f_raw}%"))

    # 2. Çok dilli eşdeğer terimler başlık ve etiketlerde aranır
    for term in terms:
        f_term = search_fold(term)
        if not f_term or f_term == f_raw:
            continue
        or_conditions.append(folded_column(model_cls.title).like(f"%{f_term}%"))
        or_conditions.append(folded_column(model_cls.tags).like(f"%{f_term}%"))

        # Çok kelimeli ise (örn. 'mechanical engineer'), kelimelerin tamamının başlıkta yer alması
        tokens = [tk for tk in f_term.split() if len(tk) >= 3]
        if len(tokens) > 1:
            or_conditions.append(and_(*[folded_column(model_cls.title).like(f"%{tk}%") for tk in tokens]))

    return or_(*or_conditions)


def apply_search_filter(query, model_cls, search_text: str, country: str = None):
    """Sorguya çok dilli arama filtresini uygular."""
    clause = build_search_filter(model_cls, search_text, country=country)
    if clause is not None:
        return query.filter(clause)
    return query
