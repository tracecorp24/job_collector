"""Default cities and per-search targets for the routine search layer."""


_CITY_ROWS = (
    # Istanbul is deliberately first: it is the critical routine location.
    ("İstanbul", "Istanbul, Turkey", None, True),
    ("Aarhus", "Aarhus, Denmark", 50, False),
    ("Amsterdam", "Amsterdam, Netherlands", 50, False),
    ("Ankara", "Ankara, Turkey", 50, False),
    ("Anvers", "Antwerp, Belgium", 50, False),
    ("Atina", "Athens, Greece", 50, False),
    ("Barcelona", "Barcelona, Spain", 50, False),
    ("Berlin", "Berlin, Germany", 50, False),
    ("Brüksel", "Brussels, Belgium", 50, False),
    ("Budapeşte", "Budapest, Hungary", 50, False),
    ("Bükreş", "Bucharest, Romania", 50, False),
    ("Cambridge", "Cambridge, England, United Kingdom", 50, False),
    ("Cenevre", "Geneva, Switzerland", 50, False),
    ("Dublin", "Dublin, Ireland", 50, False),
    ("Edinburg", "Edinburgh, Scotland, United Kingdom", 50, False),
    ("Eindhoven", "Eindhoven, Netherlands", 50, False),
    ("Frankfurt", "Frankfurt, Germany", 50, False),
    ("Göteborg", "Gothenburg, Sweden", 50, False),
    ("Hamburg", "Hamburg, Germany", 50, False),
    ("Helsinki", "Helsinki, Finland", 50, False),
    ("İzmir", "Izmir, Turkey", 50, False),
    ("Kopenhag", "Copenhagen, Denmark", 50, False),
    ("Köln", "Cologne, Germany", 50, False),
    ("Krakow", "Krakow, Poland", 50, False),
    ("Lizbon", "Lisbon, Portugal", 50, False),
    ("Londra", "London, United Kingdom", 50, False),
    ("Lozan", "Lausanne, Switzerland", 50, False),
    ("Lyon", "Lyon, France", 50, False),
    ("Madrid", "Madrid, Spain", 50, False),
    ("Milano", "Milan, Italy", 50, False),
    ("Münih", "Munich, Germany", 50, False),
    ("Oslo", "Oslo, Norway", 50, False),
    ("Oxford", "Oxford, England, United Kingdom", 50, False),
    ("Paris", "Paris, France", 50, False),
    ("Prag", "Prague, Czechia", 50, False),
    ("Roma", "Rome, Italy", 50, False),
    ("Sofya", "Sofia, Bulgaria", 50, False),
    ("Stockholm", "Stockholm, Sweden", 50, False),
    ("Stuttgart", "Stuttgart, Germany", 50, False),
    ("Tallinn", "Tallinn, Estonia", 50, False),
    ("Torino", "Turin, Italy", 50, False),
    ("Utrecht", "Utrecht, Netherlands", 50, False),
    ("Valensiya", "Valencia, Spain", 50, False),
    ("Varşova", "Warsaw, Poland", 50, False),
    ("Viyana", "Vienna, Austria", 50, False),
    ("Wroclaw", "Wroclaw, Poland", 50, False),
    ("Zürih", "Zurich, Switzerland", 50, False),
)

ROUTINE_CITIES = tuple(
    {
        "order": index,
        "city": city,
        "location": location,
        "quota": quota,
        "critical": critical,
    }
    for index, (city, location, quota, critical) in enumerate(_CITY_ROWS, start=1)
)


def install(server):
    @server.app.get("/api/routine-cities")
    def list_routine_cities():
        return {
            "cities": list(ROUTINE_CITIES),
            "total": len(ROUTINE_CITIES),
            "default_quota": 50,
        }
