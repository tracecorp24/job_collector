"""SQLAlchemy models."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Job(Base):
    """A single scraped, parsed and classified job posting.

    Deduplication is enforced across runs by the unique ``(source,
    external_id)`` constraint; the pipeline upserts (insert-or-update) on it.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_source_external"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Provenance / identity
    source = Column(String(32), nullable=False, default="linkedin", index=True)
    external_id = Column(String(64), nullable=False, index=True)
    url = Column(String(512), default="")

    # Parsed fields
    title = Column(String(512), default="", index=True)
    normalized_title = Column(String(256), default="", index=True)
    company = Column(String(256), default="", index=True)
    location = Column(String(256), default="")
    location_country = Column(String(128), default="", index=True)
    location_city = Column(String(128), default="", index=True)
    workplace_type = Column(String(32), default="", index=True)  # Remote/Hybrid/Onsite

    # Classified fields
    category = Column(String(48), default="Other", index=True)
    profession_groups = Column(Text, default='["Genel Meslekler"]')  # broad occupation roots, JSON array
    profession_subgroups = Column(Text, default='["Diğer / Belirtilmemiş"]')  # filterable occupation specialisms
    seniority = Column(String(32), default="Unknown", index=True)
    opportunity_type = Column(String(24), default="unknown", index=True)
    internship_details = Column(Text, default="{}")
    tags = Column(Text, default="[]")  # JSON array of strings
    summary = Column(Text, default="")  # optional one-liner (LLM)
    about_company = Column(Text, default="")  # optional company blurb (LLM)
    formatted_description = Column(Text, default="")  # optional LLM-rewritten description
    offerings = Column(Text, default="[]")  # optional JSON array of benefit strings (LLM)
    salary = Column(String(128), default="")  # optional pay range/figure as stated (LLM)
    salary_min = Column(Float, nullable=True)  # normalized numeric range, parsed from `salary`
    salary_max = Column(Float, nullable=True)
    salary_currency = Column(String(8), default="")  # e.g. USD, EUR, TRY
    salary_period = Column(String(16), default="")  # e.g. year, month, hour
    flag = Column(String(16), default="")  # "" | scam | ghost
    flag_reason = Column(Text, default="")  # short phrase explaining the flag
    classified_by = Column(String(16), default="rules")  # rules | llm | local
    embedding = Column(Text, nullable=True)  # optional JSON float array (local embeddings)

    # Content
    description = Column(Text, default="")

    # Search context that produced this row
    search_term = Column(String(128), default="")
    search_location = Column(String(128), default="")

    # Quality / debugging
    quality_ok = Column(Boolean, default=True, index=True)
    raw = Column(Text, default="{}")  # JSON of original scraped record

    # Timestamps
    scraped_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    posted_at = Column(DateTime, nullable=True, index=True)
    experience_years = Column(Integer, nullable=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

    def to_dict(self, include_description: bool = False, links=None) -> dict:
        import json

        try:
            tags = json.loads(self.tags or "[]")
        except (ValueError, TypeError):
            tags = []
        try:
            offerings = json.loads(self.offerings or "[]")
        except (ValueError, TypeError):
            offerings = []
        try:
            detail_pending = bool(json.loads(self.raw or "{}").get("detail_pending"))
        except (ValueError, TypeError, AttributeError):
            detail_pending = False
        data = {
            "detail_pending": detail_pending,
            "id": self.id,
            "source": self.source,
            "external_id": self.external_id,
            "url": self.url,
            "title": self.title,
            "normalized_title": self.normalized_title or self.title,
            "company": self.company,
            "location": self.location,
            "country": self.location_country,
            "city": self.location_city,
            "workplace_type": self.workplace_type,
            "category": self.category,
            "profession_groups": json.loads(self.profession_groups or '["Genel Meslekler"]'),
            "profession_subgroups": json.loads(self.profession_subgroups or '["Diğer / Belirtilmemiş"]'),
            "opportunity_type": self.opportunity_type or "unknown",
            "internship_details": json.loads(self.internship_details or "{}"),
            "seniority": self.seniority,
            "tags": tags,
            "summary": self.summary,
            "about_company": self.about_company,
            "offerings": offerings,
            "salary": self.salary,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "salary_period": self.salary_period,
            "flag": self.flag,
            "flag_reason": self.flag_reason,
            "classified_by": self.classified_by,
            "search_term": self.search_term,
            "search_location": self.search_location,
            "quality_ok": self.quality_ok,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "experience_years": self.experience_years,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }
        if include_description:
            data["description"] = self.description
            data["formatted_description"] = self.formatted_description
        from sqlalchemy.orm import object_session
        session = object_session(self)
        if links is None:
            links = session.query(TaskJob, SearchTask.run_id).join(SearchTask, TaskJob.task_id == SearchTask.id).filter(TaskJob.job_id == self.id).all() if session else []
        data["search_ids"] = [link.task_id for link, _ in links]
        data["run_ids"] = list(dict.fromkeys(run_id for _, run_id in links))
        data["discoveries"] = [{"search_id": link.task_id, "run_id": run_id, "is_new": link.is_new, "outcome":link.outcome,
                                 "found_at": link.found_at.isoformat() if link.found_at else None} for link, run_id in links]
        return data


class Setting(Base):
    """Small key/value store for application settings and generated reports."""

    __tablename__ = "settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")


class SearchRun(Base):
    __tablename__ = "search_runs"
    id = Column(String(40), primary_key=True)
    status = Column(String(24), default="queued", index=True)
    options = Column(Text, default="{}")
    stats = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    resumed_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    active_seconds = Column(Float, default=0)
    status_reason = Column(Text, default="")


