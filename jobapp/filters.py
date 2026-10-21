"""Shared SQL filters used by listings, navigation, trash and contextual facets."""
import json
from datetime import timedelta
from sqlalchemy import and_, or_, func, exists, select
from .models import Job, TaskJob, SearchTask
from .db import parse_date

FIELDS = {name: getattr(Job, column) for name, column in {
    "opportunity_type": "opportunity_type",
    "category": "category", "seniority": "seniority", "workplace": "workplace_type",
    "profession_group": "profession_groups", "profession_subgroup": "profession_subgroups",
    "company": "company", "location": "location", "country": "location_country", "city": "location_city",
    "source": "source", "backend": "classified_by",
    "search_term": "search_term", "search_location": "search_location", "flag": "flag",
}.items()}


def folded(column):
    for a, b in (("İ", "i"), ("ı", "i"), ("Ş", "s"), ("ş", "s"), ("Ğ", "g"), ("ğ", "g"),
                 ("Ü", "u"), ("ü", "u"), ("Ö", "o"), ("ö", "o"), ("Ç", "c"), ("ç", "c")):
        column = func.replace(column, a, b)
    return func.lower(column)


def fold(value):
    return str(value).translate(str.maketrans("İıŞşĞğÜüÖöÇç", "iissgguuoocc")).lower()


