"""Normalize scraped location labels into a country and city for filtering.

Job boards return a mix of localized names, English names, and administrative
regions. This module keeps the original source label intact and stores a
predictable display value alongside it.
"""
import re
import unicodedata


def _key(value):
    value = str(value or "").strip().casefold().replace("ı", "i")
    value = unicodedata.normalize("NFKD", value)
    return "".join(char for char in value if not unicodedata.combining(char))


_COUNTRIES = (
    ("Türkiye", "turkey", "türkiye", "turkiye", "republic of turkey"),
    ("Hollanda", "netherlands", "the netherlands", "holland"),
    ("Belçika", "belgium", "belgië", "belgie"),
    ("Yunanistan", "greece", "hellas"),
    ("İspanya", "spain", "españa", "espana"),
    ("Almanya", "germany", "deutschland"),
    ("Macaristan", "hungary", "magyarország", "magyarorszag"),
    ("Romanya", "romania", "românia", "romania"),
    ("İsviçre", "switzerland", "schweiz", "suisse", "svizzera"),
    ("İrlanda", "ireland", "éire", "eire"),
    ("Birleşik Krallık", "united kingdom", "uk", "u.k.", "great britain", "britain", "gb", "england", "scotland", "wales", "northern ireland"),
    ("İsveç", "sweden", "sverige"),
    ("Finlandiya", "finland", "suomi"),
    ("Danimarka", "denmark", "danmark"),
    ("Polonya", "poland", "polska"),
    ("Portekiz", "portugal"),
    ("Fransa", "france", "république française", "republique francaise"),
    ("İtalya", "italy", "italia"),
    ("Norveç", "norway", "norge"),
    ("Çekya", "czechia", "czech republic", "česko", "cesko"),
    ("Bulgaristan", "bulgaria", "българия"),
    ("Estonya", "estonia", "eesti"),
    ("Avusturya", "austria", "österreich", "osterreich"),
    ("Ukrayna", "ukraine", "україна"),
    ("Rusya", "russia", "россия"),
    ("Hırvatistan", "croatia", "hrvatska"),
    ("Sırbistan", "serbia", "srbija"),
    ("Slovakya", "slovakia", "slovensko"),
    ("Slovenya", "slovenia", "slovenija"),
    ("Litvanya", "lithuania", "lietuva"),
    ("Letonya", "latvia", "latvija"),
    ("Lüksemburg", "luxembourg", "luxemburg"),
    ("İzlanda", "iceland", "ísland", "island"),
    ("Kıbrıs", "cyprus", "κύπρος"),
    ("Malta", "malta"),
    ("Bosna-Hersek", "bosnia and herzegovina", "bosnia", "босна и херцеговина"),
    ("Karadağ", "montenegro", "crna gora"),
    ("Kuzey Makedonya", "north macedonia", "macedonia", "северна македонија"),
    ("Arnavutluk", "albania", "shqipëria", "shqiperia"),
    ("Moldova", "moldova", "republic of moldova"),
    ("Belarus", "belarus", "беларусь"),
    ("Andorra", "andorra"),
    ("Monako", "monaco"),
    ("Lihtenştayn", "liechtenstein"),
    ("San Marino", "san marino"),
    ("Vatikan", "vatican city", "holy see"),
    ("ABD", "united states", "united states of america", "usa", "u.s.a.", "us", "u.s."),
    ("Kanada", "canada"),
    ("Hindistan", "india", "bharat"),
    ("Çin", "china", "中国"),
    ("Japonya", "japan", "日本"),
    ("Güney Kore", "south korea", "republic of korea", "대한민국"),
    ("Avustralya", "australia"),
    ("Singapur", "singapore"),
    ("Birleşik Arap Emirlikleri", "united arab emirates", "uae", "u.a.e."),
    ("Suudi Arabistan", "saudi arabia"),
    ("Brezilya", "brazil", "brasil"),
    ("Meksika", "mexico", "méxico"),
    ("Güney Afrika", "south africa"),
    ("İsrail", "israel"),
    ("Yeni Zelanda", "new zealand"),
    ("Hong Kong", "hong kong"),
    ("Tayvan", "taiwan"),
    ("Endonezya", "indonesia"),
    ("Pakistan", "pakistan"),
    ("Bangladeş", "bangladesh"),
    ("Filipinler", "philippines"),
    ("Tayland", "thailand"),
    ("Vietnam", "vietnam"),
    ("Malezya", "malaysia"),
    ("Katar", "qatar"),
    ("Mısır", "egypt"),
    ("Fas", "morocco"),
    ("Nijerya", "nigeria"),
    ("Kenya", "kenya"),
)