class SearchTask(Base):
    __tablename__ = "search_tasks"
    id = Column(String(40), primary_key=True)
    run_id = Column(String(40), nullable=False, index=True)
    position = Column(Integer, default=0)
    keyword = Column(String(512), nullable=False)
    location = Column(String(512), default="")
    limit = Column(Integer, nullable=True)
    status = Column(String(24), default="queued")
    checkpoint = Column(Text, default="{}")
    folder = Column(Text, default="")
    stats = Column(Text, default="{}")
    error = Column(Text, default="")
    started_at = Column(DateTime, nullable=True)
    resumed_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    active_seconds = Column(Float, default=0)
    status_reason = Column(Text, default="")
    package = Column(String(160), default="")  # Aynı paketle eklenen görevlerin ortak adı
    keyword_language = Column(String(12), default="other", index=True)
    profession_group = Column(String(80), default="Genel Meslekler", index=True)
    profession_code = Column(String(80), default="other", index=True)
    location_key = Column(String(256), default="", index=True)


class TaskJob(Base):
    __tablename__ = "task_jobs"
    task_id = Column(String(40), primary_key=True)
    job_id = Column(Integer, primary_key=True, index=True)
    is_new = Column(Boolean, default=False)
    found_at = Column(DateTime, default=datetime.utcnow)
    outcome = Column(String(16), default="")


class SearchEvent(Base):
    __tablename__ = "search_events"
    id = Column(Integer, primary_key=True)
    run_id = Column(String(40), index=True)
    task_id = Column(String(40), index=True)
    kind = Column(String(32), index=True)
    level = Column(String(16), default="info")
    data = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class RepairTask(Base):
    """Durable completion task, including its stage, fields and retry deadline."""
    __tablename__ = "repair_tasks"
    source = Column(String(32), primary_key=True)
    external_id = Column(String(64), primary_key=True)
    raw = Column(Text, default="{}")
    stage = Column(String(16), default="detail", index=True)
    status = Column(String(16), default="pending", index=True)
    attempts = Column(Integer, default=0)
    next_attempt_at = Column(Float, default=0, index=True)
    last_error = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow)


class DetailCache(Base):
    __tablename__ = "detail_cache"
    source = Column(String(32), primary_key=True)
    external_id = Column(String(64), primary_key=True)
    fingerprint = Column(String(64), nullable=False)
    description = Column(Text, default="")
    status = Column(Integer, default=200)
    fetched_at = Column(Float, nullable=False)
    expires_at = Column(Float, nullable=False, index=True)


class SourcePolicy(Base):
    __tablename__ = "source_policy"
    source = Column(String(32), primary_key=True)
    next_request_at = Column(Float, default=0)
    lease_owner = Column(String(40), default="")
    lease_until = Column(Float, default=0)
    blocked_until = Column(Float, default=0)
    manual_pause = Column(Boolean, default=False)
    reason = Column(Text, default="")
    status_code = Column(Integer, nullable=True)
    violation_streak = Column(Integer, default=0)
    last_violation_at = Column(Float, default=0)
    last_success_at = Column(Float, default=0)
    interval_floor = Column(Float, default=0)


class Watch(Base):
    """A saved title × location combination the supervisor re-scans on its own."""
    __tablename__ = "watches"
    id = Column(String(40), primary_key=True)
    name = Column(String(200), default="")
    keywords = Column(Text, default="[]")
    locations = Column(Text, default="[]")
    interval_seconds = Column(Integer, default=21600)
    limit = Column(Integer, default=50)
    posted_within = Column(Integer, default=86400)
    enabled = Column(Boolean, default=True)
    next_due_at = Column(Float, default=0)
    last_run_id = Column(String(40), nullable=True)
    last_dispatched_at = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class RoutineCitySchedule(Base):
    """Persistent due time and last run for one configured city batch."""
    __tablename__ = "routine_city_schedules"
    city = Column(String(128), primary_key=True)
    next_due_at = Column(Float, default=0, index=True)
    interval_seconds = Column(Integer, default=86400)
    last_run_id = Column(String(40), nullable=True)
    last_dispatched_at = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class AppLog(Base):
    """Sunucu süreç logu (journald'daki satırların kalıcı, sorgulanabilir kopyası)."""
    __tablename__ = "app_logs"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String(16), index=True)
    logger = Column(String(80), default="")
    message = Column(Text, default="")
    traceback = Column(Text, default="")
    incident_id = Column(Integer, nullable=True, index=True)
    version = Column(String(16), default="")


class Incident(Base):
    """Aynı parmak izli hataların kalıcı kaydı; loglar budansa da silinmez."""
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True)
    fingerprint = Column(String(64), unique=True, index=True)
    level = Column(String(16), default="error")
    logger = Column(String(80), default="")
    title = Column(String(200), default="")
    sample = Column(Text, default="")
    traceback = Column(Text, default="")
    count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    status = Column(String(16), default="open", index=True)  # open | resolved
    issue_number = Column(Integer, nullable=True)
    issue_state = Column(String(16), default="")  # GitHub tarafının bildiği durum: "", open, closed
    resolved_at = Column(DateTime, nullable=True)
    resolution = Column(Text, default="")
    reopen_count = Column(Integer, default=0)
    history = Column(Text, default="[]")
    first_version = Column(String(16), default="")
    last_version = Column(String(16), default="")
    kind = Column(String(16), default="error")  # error | problem (eşik kuralı) | external (spool/uptime)
    fix_commit = Column(String(40), default="")
    fix_deployed_at = Column(DateTime, nullable=True)
