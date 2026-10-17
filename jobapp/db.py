"""Database engine, session factory and upsert helper."""

import json
import sqlite3
import shutil
import threading
import weakref
from contextlib import closing
from pathlib import Path
from datetime import datetime

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base, Job

# check_same_thread=False: the Flask SSE thread and the scrape worker thread
# both touch the DB. Each uses its own short-lived session.
engine = create_engine(
    config.DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False, "timeout": config.DB_BUSY_TIMEOUT_MS / 1000},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute(f"PRAGMA busy_timeout = {int(config.DB_BUSY_TIMEOUT_MS)}")
            cursor.execute("PRAGMA cache_size = -64000")
        finally:
            cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)

# init_db göçleri süreç başına, engine başına bir kez çalışır (testler engine'i değiştirir).
_initialized = weakref.WeakSet()
_init_lock = threading.RLock()


def once_per_engine(cache, bind, setup):
    """``setup(bind)``'i engine başına bir kez çalıştırır; başarısızsa tekrar denenir."""
    if bind in cache:
        return
    with _init_lock:
        if bind not in cache:
            setup(bind)
            cache.add(bind)


def init_db(force: bool = False) -> None:
    """Create tables if they don't exist, and add any new columns to old DBs.

    ``create_all`` only creates missing tables, not missing columns on tables
    that already exist — so columns added after a DB was first created (e.g.
    ``embedding``) need an explicit lightweight migration. Runs once per engine
    per process; ``force=True`` runs the migrations again.
    """
    if force:
        _initialized.discard(engine)
    once_per_engine(_initialized, engine, lambda _: _migrate())


def _migrate() -> None:
    _backup_before_upgrade()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode = WAL"))
        conn.execute(text("PRAGMA synchronous = NORMAL"))
        conn.execute(text(f"PRAGMA busy_timeout = {int(config.DB_BUSY_TIMEOUT_MS)}"))
        conn.execute(text("PRAGMA cache_size = -64000"))
        for table in ("search_runs", "search_tasks"):
            columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, kind in (("started_at", "DATETIME"), ("resumed_at", "DATETIME"), ("ended_at", "DATETIME"),
                               ("active_seconds", "FLOAT DEFAULT 0"), ("status_reason", "TEXT DEFAULT ''")):
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {kind}"))
            # Recover only recorded start times; never invent a start from queue creation.
            key = "run_id" if table == "search_runs" else "task_id"
            kind = "run_started" if table == "search_runs" else "task_start"
            conn.execute(text(f"UPDATE {table} SET started_at=(SELECT MIN(created_at) FROM search_events WHERE {key}={table}.id AND kind=:kind) WHERE started_at IS NULL AND status != 'queued'"), {"kind":kind})
            end_kind = "run_completed" if table == "search_runs" else "task_done"
            conn.execute(text(f"UPDATE {table} SET ended_at=(SELECT MAX(created_at) FROM search_events WHERE {key}={table}.id AND kind=:kind) WHERE ended_at IS NULL AND status IN ('finished','stopped')"), {"kind":end_kind})
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        for name, kind in (("posted_at", "DATETIME"), ("experience_years", "INTEGER"), ("deleted_at", "DATETIME"),
                           ("normalized_title", "VARCHAR(256) DEFAULT ''"),
                           ("profession_groups", "TEXT DEFAULT '[\"Genel Meslekler\"]'"),
                           ("profession_subgroups", "TEXT DEFAULT '[\"Diğer / Belirtilmemiş\"]'")):
            if name not in existing:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {kind}"))
        if "package" not in {row[1] for row in conn.execute(text("PRAGMA table_info(search_tasks)"))}:
            conn.execute(text("ALTER TABLE search_tasks ADD COLUMN package VARCHAR(160) DEFAULT ''"))
        task_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(task_jobs)"))}
        for name, kind in (("is_new", "BOOLEAN DEFAULT 0"), ("found_at", "DATETIME"), ("outcome", "VARCHAR(16) DEFAULT ''")):
            if name not in task_columns:
                conn.execute(text(f"ALTER TABLE task_jobs ADD COLUMN {name} {kind}"))
        if "embedding" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN embedding TEXT"))
        if "about_company" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN about_company TEXT DEFAULT ''"))
        if "offerings" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN offerings TEXT DEFAULT '[]'"))
        if "formatted_description" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN formatted_description TEXT DEFAULT ''"))
        if "salary" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN salary VARCHAR(128) DEFAULT ''"))
        if "salary_min" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN salary_min FLOAT"))
        if "salary_max" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN salary_max FLOAT"))
        if "salary_currency" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN salary_currency VARCHAR(8) DEFAULT ''"))
        if "salary_period" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN salary_period VARCHAR(16) DEFAULT ''"))
        if "flag" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN flag VARCHAR(16) DEFAULT ''"))
        if "flag_reason" not in existing:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN flag_reason TEXT DEFAULT ''"))
        for table, additions in (("app_logs", (("version", "VARCHAR(16) DEFAULT ''"),)),
                                 ("incidents", (("first_version", "VARCHAR(16) DEFAULT ''"), ("last_version", "VARCHAR(16) DEFAULT ''"),
                                               ("kind", "VARCHAR(16) DEFAULT 'error'"), ("fix_commit", "VARCHAR(40) DEFAULT ''"),
                                               ("fix_deployed_at", "DATETIME")))):
            present = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, kind in additions:
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {kind}"))
        task_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(search_tasks)"))}
        for name, kind in (("keyword_language", "VARCHAR(12) DEFAULT 'other'"),
                           ("profession_group", "VARCHAR(80) DEFAULT 'Genel Meslekler'"),
                           ("profession_code", "VARCHAR(80) DEFAULT 'other'"),
                           ("location_key", "VARCHAR(256) DEFAULT ''")):
            if name not in task_columns:
                conn.execute(text(f"ALTER TABLE search_tasks ADD COLUMN {name} {kind}"))
        # Profil özelliği kaldırıldı; eski profil metni ve uygunluk puanları canlı veride
        # silinmeden kalır (veri silen göç yazılmaz), uygulama bunları artık okumaz.

    _backfill_salary_numbers()
    _upgrade_history()
    from .service_api import init_journal
    init_journal()
    _repair_guest_card_fields()
    _repair_guest_noise_titles()
    _backfill_profession_taxonomy()


