"""Persistent city × profession routine searches and their default targets."""

import json
import time
from datetime import datetime
from flask import jsonify

from . import audit, config, runs
from .models import RoutineCitySchedule, SearchRun, SearchTask, Setting


# --- Şu an devre dışı şehirler (ileride tekrar aktif edilebilir) -----------
# ("Budapeşte", "Macaristan", "Budapest, Hungary", 50, False),
# ("Bükreş", "Romanya", "Bucharest, Romania", 50, False),
# ("Cambridge", "Birleşik Krallık", "Cambridge, England, United Kingdom", 50, False),
# ("Cenevre", "İsviçre", "Geneva, Switzerland", 50, False),
# ("Edinburg", "Birleşik Krallık", "Edinburgh, Scotland, United Kingdom", 50, False),
# ("Eindhoven", "Hollanda", "Eindhoven, Netherlands", 50, False),
# ("Göteborg", "İsveç", "Gothenburg, Sweden", 50, False),
# ("Köln", "Almanya", "Cologne, Germany", 50, False),
# ("Krakow", "Polonya", "Krakow, Poland", 50, False),
# ("Lozan", "İsviçre", "Lausanne, Switzerland", 50, False),
# ("Lyon", "Fransa", "Lyon, France", 50, False),
# ("Oxford", "Birleşik Krallık", "Oxford, England, United Kingdom", 50, False),
# ("Sofya", "Bulgaristan", "Sofia, Bulgaria", 50, False),
# ("Torino", "İtalya", "Turin, Italy", 50, False),
# --------------------------------------------------------------------------

_CITY_ROWS = (
    # Istanbul is deliberately first: it is the critical routine location.
    ("İstanbul", "Türkiye", "Istanbul, Turkey", 50, True),
    ("Amsterdam", "Hollanda", "Amsterdam, Netherlands", 50, False),
    ("Ankara", "Türkiye", "Ankara, Turkey", 50, False),
    ("Barcelona", "İspanya", "Barcelona, Spain", 50, False),
    ("Berlin", "Almanya", "Berlin, Germany", 50, False),
    ("Brüksel", "Belçika", "Brussels, Belgium", 50, False),
    ("Dublin", "İrlanda", "Dublin, Ireland", 50, False),
    ("Frankfurt", "Almanya", "Frankfurt, Germany", 50, False),
    ("Hamburg", "Almanya", "Hamburg, Germany", 50, False),
    ("Helsinki", "Finlandiya", "Helsinki, Finland", 50, False),
    ("İzmir", "Türkiye", "Izmir, Turkey", 50, False),
    ("Kopenhag", "Danimarka", "Copenhagen, Denmark", 50, False),
    ("Lizbon", "Portekiz", "Lisbon, Portugal", 50, False),
    ("Londra", "Birleşik Krallık", "London, United Kingdom", 50, False),
    ("Madrid", "İspanya", "Madrid, Spain", 50, False),
    ("Milano", "İtalya", "Milan, Italy", 50, False),
    ("Münih", "Almanya", "Munich, Germany", 50, False),
    ("Oslo", "Norveç", "Oslo, Norway", 50, False),
    ("Paris", "Fransa", "Paris, France", 50, False),
    ("Prag", "Çekya", "Prague, Czechia", 50, False),
    ("Roma", "İtalya", "Rome, Italy", 50, False),
    ("Stockholm", "İsveç", "Stockholm, Sweden", 50, False),
    ("Stuttgart", "Almanya", "Stuttgart, Germany", 50, False),
    ("Tallinn", "Estonya", "Tallinn, Estonia", 50, False),
    ("Utrecht", "Hollanda", "Utrecht, Netherlands", 50, False),
    ("Valensiya", "İspanya", "Valencia, Spain", 50, False),
    ("Varşova", "Polonya", "Warsaw, Poland", 50, False),
    ("Viyana", "Avusturya", "Vienna, Austria", 50, False),
    ("Wroclaw", "Polonya", "Wroclaw, Poland", 50, False),
    ("Zürih", "İsviçre", "Zurich, Switzerland", 50, False),
)

ROUTINE_PROFESSIONS = (
    "Yapay Zeka Mühendisliği",
    "Yazılım Mühendisliği",
    "Makine Mühendisliği",
    "Elektrik-Elektronik Mühendisliği",
    "Elektrik Güç ve Tesisat Mühendisliği",
    "Mekatronik Mühendisliği",
    "Veri Mühendisliği",
    "Endüstri Mühendisliği",
    "Havacılık ve Uzay Mühendisliği",
    "Robotik Mühendisliği",
    "Kalibrasyon Mühendisliği",
    "Sistem Mühendisliği",
)

ROUTINE_PROFESSION_KEYWORDS_INTL = {
    "Yapay Zeka Mühendisliği": "Artificial Intelligence Engineer",
    "Yazılım Mühendisliği": "Software Engineer",
    "Makine Mühendisliği": "Mechanical Engineer",
    "Elektrik-Elektronik Mühendisliği": "Electrical Engineer",
    "Elektrik Güç ve Tesisat Mühendisliği": "Power Systems Engineer",
    "Mekatronik Mühendisliği": "Mechatronics Engineer",
    "Veri Mühendisliği": "Data Engineer",
    "Endüstri Mühendisliği": "Industrial Engineer",
    "Havacılık ve Uzay Mühendisliği": "Aerospace Engineer",
    "Robotik Mühendisliği": "Robotics Engineer",
    "Kalibrasyon Mühendisliği": "Calibration Engineer",
    "Sistem Mühendisliği": "System Engineer",
}

