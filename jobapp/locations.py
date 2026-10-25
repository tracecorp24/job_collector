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

_TURKISH_PROVINCES = ('Adana Adıyaman Afyonkarahisar Ağrı Amasya Ankara Antalya Artvin Aydın Balıkesir '
    'Bilecik Bingöl Bitlis Bolu Burdur Bursa Çanakkale Çankırı Çorum Denizli Diyarbakır Edirne Elazığ '
    'Erzincan Erzurum Eskişehir Gaziantep Giresun Gümüşhane Hakkari Hatay Isparta Mersin İstanbul İzmir '
    'Kars Kastamonu Kayseri Kırklareli Kırşehir Kocaeli Konya Kütahya Malatya Manisa Kahramanmaraş '
    'Mardin Muğla Muş Nevşehir Niğde Ordu Rize Sakarya Samsun Siirt Sinop Sivas Tekirdağ Tokat '
    'Trabzon Tunceli Şanlıurfa Uşak Van Yozgat Zonguldak Aksaray Bayburt Karaman Kırıkkale Batman '
    'Şırnak Bartın Ardahan Iğdır Yalova Karabük Kilis Osmaniye Düzce').split()
_TURKISH_LOCALITIES = {_key(city): city for city in _TURKISH_PROVINCES}
for _parent, _districts in (
    ('İstanbul', 'Ümraniye Kadıköy Şişli Beşiktaş Ataşehir Sarıyer Pendik Kartal Maltepe Üsküdar Tuzla Esenyurt Kağıthane Beykoz Bağcılar Başakşehir Beylikdüzü Zeytinburnu Fatih Bakırköy Eyüpsultan Sultangazi Sultanbeyli Sancaktepe Çekmeköy Büyükçekmece Küçükçekmece Silivri Çatalca Şile Arnavutköy Güngören Bayrampaşa Gaziosmanpaşa Esenler Avcılar Beyoğlu Bahçelievler Adalar Hadımköy Riva Kurtköy Göktürk Kilyos'),
    ('Ankara', 'Çankaya Sincan Yenimahalle Keçiören Mamak Etimesgut Gölbaşı Altındağ Polatlı Kahramankazan Pursaklar Şereflikoçhisar Beypazarı Çubuk Elmadağ Güdül Haymana Kalecik Kızılcahamam Nallıhan Akyurt Ayaş Bala'),
    ('İzmir', 'Bornova Konak Karşıyaka Bayraklı Buca Çiğli Gaziemir Torbalı Urla Çeşme Menemen Kemalpaşa Aliağa Karabağlar Balçova Bayındır Bergama Beydağ Dikili Foça Güzelbahçe Karaburun Kınık Kiraz Menderes Narlıdere Ödemiş Seferihisar Selçuk Tire'),
    ('Kocaeli', 'Gebze İzmit Darıca Çayırova Dilovası'),
    ('Bursa', 'Nilüfer Osmangazi Yıldırım'),
    ('Tekirdağ', 'Çerkezköy Çorlu'),
):
    _TURKISH_LOCALITIES.update({_key(district): _parent for district in _districts.split()})


def _turkish_city(parts):
    for part in parts:
        k = _key(part)
        if k in _TURKISH_LOCALITIES:
            return _TURKISH_LOCALITIES[k]
        k_clean = re.sub(r"^(?:greater|buyuk)\s+", "", k).strip()
        if k_clean in _TURKISH_LOCALITIES:
            return _TURKISH_LOCALITIES[k_clean]
    return ''