_COUNTRY_BY_KEY = {_key(alias): country for country, *aliases in _COUNTRIES for alias in (country, *aliases)}


_CITY_ROWS = (
    ("Aarhus", "Aarhus", "Århus"), ("Amsterdam", "Amsterdam"), ("Ankara", "Ankara"),
    ("Anvers", "Antwerp", "Antwerpen", "Anvers"), ("Atina", "Athens", "Athina", "Atina"),
    ("Barcelona", "Barcelona"), ("Berlin", "Berlin"), ("Brüksel", "Brussels", "Bruxelles", "Brüksel"),
    ("Budapeşte", "Budapest", "Budapeşte"), ("Bükreş", "Bucharest", "București", "Bükreş"),
    ("Cambridge", "Cambridge"), ("Cenevre", "Geneva", "Genève", "Cenevre"), ("Dublin", "Dublin"),
    ("Edinburg", "Edinburgh", "Edinburg"), ("Eindhoven", "Eindhoven"), ("Frankfurt", "Frankfurt", "Frankfurt am Main"),
    ("Göteborg", "Gothenburg", "Göteborg"), ("Hamburg", "Hamburg"), ("Helsinki", "Helsinki"),
    ("İstanbul", "Istanbul", "İstanbul", "Constantinople"), ("İzmir", "Izmir", "İzmir", "Smyrna"),
    ("Kopenhag", "Copenhagen", "København", "Kopenhag"), ("Köln", "Cologne", "Köln", "Koeln"),
    ("Krakow", "Krakow", "Kraków"), ("Lizbon", "Lisbon", "Lisboa", "Lizbon"),
    ("Londra", "London", "Londra"), ("Lozan", "Lausanne", "Lozan"), ("Lyon", "Lyon"),
    ("Madrid", "Madrid"), ("Milano", "Milan", "Milano"), ("Münih", "Munich", "München", "Münih"),
    ("Oslo", "Oslo"), ("Oxford", "Oxford"), ("Paris", "Paris"), ("Prag", "Prague", "Praha", "Prag"),
    ("Roma", "Rome", "Roma"), ("Sofya", "Sofia", "Sofya"), ("Stockholm", "Stockholm"),
    ("Stuttgart", "Stuttgart"), ("Tallinn", "Tallinn"), ("Torino", "Turin", "Torino"),
    ("Utrecht", "Utrecht"), ("Valensiya", "Valencia", "València", "Valensiya"),
    ("Varşova", "Warsaw", "Warszawa", "Varşova"), ("Viyana", "Vienna", "Wien", "Viyana"),
    ("Wroclaw", "Wroclaw", "Wrocław"), ("Zürih", "Zurich", "Zürich", "Zürih"),
    ("New York", "New York", "New York City"), ("San Francisco", "San Francisco", "San Francisco Bay Area"),
    ("Los Angeles", "Los Angeles"), ("Chicago", "Chicago"), ("Boston", "Boston"),
    ("Seattle", "Seattle"), ("Austin", "Austin"), ("Toronto", "Toronto"),
    ("Vancouver", "Vancouver"), ("Montreal", "Montreal", "Montréal"),
    ("Delhi", "Delhi", "New Delhi"), ("Bengaluru", "Bengaluru", "Bangalore"),
    ("Mumbai", "Mumbai", "Bombay"), ("Tokyo", "Tokyo"), ("Singapore", "Singapore"),
    ("Sydney", "Sydney"), ("Melbourne", "Melbourne"), ("Dubai", "Dubai"),
    ("Abu Dhabi", "Abu Dhabi"), ("Tel Aviv", "Tel Aviv"), ("Cairo", "Cairo"),
)