ROUTINE_CITIES = tuple(
    {
        "order": index,
        "city": city,
        "country": country,
        "location": location,
        "quota": quota,
        "critical": critical,
    }
    for index, (city, country, location, quota, critical) in enumerate(_CITY_ROWS, start=1)
)

CITY_COUNT = len(ROUTINE_CITIES)
PROFESSION_COUNT = len(ROUTINE_PROFESSIONS)
PAUSE_KEY = "routine_cities_paused"
ROUTINE_INTERVAL_SECONDS = 86400


def is_paused(session):
    setting = session.get(Setting, PAUSE_KEY)
    return bool(setting and setting.value == "1")


def _ensure_schedules(session):
    rows = {row.city: row for row in session.query(RoutineCitySchedule).all()}
    changed = False
    for city in ROUTINE_CITIES:
        if city["city"] not in rows:
            row = RoutineCitySchedule(city=city["city"], next_due_at=0,
                                      interval_seconds=ROUTINE_INTERVAL_SECONDS)
            session.add(row)
            rows[row.city] = row
            changed = True
    if changed:
        session.flush()
    return rows


def _city_snapshot(session, city, row, now):
    last = session.get(SearchRun, row.last_run_id) if row.last_run_id else None
    last_info = None
    if last and not last.deleted_at:
        last_info = {
            "id": last.id,
            "status": last.status,
            "created_at": last.created_at.isoformat() if last.created_at else None,
            "new": json.loads(last.stats or "{}").get("new", 0),
        }
    return dict(city, enabled=True, interval_seconds=row.interval_seconds,
                next_due_at=row.next_due_at, last_run=last_info)


def dispatch(session, now, source):
    """Queue one due city batch; the shared supervisor runs its tasks serially."""
    if source.get("paused") or is_paused(session):
        return None
    rows = _ensure_schedules(session)
    # Initially all cities tie, so the critical city order keeps Istanbul first.
    # After that, oldest-due city wins so a long run cannot starve the rest.
    ordered_cities = sorted(
        ROUTINE_CITIES,
        key=lambda city: (rows[city["city"]].next_due_at, city["order"]),
    )
    for city in ordered_cities:
        row = rows[city["city"]]
        if row.next_due_at > now:
            continue
        previous = session.get(SearchRun, row.last_run_id) if row.last_run_id else None
        if previous and not previous.deleted_at and previous.status not in runs.TERMINAL:
            continue

        run_id = runs.identifier()
        options = dict(
            kind="scrape", queue_layer="routine", service_managed=True,
            routine_city=city["city"], routine_country=city.get("country", ""), routine_city_order=city["order"],
            classify_backend="groq" if config.GROQ_API_KEY else "rules",
            use_embeddings=False, mode="incremental", refresh_details=False,
            posted_within=7 * 86400, sort_recent=True, stop_when_known=True,
        )
        session.add(SearchRun(id=run_id, options=json.dumps(options, ensure_ascii=False)))
        is_turkey = city.get("country") == "Türkiye"
        for position, profession in enumerate(ROUTINE_PROFESSIONS):
            task_id = runs.identifier()
            keyword = profession if is_turkey else ROUTINE_PROFESSION_KEYWORDS_INTL.get(profession, profession)
            task = SearchTask(
                id=task_id, run_id=run_id, position=position,
                keyword=keyword, location=city["location"], limit=city["quota"],
                package=f"Rutin · {city['city']}", profession_group="Mühendislik",
                profession_code=f"routine-engineering-{position + 1}",
            )
            session.add(task)
            audit.record(session, run_id, task_id, "task_queued", {
                "keyword": keyword, "location": city["location"],
                "limit": city["quota"], "package": task.package,
                "city": city["city"], "country": city.get("country", ""),
            })
        row.last_run_id = run_id
        row.last_dispatched_at = now
        row.next_due_at = now + row.interval_seconds
        row.updated_at = datetime.utcnow()
        audit.record(session, run_id, None, "routine_city_run_created", {
            "city": city["city"], "country": city.get("country", ""), "location": city["location"],
            "order": city["order"], "critical": city["critical"],
            "profession_count": PROFESSION_COUNT, "quota": city["quota"],
            "next_due_at": row.next_due_at,
        })
        session.commit()
        return run_id
    return None


def install(server):
    @server.app.get("/api/routine-cities")
    def list_routine_cities():
        now = time.time()
        with runs.lock, server.SessionLocal() as session:
            rows = _ensure_schedules(session)
            session.commit()
            paused = is_paused(session)
            cities = [_city_snapshot(session, city, rows[city["city"]], now) for city in ROUTINE_CITIES]
            country_count = len({city["country"] for city in ROUTINE_CITIES if city.get("country")})
            return jsonify(cities=cities, total=len(cities), default_quota=50,
                           country_count=country_count,
                           professions=list(ROUTINE_PROFESSIONS), profession_count=PROFESSION_COUNT,
                           interval_seconds=ROUTINE_INTERVAL_SECONDS, paused=paused, now=now)

    @server.app.post("/api/routine-cities/<action>")
    def control_routine_cities(action):
        if action not in ("pause", "resume"):
            return jsonify(ok=False, error="Geçersiz rutin şehir işlemi."), 400
        with runs.lock, server.SessionLocal() as session:
            _ensure_schedules(session)
            session.merge(Setting(key=PAUSE_KEY, value="1" if action == "pause" else "0"))
            session.commit()
            return jsonify(ok=True, paused=action == "pause")