def _repair_guest_card_fields():
    """Eski ayrıştırıcı hesapsız kartlarda konumu tahminle arıyordu: tek kelimelik konumlar
    boş kaldı, adında "Türkiye" geçen şirketler konuma yazıldı. Ham kart satırlarından bir
    kez yeniden türetilir; ham veri değişmez."""
    from .models import Setting
    from . import parse
    marker = "repair_guest_card_fields_v1"
    with sessionmaker(bind=engine)() as session:
        if session.get(Setting, marker):
            return
        for job in session.query(Job).filter(Job.source == config.SOURCE_LINKEDIN):
            try:
                raw = json.loads(job.raw or "{}")
            except ValueError:
                continue
            if not isinstance(raw, dict) or not parse.is_guest_card(raw):
                continue
            parsed = parse.parse_guest_card(raw.get("card_lines"), "")
            if not parsed["quality_ok"]:
                continue
            if job.location != parsed["location"]:
                job.location = parsed["location"]
            if parsed["company"] and job.company != parsed["company"]:
                job.company = parsed["company"]
        session.add(Setting(key=marker, value=datetime.utcnow().isoformat()))
        session.commit()


def _repair_guest_noise_titles():
    """Hesapsız kart unvanı eskiden alt dizgi gürültü filtresinden geçiyordu; "Applied
    Scientist", "Incident Response Analyst" gibi gerçek ilanlar ``quality_ok=False`` kaldı.
    Ham kart satırlarından bir kez yeniden değerlendirilir; ağ isteği yok, veri silinmez."""
    from .models import Setting
    from . import parse
    marker = "repair_guest_noise_titles_v1"
    with sessionmaker(bind=engine)() as session:
        if session.get(Setting, marker):
            return
        for job in session.query(Job).filter(Job.source == config.SOURCE_LINKEDIN, Job.quality_ok.is_(False)):
            try:
                raw = json.loads(job.raw or "{}")
            except ValueError:
                continue
            if not isinstance(raw, dict) or not parse.is_guest_card(raw):
                continue
            parsed = parse.parse_guest_card(raw.get("card_lines"), "")
            if not parsed["quality_ok"]:
                continue
            job.quality_ok = True
            job.title = parsed["title"]
            if parsed["company"]:
                job.company = parsed["company"]
            if parsed["location"]:
                job.location = parsed["location"]
            if parsed["workplace_type"] and not job.workplace_type:
                job.workplace_type = parsed["workplace_type"]
        session.add(Setting(key=marker, value=datetime.utcnow().isoformat()))
        session.commit()


