"""Persistent cache and a SQLite coordinator shared by web and CLI processes."""
import hashlib
import json
import math
import random
import time
import uuid
import weakref
from contextlib import contextmanager
from datetime import timezone
from email.utils import parsedate_to_datetime
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.sqlite import insert

from . import config, db
from .models import DetailCache, SourcePolicy, Job


def retry_after_seconds(value, now=None):
    """RFC 9110 delay-seconds / HTTP-date. Invalid values return None."""
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    try:
        if value.isascii() and value.isdigit():
            seconds = float(int(value))
        else:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = max(0.0, date.timestamp() - (time.time() if now is None else now))
        return seconds if math.isfinite(seconds) else None
    except (ValueError, TypeError, OverflowError):
        return None


def fingerprint(raw):
    card = [str(v).strip() for v in raw.get("card_lines", [])]
    payload = json.dumps([card, raw.get("posted") or ""], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Tablo varlık kontrolü her örnekte değil, süreç içinde engine başına bir kez yapılır.
_policy_tables = weakref.WeakSet()
_cache_tables = weakref.WeakSet()


class SourcePaused(RuntimeError):
    def __init__(self, state):
        self.state = state
        super().__init__(state.get("message") or "Kaynak için tarama duraklatıldı.")


class Coordinator:
    def __init__(self, source="linkedin", interval=None, engine=None, clock=None, sleeper=None):
        self.source = source
        self.engine = engine or db.engine
        self.interval = max(config.MIN_REQUEST_INTERVAL, config.REQUEST_INTERVAL if interval is None else interval)
        self.clock = clock or time.time
        self.sleep = sleeper or time.sleep
        db.once_per_engine(_policy_tables, self.engine, lambda bind: SourcePolicy.__table__.create(bind, checkfirst=True))

    @contextmanager
    def transaction(self):
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                connection.execute(text("INSERT OR IGNORE INTO source_policy (source, next_request_at, lease_owner, lease_until, blocked_until, manual_pause, reason, violation_streak, last_violation_at, last_success_at, interval_floor) VALUES (:source,0,'',0,0,0,'',0,0,0,:floor)"), {"source":self.source,"floor":config.MIN_REQUEST_INTERVAL})
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def row(self, connection):
        return dict(connection.execute(text("SELECT * FROM source_policy WHERE source=:source"), {"source":self.source}).mappings().one())

    def state(self):
        # Salt okuma: yazma kilidi almaz. Satır yalnızca hiç yoksa (ilk çağrı) bir kez oluşturulur.
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT * FROM source_policy WHERE source=:source"), {"source":self.source}).mappings().first()
        if row:
            return self.describe(dict(row))
        with self.transaction() as connection:
            return self.describe(self.row(connection))

    def describe(self, row):
        now = self.clock()
        remaining = max(0.0, row["blocked_until"] - now)
        paused = remaining > 0
        message = row["reason"] if paused else "Kaynak erişime hazır."
        if paused and remaining > 0:
            message += f" En az {math.ceil(remaining)} saniye beklenmeli."
        if paused:
            message += " Süre dolunca sistem otomatik devam edecek."
        return {"source":self.source,"paused":paused,"manual_pause":False,"automatic_resume":True,
                "blocked_until":row["blocked_until"],"remaining_seconds":math.ceil(remaining),
                "reason":row["reason"],"message":message,"status_code":row["status_code"],
                "violation_streak":row["violation_streak"],"interval_floor":max(config.MIN_REQUEST_INTERVAL,row["interval_floor"]),
                "effective_interval":max(self.interval, config.MIN_REQUEST_INTERVAL, row["interval_floor"]),
                "interval_with_jitter_max":max(self.interval, config.MIN_REQUEST_INTERVAL, row["interval_floor"])*(1+config.REQUEST_JITTER),
                "next_request_at":row["next_request_at"],
                "acknowledge_allowed":False}

    def ensure_allowed(self):
        state = self.state()
        if state["paused"]:
            raise SourcePaused(state)
        return state

    def acquire(self, should_stop=lambda:False, emit=None):
        announced = False
        started = self.clock()
        while not should_stop():
            now = self.clock()
            with self.transaction() as connection:
                row = self.row(connection)
                state = self.describe(row)
                if state["paused"]:
                    raise SourcePaused(state)
                wait = max(0.0, row["next_request_at"] - now, row["lease_until"] - now if row["lease_owner"] else 0.0)
                if wait <= 0:
                    owner = uuid.uuid4().hex
                    interval = max(self.interval, config.MIN_REQUEST_INTERVAL, row["interval_floor"])
                    interval *= 1 + random.uniform(0, config.REQUEST_JITTER)
                    connection.execute(text("UPDATE source_policy SET lease_owner=:owner, lease_until=:lease, next_request_at=:next, interval_floor=:floor WHERE source=:source"),
                                       {"owner":owner,"lease":now+config.NETWORK_LEASE_SECONDS,"next":now+interval,"floor":max(config.MIN_REQUEST_INTERVAL,row["interval_floor"]),"source":self.source})
                    break
            if not announced and emit:
                emit("shared_rate_wait", {"source":self.source,"seconds":round(wait,3),
                     "effective_interval":state["effective_interval"], "reason":"Kaynağı koruyan ortak istek aralığı bekleniyor."})
                announced = True
            self.sleep(min(0.25, wait))
        else:
            owner = None
        if announced and emit:
            try:
                emit("shared_rate_wait_finished", {"seconds":round(max(0, self.clock()-started),3),
                                                  "outcome":"acquired" if owner else "cancelled"})
            except BaseException:
                if owner:
                    self.release(owner)
                raise
        return owner

    def release(self, owner):
        with self.transaction() as connection:
            connection.execute(text("UPDATE source_policy SET lease_owner='', lease_until=0 WHERE source=:source AND lease_owner=:owner"), {"source":self.source,"owner":owner})

    def success(self):
        with self.transaction() as connection:
            row = self.row(connection)
            # One successful request must not immediately undo throttling.
            stable = self.clock() - row["last_violation_at"] > config.ACCESS_FAILURE_WINDOW_SECONDS
            connection.execute(text("UPDATE source_policy SET last_success_at=:now, manual_pause=0, violation_streak=:streak, interval_floor=:floor WHERE source=:source"),
                {"source":self.source,"now":self.clock(), "streak":0 if stable else row["violation_streak"],
                 "floor":max(config.MIN_REQUEST_INTERVAL, row["interval_floor"]*.95) if stable else row["interval_floor"]})

    def pause(self, reason, status_code=None, retry_after=None, hard=False, violation=True, minimum=None):
        now = self.clock()
        requested = retry_after_seconds(retry_after, now)
        with self.transaction() as connection:
            row = self.row(connection)
            streak = row["violation_streak"]
            if violation:
                streak = streak + 1 if now-row["last_violation_at"] <= config.ACCESS_FAILURE_WINDOW_SECONDS else 1
            escalated = hard or streak >= config.ACCESS_FAILURE_THRESHOLD
            fallback = min(config.MAX_ACCESS_PAUSE_SECONDS,
                config.RETRY_BASE_COOLDOWN * 2 ** min(max(0, streak-1), 16))
            if escalated:
                fallback = max(fallback, config.ACCESS_PAUSE_SECONDS)
            delay = max(0.0, requested if requested is not None else fallback, minimum or 0.0)
            if escalated:
                delay = max(delay, fallback)
            deadline = max(row["blocked_until"], now+delay)
            floor = min(120.0, max(config.MIN_REQUEST_INTERVAL, row["interval_floor"]) * (1.5 if violation else 1))
            connection.execute(text("UPDATE source_policy SET blocked_until=:deadline, manual_pause=0, interval_floor=:floor, reason=:reason, status_code=:status, violation_streak=:streak, last_violation_at=:last WHERE source=:source"),
                               {"deadline":deadline,"floor":floor,"reason":reason,"status":status_code,"streak":streak,
                                "last":now if violation else row["last_violation_at"],"source":self.source})
            return self.describe(self.row(connection))

    def acknowledge(self):
        with self.transaction() as connection:
            row = self.row(connection)
            state = self.describe(row)
            if state["remaining_seconds"] > 0:
                raise SourcePaused(state)
            connection.execute(text("UPDATE source_policy SET manual_pause=0, blocked_until=0, reason='', status_code=NULL, violation_streak=0 WHERE source=:source"), {"source":self.source})
            return self.describe(self.row(connection))


class Details:
    def __init__(self, engine=None, clock=None):
        self.engine = engine or db.engine
        self.factory = sessionmaker(bind=self.engine)
        self.clock = clock or time.time
        db.once_per_engine(_cache_tables, self.engine, lambda bind: DetailCache.__table__.create(bind, checkfirst=True))

    def known(self, external_ids):
        """External ids already stored as jobs with a description."""
        if not external_ids:
            return set()
        with self.factory() as session:
            rows = session.query(Job.external_id).filter(Job.source == config.SOURCE_LINKEDIN,
                Job.external_id.in_(list(external_ids)), Job.description.isnot(None), Job.description != "").all()
            return {r[0] for r in rows}

    def get(self, raw, force=False, allow_stale=False):
        return self.get_many([raw], force=force,
                             allow_stale_ids={raw["external_id"]} if allow_stale else set()).get(raw["external_id"])

    def get_many(self, raws, force=False, allow_stale_ids=()):
        """Read a page's detail cache together; cache survives result deletion."""
        decisions = self.lookup_many(raws, force=force, allow_stale_ids=allow_stale_ids)
        return {key:result["value"] for key,result in decisions.items() if result["value"] is not None}

    def lookup(self, raw, force=False, allow_stale=False):
        return self.lookup_many([raw], force=force,
            allow_stale_ids={raw["external_id"]} if allow_stale else set())[raw["external_id"]]

    def lookup_many(self, raws, force=False, allow_stale_ids=()):
        """Explain per-card cache decisions using the existing batched read."""
        by_id = {raw["external_id"]: raw for raw in raws}
        if force:
            return {key:{"value":None,"reason":"forced_refresh"} for key in by_id}
        if not by_id:
            return {}
        allow_stale_ids = set(allow_stale_ids)
        with self.factory() as session:
            rows = session.query(DetailCache).filter(DetailCache.source == config.SOURCE_LINKEDIN,
                                                     DetailCache.external_id.in_(list(by_id))).all()
            cached_by_id = {row.external_id: row for row in rows}
            missing = set(by_id) - set(cached_by_id)
            if missing:
                jobs = session.query(Job).filter(Job.source == config.SOURCE_LINKEDIN,
                                                Job.external_id.in_(list(missing)), Job.description != "").all()
                for job in jobs:
                    try:
                        previous = json.loads(job.raw or "{}")
                        # A pending refresh may retain an older description next to
                        # a changed card. Never label it as fresh content.
                        if previous.get("detail_pending"):
                            continue
                        stamp = previous.get("detail_fetched_at")
                        if stamp is None and job.scraped_at:
                            stamp = job.scraped_at.replace(tzinfo=timezone.utc).timestamp()
                        if stamp is not None:
                            cached = DetailCache(source=config.SOURCE_LINKEDIN, external_id=job.external_id, fingerprint=fingerprint(previous),
                                                 description=job.description,status=200,fetched_at=stamp,expires_at=stamp+config.DETAIL_CACHE_TTL_SECONDS)
                            session.execute(insert(DetailCache).values(source=cached.source, external_id=cached.external_id,
                                fingerprint=cached.fingerprint, description=cached.description, status=cached.status,
                                fetched_at=cached.fetched_at, expires_at=cached.expires_at).on_conflict_do_nothing())
                            cached_by_id[job.external_id] = session.get(DetailCache, (cached.source, cached.external_id))
                    except (ValueError,TypeError):
                        continue
            now = self.clock()
            result = {}
            for external_id, raw in by_id.items():
                cached = cached_by_id.get(external_id)
                stale_allowed = external_id in allow_stale_ids and cached is not None and cached.status == 200
                reason = ("not_cached" if cached is None else "card_changed" if cached.fingerprint != fingerprint(raw)
                          else "expired" if cached.expires_at <= now and not stale_allowed else None)
                if reason:
                    result[external_id] = {"value":None,"reason":reason}
                else:
                    result[external_id] = {"reason":"known_stale" if cached.expires_at <= now else "fresh",
                        "value":{"description":cached.description,"status":cached.status,
                                 "fetched_at":cached.fetched_at,"expires_at":cached.expires_at}}
            session.commit()
            return result

    def previous(self, raw):
        """Keep an existing description visible while its refresh is queued."""
        with self.factory() as session:
            job = session.query(Job).filter_by(source=config.SOURCE_LINKEDIN, external_id=raw["external_id"]).first()
            if job and job.description:
                try:
                    stamp = json.loads(job.raw or "{}").get("detail_fetched_at")
                except (ValueError, TypeError):
                    stamp = None
                return {"description": job.description, "status": 200, "fetched_at": stamp}
        return None

    def put(self, raw, description, status=200):
        now = self.clock()
        ttl = config.DETAIL_CACHE_TTL_SECONDS if status == 200 else config.DETAIL_MISSING_TTL_SECONDS
        with self.factory() as session:
            values = dict(source=config.SOURCE_LINKEDIN,external_id=raw["external_id"],fingerprint=fingerprint(raw),
                          description=description or "",status=status,fetched_at=now,expires_at=now+ttl)
            statement = insert(DetailCache).values(**values)
            session.execute(statement.on_conflict_do_update(index_elements=["source", "external_id"],
                set_={k:v for k,v in values.items() if k not in ("source", "external_id")}))
            session.commit()
        return {"description":description,"status":status,"fetched_at":now,"expires_at":now+ttl}
