"""Database engine, session factory and upsert helper."""

import json
import sqlite3
import shutil
from contextlib import closing
from pathlib import Path
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base, Job

# check_same_thread=False: the Flask SSE thread and the scrape worker thread
# both touch the DB. Each uses its own short-lived session.
engine = create_engine(
    config.DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False, "timeout":30},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


def init_db() -> None:
    """Create tables if they don't exist, and add any new columns to old DBs.

    ``create_all`` only creates missing tables, not missing columns on tables
    that already exist — so columns added after a DB was first created (e.g.
    ``embedding``) need an explicit lightweight migration.
    """
    _backup_before_upgrade()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
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
                           ("fit_score", "INTEGER"), ("fit_reason", "TEXT DEFAULT ''"), ("fit_profile", "VARCHAR(16) DEFAULT ''")):
            if name not in existing:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {kind}"))
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

    _backfill_salary_numbers()
    _upgrade_history()
    from .service_api import init_journal
    init_journal()
    _repair_guest_card_fields()


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