def _backfill_profession_taxonomy():
    """Tag existing listings and searches once, without using an API or rewriting source text."""
    from . import professions
    from .models import SearchTask, Setting

    marker = "profession_taxonomy_v1"
    with sessionmaker(bind=engine)() as session:
        if session.get(Setting, marker):
            return
        for job in session.query(Job).yield_per(300):
            role = professions.classify(job.title, job.description)
            job.normalized_title = role["normalized_title"]
            job.profession_groups = json.dumps(role["profession_groups"], ensure_ascii=False)
            job.profession_subgroups = json.dumps(role["profession_subgroups"], ensure_ascii=False)
            try:
                existing_tags = json.loads(job.tags or "[]")
            except (ValueError, TypeError):
                existing_tags = []
            job.tags = json.dumps(professions.normalize_skill_tags(existing_tags), ensure_ascii=False)
        for task in session.query(SearchTask).yield_per(300):
            metadata = professions.query_metadata(task.keyword, task.location)
            task.keyword_language = metadata["keyword_language"]
            task.profession_group = metadata["profession_group"]
            task.profession_code = metadata["profession_code"]
            task.location_key = metadata["location_key"]
        session.add(Setting(key=marker, value=datetime.utcnow().isoformat()))
        session.commit()


def _backup_before_upgrade():
    """SQLite online backup is safe even when a previous server has a connection."""
    path = engine.url.database
    if not path or path == ":memory:" or not Path(path).exists():
        return
    with closing(sqlite3.connect(path)) as source:
        columns = {r[1] for r in source.execute("PRAGMA table_info(jobs)")}
        if not columns or "deleted_at" in columns:
            return
        from . import config
        target = Path(path).parent / ("backup_before_ux_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        target.mkdir(exist_ok=True)
        with closing(sqlite3.connect(target / "jobs.db")) as backup:
            source.backup(backup)
        pool = Path(config.ACCOUNTLESS_OUTPUT_DIR)
        if pool.exists():
            shutil.copytree(pool, target / "accountless_searches", dirs_exist_ok=True)


def _upgrade_history():
    from .models import SearchRun, SearchTask, TaskJob, Setting
    from . import config, skills
    import hashlib
    with sessionmaker(bind=engine)() as session:
        if session.get(Setting, "ux_schema_v2"):
            return
        for job in session.query(Job).all():
            try:
                raw = json.loads(job.raw or "{}")
                job.posted_at = parse_date(raw.get("posted"))
            except (ValueError, TypeError):
                pass
            job.experience_years = skills.extract_experience_years(job.title + " " + job.description)
        root = Path(config.ACCOUNTLESS_OUTPUT_DIR)
        for meta_path in root.glob("*/search.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                existing_task = session.query(SearchTask).filter_by(folder=meta_path.parent.name).first()
                if existing_task and not existing_task.id.startswith("old-"):
                    continue
                ident = "old-" + hashlib.sha256(meta_path.parent.name.encode()).hexdigest()[:24]
                started = parse_date(meta.get("startedAt"))
                finished = parse_date(meta.get("finishedAt"))
                status = "paused" if meta.get("status") in ("running", "stopped", "error") else "finished"
                existing_run = session.get(SearchRun, ident)
                if not existing_run:
                    session.add(SearchRun(id=ident, status=status, created_at=started or datetime.utcnow()))
                elif existing_run.status == "finished" and status == "paused":
                    existing_run.status = "paused"
                session.merge(SearchTask(id=ident, run_id=ident, keyword=meta.get("title", ""), location=meta.get("location", ""),
                                       limit=meta.get("limit"), status=status, folder=meta_path.parent.name,
                                       checkpoint=json.dumps({"page": 0, "collected": meta.get("count", 0), "seen": [p.stem.removeprefix("ap-linkedin-") for p in (meta_path.parent / "ilan_havuzu").glob("*.json")]}),
                                       stats=json.dumps(meta.get("stats", {}))))
                for file in (meta_path.parent / "ilan_havuzu").glob("*.json"):
                    external_id = file.stem.removeprefix("ap-linkedin-")
                    job = session.query(Job).filter_by(source="linkedin", external_id=external_id).first()
                    if job:
                        session.merge(TaskJob(task_id=ident, job_id=job.id, is_new=bool(started and finished and started <= job.created_at <= finished), found_at=started or job.created_at))
                    try:
                        saved = json.loads(file.read_text(encoding="utf-8"))
                        saved.setdefault("_collector", {}).update(searchId=ident, runId=ident)
                        from .search_export import _write_json
                        _write_json(file, saved)
                    except (OSError, ValueError, TypeError, AttributeError):
                        continue
                from .search_export import _write_json
                meta.update(searchId=ident, runId=ident)
                _write_json(meta_path, meta)
            except (OSError, ValueError, TypeError):
                continue
        session.merge(Setting(key="ux_schema_v2", value="1"))
        session.commit()


def parse_date(value):
    if not value:
        return None
    try:
        from datetime import timezone
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return date.astimezone(timezone.utc).replace(tzinfo=None) if date.tzinfo else date
    except (TypeError, ValueError):
        return None


def _backfill_salary_numbers() -> None:
    """One-time normalization of ``salary`` text into numeric columns for rows
    that predate the salary_min/max columns (or were never parsed)."""
    from . import salary as salary_mod

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, salary FROM jobs WHERE salary != '' AND salary_min IS NULL"
        )).all()
        for row_id, raw in rows:
            parsed = salary_mod.parse_salary(raw)
            conn.execute(
                text(
                    "UPDATE jobs SET salary_min=:min, salary_max=:max, "
                    "salary_currency=:currency, salary_period=:period WHERE id=:id"
                ),
                {**parsed, "id": row_id},
            )