def normalize_country(value):
    """Return a canonical country for a known name or alias, else an empty string."""
    return _COUNTRY_BY_KEY.get(_key(value)) or ""


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
    ("Rotterdam", "Rotterdam"), ("Lahey", "The Hague", "Den Haag", "Lahey", "Hague"),
    ("Groningen", "Groningen"), ("Düsseldorf", "Düsseldorf", "Dusseldorf"),
    ("Dortmund", "Dortmund"), ("Essen", "Essen"), ("Leipzig", "Leipzig"),
    ("Dresden", "Dresden"), ("Hannover", "Hannover", "Hanover"),
    ("Nürnberg", "Nürnberg", "Nuremberg", "Nurnberg"), ("Bremen", "Bremen"),
    ("Bonn", "Bonn"), ("Mannheim", "Mannheim"), ("Karlsruhe", "Karlsruhe"),
    ("Manchester", "Manchester"), ("Birmingham", "Birmingham"), ("Leeds", "Leeds"),
    ("Glasgow", "Glasgow"), ("Bristol", "Bristol"), ("Sheffield", "Sheffield"),
    ("Liverpool", "Liverpool"), ("Belfast", "Belfast"),
    ("Marseille", "Marseille"), ("Toulouse", "Toulouse"), ("Nice", "Nice"),
    ("Nantes", "Nantes"), ("Strasbourg", "Strasbourg"), ("Bordeaux", "Bordeaux"),
    ("Lille", "Lille"), ("Sevilla", "Sevilla", "Seville"), ("Málaga", "Málaga", "Malaga"),
    ("Bilbao", "Bilbao"), ("Zaragoza", "Zaragoza"),
    ("Napoli", "Napoli", "Naples"), ("Floransa", "Floransa", "Florence", "Firenze"),
    ("Bologna", "Bologna"), ("Venedik", "Venedik", "Venice", "Venezia"), ("Verona", "Verona"),
    ("Porto", "Porto", "Oporto"), ("Braga", "Braga"),
    ("Basel", "Basel", "Bâle"), ("Bern", "Bern", "Berne"),
    ("Graz", "Graz"), ("Linz", "Linz"), ("Salzburg", "Salzburg"),
    ("Gent", "Gent", "Ghent", "Gand"), ("Brugge", "Brugge", "Bruges"), ("Leuven", "Leuven"),
    ("Gdansk", "Gdansk", "Gdańsk"), ("Poznan", "Poznan", "Poznań"), ("Katowice", "Katowice"),
    ("Malmö", "Malmö", "Malmo"), ("Uppsala", "Uppsala"),
    ("Espoo", "Espoo"), ("Tampere", "Tampere"),
    ("Bergen", "Bergen"), ("Trondheim", "Trondheim"),
    ("Odense", "Odense"), ("Aalborg", "Aalborg"),
    ("New York", "New York", "New York City"), ("San Francisco", "San Francisco", "San Francisco Bay Area"),
    ("Los Angeles", "Los Angeles"), ("Chicago", "Chicago"), ("Boston", "Boston"),
    ("Seattle", "Seattle"), ("Austin", "Austin"), ("Dallas", "Dallas"),
    ("Houston", "Houston"), ("Atlanta", "Atlanta"), ("Philadelphia", "Philadelphia"),
    ("Washington", "Washington", "Washington D.C.", "Washington DC"), ("Miami", "Miami"),
    ("Denver", "Denver"), ("Phoenix", "Phoenix"), ("San Diego", "San Diego"),
    ("Toronto", "Toronto"), ("Vancouver", "Vancouver"), ("Montreal", "Montreal", "Montréal"),
    ("Calgary", "Calgary"), ("Ottawa", "Ottawa"),
    ("Delhi", "Delhi", "New Delhi"), ("Bengaluru", "Bengaluru", "Bangalore"),
    ("Mumbai", "Mumbai", "Bombay"), ("Tokyo", "Tokyo"), ("Singapore", "Singapore"),
    ("Sydney", "Sydney"), ("Melbourne", "Melbourne"), ("Brisbane", "Brisbane"), ("Perth", "Perth"),
    ("Dubai", "Dubai"), ("Abu Dhabi", "Abu Dhabi"), ("Tel Aviv", "Tel Aviv"), ("Cairo", "Cairo"),
    ("Auckland", "Auckland"),
    ("Bursa", "Bursa"), ("Antalya", "Antalya"), ("Adana", "Adana"),
    ("Gaziantep", "Gaziantep"), ("Konya", "Konya"), ("Kocaeli", "Kocaeli"),
    ("Eskişehir", "Eskişehir", "Eskisehir"), ("Mersin", "Mersin"),
    ("Diyarbakır", "Diyarbakır", "Diyarbakir"), ("Kayseri", "Kayseri"),
    ("Samsun", "Samsun"), ("Denizli", "Denizli"), ("Şanlıurfa", "Şanlıurfa", "Sanliurfa"),
    ("Sakarya", "Sakarya", "Adapazarı", "Adapazari"), ("Malatya", "Malatya"),
    ("Kahramanmaraş", "Kahramanmaraş", "Kahramanmaras"), ("Erzurum", "Erzurum"),
    ("Van", "Van"), ("Batman", "Batman"), ("Elazığ", "Elazığ", "Elazig"),
    ("Sivas", "Sivas"), ("Manisa", "Manisa"), ("Balıkesir", "Balıkesir", "Balikesir"),
    ("Trabzon", "Trabzon"), ("Çanakkale", "Çanakkale", "Canakkale"),
    ("Kütahya", "Kütahya", "Kutahya"), ("Çorum", "Çorum", "Corum"),
    ("Isparta", "Isparta"), ("Afyonkarahisar", "Afyonkarahisar", "Afyon"),
    ("Tekirdağ", "Tekirdağ", "Tekirdag"), ("Edirne", "Edirne"),
    ("Muğla", "Muğla", "Mugla", "Bodrum", "Fethiye", "Marmaris"),
    ("Aydın", "Aydın", "Aydin", "Kuşadası", "Kusadasi"),
    ("Yalova", "Yalova"), ("Zonguldak", "Zonguldak"), ("Düzce", "Düzce", "Duzce"),
    ("Bolu", "Bolu"), ("Rize", "Rize"), ("Ordu", "Ordu"), ("Giresun", "Giresun"),
)