def contains(column, value):
    value = fold(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return folded(column).like("%" + value + "%", escape="\\")


def values(args, key):
    return [v.strip() for v in args.getlist(key) if v.strip()]


def number(args, key, integer=False):
    value = args.get(key, "")
    if value == "":
        return None
    try:
        result = int(value) if integer else float(value)
        import math
        if result < 0 or not math.isfinite(result):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError(f"{key}: sıfır veya daha büyük geçerli bir sayı girin.")


def filtered(session, args, omit=None):
    q = session.query(Job)
    trash = args.get("visibility", "active")
    if trash not in ("active", "trash", "all"):
        raise ValueError("Geçersiz görünürlük seçimi.")
    if trash != "all":
        q = q.filter(Job.deleted_at.isnot(None) if trash == "trash" else Job.deleted_at.is_(None))
    quality = args.get("quality", "valid")
    if quality != "all":
        q = q.filter(Job.quality_ok.is_(quality != "invalid"))
    omitted = set(omit) if isinstance(omit, (list, tuple, set, frozenset)) else {omit}
    for key, col in FIELDS.items():
        if key in omitted:
            continue
        selected = values(args, key)
        if not selected:
            continue
        conditions = []
        for v in selected:
            if key in ("country", "city") and v == "Belirtilmemiş":
                conditions.append(or_(col == "", col.is_(None), col == "Belirtilmemiş"))
            elif v == "__missing__" or key == "flag" and v == "clean":
                conditions.append(or_(col == "", col.is_(None), col == "Unknown"))
            elif key in ("search_term", "search_location"):
                task_col = SearchTask.keyword if key == "search_term" else SearchTask.location
                conditions.append(exists(select(TaskJob.job_id).join(SearchTask, SearchTask.id == TaskJob.task_id)
                                         .where(TaskJob.job_id == Job.id, task_col == v)))
            elif key in ("profession_group", "profession_subgroup"):
                array = func.json_each(col).table_valued("value").alias("facet_" + key)
                conditions.append(exists(select(1).select_from(array).where(folded(array.c.value) == fold(v))))
            else:
                conditions.append(col == v)
        q = q.filter(or_(*conditions))
    columns = {"title": Job.title, "description": Job.description, "company_text": Job.company}
    for key, col in columns.items():
        if args.get(key, "").strip():
            q = q.filter(contains(col, args[key].strip()))
    if args.get("location_text", "").strip():
        loc_val = args["location_text"].strip()
        q = q.filter(or_(contains(Job.location, loc_val), contains(Job.search_location, loc_val)))
    text = args.get("search", "").strip()
    if text and args.get("semantic") not in ("1", "true"):
        q = q.filter(or_(*(contains(col, text) for col in (Job.title, Job.company, Job.description, Job.tags))))
    if args.get("phrase", "").strip():
        q = q.filter(or_(contains(Job.title, args["phrase"]), contains(Job.description, args["phrase"])))
    for term in args.get("exclude", "").split(","):
        if term.strip():
            q = q.filter(~or_(contains(Job.title, term.strip()), contains(Job.description, term.strip()), contains(Job.company, term.strip())))
    if omit != "skills":
        skill_conditions = []
        for i, skill in enumerate(values(args, "skills")):
            tags = func.json_each(Job.tags).table_valued("value").alias(f"skill_{i}")
            skill_conditions.append(exists(select(1).select_from(tags).where(folded(tags.c.value) == fold(skill))))
        if skill_conditions:
            q = q.filter((and_ if args.get("skill_mode") == "all" else or_)(*skill_conditions))
    for i, skill in enumerate(values(args, "exclude_skills")):
        tags = func.json_each(Job.tags).table_valued("value").alias(f"excluded_{i}")
        q = q.filter(~exists(select(1).select_from(tags).where(folded(tags.c.value) == fold(skill))))
    for key, column in (("experience", Job.experience_years), ("salary", None)):
        low, high = number(args, key + "_min"), number(args, key + "_max")
        if low is not None and high is not None and low > high:
            raise ValueError("Alt sınır üst sınırdan büyük olamaz.")
        if key == "salary":
            if (low is not None or high is not None or args.get("sort", "").startswith("salary_")) and not (args.get("currency") and args.get("period")):
                raise ValueError("Maaş karşılaştırması için para birimi ve dönem seçin.")
            if low is not None:
                q = q.filter(func.coalesce(Job.salary_max, Job.salary_min) >= low)
            if high is not None:
                q = q.filter(func.coalesce(Job.salary_min, Job.salary_max) <= high)
        else:
            if low is not None:
                q = q.filter(column >= low)
            if high is not None:
                q = q.filter(column <= high)
    if args.get("experience_missing") == "1":
        q = q.filter(Job.experience_years.is_(None))
    for key, col in (("currency", Job.salary_currency), ("period", Job.salary_period)):
        if args.get(key):
            q = q.filter(col == args[key])
    for key, col in (("has_salary", Job.salary), ("has_description", Job.description), ("has_summary", Job.summary)):
        if args.get(key) in ("1", "0"):
            condition = and_(col.isnot(None), col != "")
            q = q.filter(condition if args[key] == "1" else ~condition)
    if args.get("has_embedding") in ("1", "0"):
        q = q.filter(Job.embedding.isnot(None) if args["has_embedding"] == "1" else Job.embedding.is_(None))
    for key, col in (("posted", Job.posted_at), ("created", Job.created_at), ("scraped", Job.scraped_at)):
        low, high = args.get(key + "_from"), args.get(key + "_to")
        if low and high and low > high:
            raise ValueError("Başlangıç tarihi bitiş tarihinden sonra olamaz.")
        for raw, is_end in ((low, False), (high, True)):
            if raw:
                date = parse_date(raw)
                if date is None:
                    raise ValueError("Geçerli bir tarih seçin.")
                q = q.filter(col < date + timedelta(days=1) if is_end else col >= date)
        if args.get(key + "_missing") == "1":
            q = q.filter(col.is_(None))
    for key in ("run_id", "task_id"):
        selected = values(args, key)
        if selected:
            sub = select(TaskJob.job_id).join(SearchTask, SearchTask.id == TaskJob.task_id).where(TaskJob.job_id == Job.id)
            sub = sub.where((SearchTask.run_id if key == "run_id" else SearchTask.id).in_(selected))
            if args.get("discovery") == "new":
                sub = sub.where(TaskJob.is_new.is_(True))
            q = q.filter(exists(sub))
    return q


def ordered(q, args):
    sort = args.get("sort", "recent")
    orders = {"recent": (Job.scraped_at.desc(),), "posted": (Job.posted_at.is_(None), Job.posted_at.desc()),
              "posted_oldest": (Job.posted_at.is_(None), Job.posted_at.asc()),
              "created": (Job.created_at.is_(None), Job.created_at.desc()),
              "created_oldest": (Job.created_at.is_(None), Job.created_at.asc()), "title": (Job.title.asc(),),
              "salary_high": (Job.salary_max.is_(None), Job.salary_max.desc()),
              "salary_low": (Job.salary_min.is_(None), Job.salary_min.asc())}
    return q.order_by(*orders.get(sort, orders["recent"]), Job.id.desc())