_CITY_BY_KEY = {_key(alias): city for city, *aliases in _CITY_ROWS for alias in (city, *aliases)}
_CITY_COUNTRY = {
    "Amsterdam": "Hollanda", "Anvers": "Belçika", "Atina": "Yunanistan", "Barcelona": "İspanya",
    "Berlin": "Almanya", "Brüksel": "Belçika", "Budapeşte": "Macaristan", "Bükreş": "Romanya",
    "Cambridge": "Birleşik Krallık", "Cenevre": "İsviçre", "Dublin": "İrlanda", "Edinburg": "Birleşik Krallık",
    "Eindhoven": "Hollanda", "Frankfurt": "Almanya", "Göteborg": "İsveç", "Hamburg": "Almanya",
    "Helsinki": "Finlandiya", "İstanbul": "Türkiye", "İzmir": "Türkiye", "Kopenhag": "Danimarka",
    "Köln": "Almanya", "Krakow": "Polonya", "Lizbon": "Portekiz", "Londra": "Birleşik Krallık",
    "Lozan": "İsviçre", "Lyon": "Fransa", "Madrid": "İspanya", "Milano": "İtalya", "Münih": "Almanya",
    "Oslo": "Norveç", "Oxford": "Birleşik Krallık", "Paris": "Fransa", "Prag": "Çekya", "Roma": "İtalya",
    "Sofya": "Bulgaristan", "Stockholm": "İsveç", "Stuttgart": "Almanya", "Tallinn": "Estonya",
    "Torino": "İtalya", "Utrecht": "Hollanda", "Valensiya": "İspanya", "Varşova": "Polonya",
    "Viyana": "Avusturya", "Wroclaw": "Polonya", "Zürih": "İsviçre", "Aarhus": "Danimarka",
    "New York": "ABD", "San Francisco": "ABD", "Los Angeles": "ABD", "Chicago": "ABD", "Boston": "ABD",
    "Seattle": "ABD", "Austin": "ABD", "Toronto": "Kanada", "Vancouver": "Kanada", "Montreal": "Kanada",
    "Delhi": "Hindistan", "Bengaluru": "Hindistan", "Mumbai": "Hindistan", "Tokyo": "Japonya",
    "Singapore": "Singapur", "Sydney": "Avustralya", "Melbourne": "Avustralya", "Dubai": "Birleşik Arap Emirlikleri",
    "Abu Dhabi": "Birleşik Arap Emirlikleri", "Tel Aviv": "İsrail", "Cairo": "Mısır",
}


def _city(value):
    """Return the canonical city for a known alias, otherwise clean the label."""
    value = str(value or "").strip()
    if _key(value) in _CITY_BY_KEY:
        return _CITY_BY_KEY[_key(value)]
    value = re.sub(r"\s+(?:metropolitan area|metro area|area)$", "", value, flags=re.I)
    return _CITY_BY_KEY.get(_key(value), value)


def normalize(value):
    """Return ``(country, city)`` without changing the source location string."""
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if not raw:
        return "Belirtilmemiş", "Belirtilmemiş"
    folded = _key(raw)
    if folded in ("worldwide", "global", "anywhere in the world"):
        return "Dünya geneli", "Dünya geneli"

    parts = [re.sub(r"\s+", " ", part).strip(" .") for part in re.split(r"[,|·]+", raw) if part.strip(" .")]
    remote = any(any(token in _key(part) for token in ("remote", "uzaktan", "anywhere")) for part in parts)
    country_index, country = None, None
    for index in range(len(parts) - 1, -1, -1):
        match = _COUNTRY_BY_KEY.get(_key(parts[index]))
        if match:
            country_index, country = index, match
            break

    if country_index is not None:
        if remote:
            return country, "Uzaktan"
        before = parts[:country_index]
        city = next((_city(part) for part in before if _key(_city(part)) in _CITY_BY_KEY), None)
        if not city:
            city = _city(before[0]) if before else "Belirtilmemiş"
        return country, city or "Belirtilmemiş"

    if remote:
        return "Uzaktan", "Uzaktan"

    for part in parts:
        city = _city(part)
        inferred = _CITY_COUNTRY.get(city)
        if inferred:
            return inferred, city

    city = _city(parts[0]) if parts else raw
    return "Belirtilmemiş", city or "Belirtilmemiş"