_CITY_BY_KEY = {_key(alias): city for city, *aliases in _CITY_ROWS for alias in (city, *aliases)}
_CITY_COUNTRY = {
    "Amsterdam": "Hollanda", "Rotterdam": "Hollanda", "Lahey": "Hollanda", "Utrecht": "Hollanda",
    "Eindhoven": "Hollanda", "Groningen": "Hollanda",
    "Anvers": "Belçika", "Brüksel": "Belçika", "Gent": "Belçika", "Brugge": "Belçika", "Leuven": "Belçika",
    "Atina": "Yunanistan", "Barcelona": "İspanya", "Madrid": "İspanya", "Valensiya": "İspanya",
    "Sevilla": "İspanya", "Málaga": "İspanya", "Bilbao": "İspanya", "Zaragoza": "İspanya",
    "Berlin": "Almanya", "Frankfurt": "Almanya", "Hamburg": "Almanya", "Köln": "Almanya",
    "Münih": "Almanya", "Stuttgart": "Almanya", "Düsseldorf": "Almanya", "Dortmund": "Almanya",
    "Essen": "Almanya", "Leipzig": "Almanya", "Dresden": "Almanya", "Hannover": "Almanya",
    "Nürnberg": "Almanya", "Bremen": "Almanya", "Bonn": "Almanya", "Mannheim": "Almanya", "Karlsruhe": "Almanya",
    "Budapeşte": "Macaristan", "Bükreş": "Romanya",
    "Cambridge": "Birleşik Krallık", "Edinburg": "Birleşik Krallık", "Londra": "Birleşik Krallık",
    "Oxford": "Birleşik Krallık", "Manchester": "Birleşik Krallık", "Birmingham": "Birleşik Krallık",
    "Leeds": "Birleşik Krallık", "Glasgow": "Birleşik Krallık", "Bristol": "Birleşik Krallık",
    "Sheffield": "Birleşik Krallık", "Liverpool": "Birleşik Krallık", "Belfast": "Birleşik Krallık",
    "Cenevre": "İsviçre", "Lozan": "İsviçre", "Zürih": "İsviçre", "Basel": "İsviçre", "Bern": "İsviçre",
    "Dublin": "İrlanda", "Göteborg": "İsveç", "Stockholm": "İsveç", "Malmö": "İsveç", "Uppsala": "İsveç",
    "Helsinki": "Finlandiya", "Espoo": "Finlandiya", "Tampere": "Finlandiya",
    "İstanbul": "Türkiye", "İzmir": "Türkiye", "Ankara": "Türkiye", "Bursa": "Türkiye", "Antalya": "Türkiye",
    "Adana": "Türkiye", "Gaziantep": "Türkiye", "Konya": "Türkiye", "Kocaeli": "Türkiye",
    "Eskişehir": "Türkiye", "Mersin": "Türkiye", "Diyarbakır": "Türkiye", "Kayseri": "Türkiye",
    "Samsun": "Türkiye", "Denizli": "Türkiye", "Şanlıurfa": "Türkiye", "Sakarya": "Türkiye",
    "Malatya": "Türkiye", "Kahramanmaraş": "Türkiye", "Erzurum": "Türkiye", "Van": "Türkiye",
    "Batman": "Türkiye", "Elazığ": "Türkiye", "Sivas": "Türkiye", "Manisa": "Türkiye",
    "Balıkesir": "Türkiye", "Trabzon": "Türkiye", "Çanakkale": "Türkiye", "Kütahya": "Türkiye",
    "Çorum": "Türkiye", "Isparta": "Türkiye", "Afyonkarahisar": "Türkiye", "Tekirdağ": "Türkiye",
    "Edirne": "Türkiye", "Muğla": "Türkiye", "Aydın": "Türkiye", "Yalova": "Türkiye",
    "Zonguldak": "Türkiye", "Düzce": "Türkiye", "Bolu": "Türkiye", "Rize": "Türkiye",
    "Ordu": "Türkiye", "Giresun": "Türkiye",
    "Kopenhag": "Danimarka", "Aarhus": "Danimarka", "Odense": "Danimarka", "Aalborg": "Danimarka",
    "Krakow": "Polonya", "Varşova": "Polonya", "Wroclaw": "Polonya", "Gdansk": "Polonya", "Poznan": "Polonya", "Katowice": "Polonya",
    "Lizbon": "Portekiz", "Porto": "Portekiz", "Braga": "Portekiz",
    "Lyon": "Fransa", "Paris": "Fransa", "Marseille": "Fransa", "Toulouse": "Fransa", "Nice": "Fransa",
    "Nantes": "Fransa", "Strasbourg": "Fransa", "Bordeaux": "Fransa", "Lille": "Fransa",
    "Milano": "İtalya", "Roma": "İtalya", "Torino": "İtalya", "Napoli": "İtalya", "Floransa": "İtalya",
    "Bologna": "İtalya", "Venedik": "İtalya", "Verona": "İtalya",
    "Oslo": "Norveç", "Bergen": "Norveç", "Trondheim": "Norveç",
    "Prag": "Çekya", "Sofya": "Bulgaristan", "Tallinn": "Estonya",
    "Viyana": "Avusturya", "Graz": "Avusturya", "Linz": "Avusturya", "Salzburg": "Avusturya",
    "New York": "ABD", "San Francisco": "ABD", "Los Angeles": "ABD", "Chicago": "ABD", "Boston": "ABD",
    "Seattle": "ABD", "Austin": "ABD", "Dallas": "ABD", "Houston": "ABD", "Atlanta": "ABD",
    "Philadelphia": "ABD", "Washington": "ABD", "Miami": "ABD", "Denver": "ABD", "Phoenix": "ABD", "San Diego": "ABD",
    "Toronto": "Kanada", "Vancouver": "Kanada", "Montreal": "Kanada", "Calgary": "Kanada", "Ottawa": "Kanada",
    "Delhi": "Hindistan", "Bengaluru": "Hindistan", "Mumbai": "Hindistan", "Tokyo": "Japonya",
    "Singapore": "Singapur", "Sydney": "Avustralya", "Melbourne": "Avustralya", "Brisbane": "Avustralya", "Perth": "Avustralya",
    "Dubai": "Birleşik Arap Emirlikleri", "Abu Dhabi": "Birleşik Arap Emirlikleri", "Tel Aviv": "İsrail", "Cairo": "Mısır",
    "Auckland": "Yeni Zelanda",
}