# Columns that upsert is allowed to refresh on an existing row.
_UPDATABLE = (
    "url",
    "title",
    "normalized_title",
    "profession_groups",
    "profession_subgroups",
    "company",
    "location",
    "workplace_type",
    "category",
    "seniority",
    "tags",
    "summary",
    "about_company",
    "offerings",
    "salary",
    "formatted_description",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "flag",
    "flag_reason",
    "classified_by",
    "description",
    "search_term",
    "search_location",
    "quality_ok",
    "raw",
    "scraped_at",
    "embedding",
    "posted_at",
    "experience_years",
)


def upsert_job(session, record: dict) -> tuple[Job, bool]:
    """Insert a job, or update the existing row with the same
    ``(source, external_id)``.

    ``record`` values may be Python objects; ``tags`` (list), ``raw`` (dict) and
    ``embedding`` (list of floats) are JSON-encoded here if needed. Returns
    ``(job, created)``.
    """
    record = dict(record)
    if isinstance(record.get("tags"), (list, tuple)):
        record["tags"] = json.dumps(list(record["tags"]), ensure_ascii=False)
    if isinstance(record.get("offerings"), (list, tuple)):
        record["offerings"] = json.dumps(list(record["offerings"]), ensure_ascii=False)
    for field in ("profession_groups", "profession_subgroups"):
        if isinstance(record.get(field), (list, tuple)):
            record[field] = json.dumps(list(record[field]), ensure_ascii=False)
    if isinstance(record.get("raw"), (dict, list)):
        record["raw"] = json.dumps(record["raw"], ensure_ascii=False)
    if isinstance(record.get("embedding"), (list, tuple)):
        record["embedding"] = json.dumps(list(record["embedding"]))
    record.setdefault("scraped_at", datetime.utcnow())

    source = record.get("source", config.SOURCE_LINKEDIN)
    external_id = record["external_id"]

    existing = (
        session.query(Job)
        .filter(Job.source == source, Job.external_id == external_id)
        .one_or_none()
    )

    if existing is None:
        job = Job(**{k: v for k, v in record.items() if hasattr(Job, k)})
        session.add(job)
        return job, True

    for key in _UPDATABLE:
        if key in record and record[key] is not None:
            setattr(existing, key, record[key])
    return existing, False