def _city(value):
    """Return the canonical city for a known alias, otherwise clean the label."""
    value = str(value or "").strip()
    if _key(value) in _CITY_BY_KEY:
        return _CITY_BY_KEY[_key(value)]
    cleaned = re.sub(r"^(?:greater|büyük)\s+", "", value, flags=re.I).strip()
    if _key(cleaned) in _CITY_BY_KEY:
        return _CITY_BY_KEY[_key(cleaned)]
    cleaned = re.sub(r"\s+(?:metropolitan area|metro area|area|bölgesi|ili|merkez)$", "", cleaned, flags=re.I).strip()
    if _key(cleaned) in _CITY_BY_KEY:
        return _CITY_BY_KEY[_key(cleaned)]
    return _CITY_BY_KEY.get(_key(cleaned), cleaned or value)


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
        if country == 'Türkiye' and _turkish_city(before):
            return country, _turkish_city(before)
        city = next((_city(part) for part in before if _key(_city(part)) in _CITY_BY_KEY), None)
        if not city:
            city = _city(before[0]) if before else "Belirtilmemiş"
        return country, city or "Belirtilmemiş"

    if remote:
        return "Uzaktan", "Uzaktan"

    if _turkish_city(parts):
        return 'Türkiye', _turkish_city(parts)

    for part in parts:
        city = _city(part)
        inferred = _CITY_COUNTRY.get(city)
        if inferred:
            return inferred, city

    city = _city(parts[0]) if parts else raw
    return "Belirtilmemiş", city or "Belirtilmemiş"
