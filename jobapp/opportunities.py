"""Evidence-based opportunity classification, independent of seniority and AI backend.

Runs on the first card and again when original detail arrives. Search keywords are
deliberately excluded. Unknown requirements stay null, never negative or zero.
"""
import re
from datetime import date
from .classify.rules import _fold

VERSION = 1
INTERN = re.compile(r"\b(?:intern(?:s|ship)?|staj(?:yer\w*|i|lar\w*)?|praktikum)\b")
GRAD = re.compile(r"\b(?:yeni mezun|new grad\w*|graduate (?:program\w*|trainee)|management trainee|young talent|genc yetenek)\b")


def classify(title, description="", employment_type=""):
    t, d = _fold(title), _fold(description)
    evidence = []
    source_type = _fold(employment_type)
    # A mention in responsibilities (e.g. mentoring interns) is not an internship.
    explicit = re.search(r"\b(?:this (?:position|role) is (?:an? )?internship|bu (?:pozisyon|ilan) (?:bir )?staj|stajyer ar(?:aniyor|iyoruz))\b", d)
    organizer = re.search(r"\b(?:internship|staj)\s+(?:program\s+)?(?:manager|coordinator|koordinator\w*|yonetici\w*|sorumlusu)\b", t)
    title_intern = INTERN.search(t) and not organizer
    if source_type in ("internship", "intern", "staj") or title_intern or explicit:
        kind = "internship"
        evidence.append({"field": "employment_type" if source_type in ("internship", "intern", "staj") else "title" if title_intern else "description",
                         "text": employment_type if source_type in ("internship", "intern", "staj") else title if title_intern else explicit.group(0)})
    elif GRAD.search(t):
        kind = "graduate"
        evidence.append({"field": "title", "text": title})
    else:
        kind = "unknown" if not title or re.search(r"\b(?:trainee|bursiyer)\b", t) else "job"
    details = {"version": VERSION, "evidence": evidence, "period": None,
               "mandatory": None, "duration_weeks": None, "weekly_days": None,
               "paid": None, "deadline": None, "class_years": [], "departments": []}
    if kind != "internship":
        return {"opportunity_type": kind, "internship_details": details}
    text = t + "\n" + d
    def capture(key, pattern, value, source=None):
        match = re.search(pattern, text if source is None else source)
        if match:
            details[key] = value(match) if callable(value) else value
            evidence.append({"field": key, "text": match.group(0)})
    periods = [("summer", r"\b(?:summer internship|yaz (?:donemi )?staj\w*)\b"),
               ("semester", r"\b(?:donem ici|during (?:the )?semester)\b"),
               ("long_term", r"\b(?:uzun donem|long[ -]term)\b")]
    found_periods = [(value, pattern) for value, pattern in periods if re.search(pattern, text)]
    if len(found_periods) == 1:
        capture("period", found_periods[0][1], found_periods[0][0])
    # Negated/optional statements are not affirmative requirements.
    conditions = "\n".join(s for s in re.split(r"[.;\n]", text)
                           if not re.search(r"\b(?:degil|aranmiyor|aranmamaktadir|gerekmiyor|not required|not mandatory|optional)\b", s))
    mandatory = bool(re.search(r"\b(?:zorunlu staj|compulsory internship|mandatory internship)\b", conditions))
    voluntary = bool(re.search(r"\b(?:gonullu staj|voluntary internship)\b", conditions))
    if mandatory != voluntary:
        capture("mandatory", r"\b(?:zorunlu staj|compulsory internship|mandatory internship|gonullu staj|voluntary internship)\b", mandatory, conditions)
    duration = re.search(r"\b(?:(\d{1,2})\s*[-–]\s*)?(\d{1,2})\s*(?:hafta|weeks?)\b", text)
    if duration and 0 < int(duration[2]) <= 52 and (not duration[1] or int(duration[1]) <= int(duration[2])):
        details["duration_weeks"] = int(duration[2])
        details["duration_min_weeks"] = int(duration[1] or duration[2])
        evidence.append({"field": "duration_weeks", "text": duration[0]})
    capture("weekly_days", r"\bhaftada\s*(?:[1-7]\s*[-–]\s*)?(\d)\s*gun\b|\b(?:[1-7]\s*[-–]\s*)?(\d)\s*days? (?:a|per) week\b", lambda m: int(m[1] or m[2]) if 1 <= int(m[1] or m[2]) <= 7 else None)
    paid = bool(re.search(r"\b(?:paid internship|ucretli staj)\b", conditions))
    unpaid = bool(re.search(r"\b(?:unpaid internship|ucretsiz staj)\b", conditions))
    if paid != unpaid:
        capture("paid", r"\b(?:paid internship|ucretli staj|unpaid internship|ucretsiz staj)\b", paid, conditions)
    match = re.search(r"(?:son basvuru(?: tarihi)?|application deadline|apply by)\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4})", text)
    if match:
        try:
            raw_date = match[1]
            if not re.match(r"\d{4}-", raw_date):
                day, month, year = re.split(r"[./]", raw_date)
                raw_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
            details["deadline"] = date.fromisoformat(raw_date).isoformat()
            evidence.append({"field": "deadline", "text": match[0]})
        except ValueError:
            pass
    for match in re.finditer(r"\b([1-6])\.?\s*(?:(?:ve|veya|or|and|[-–])\s*([1-6])\.?\s*)?sinif\b|\b([1-6])(?:st|nd|rd|th)[ -]year\b", text):
        details["class_years"].extend(int(v) for v in match.groups() if v)
        evidence.append({"field": "class_years", "text": match[0]})
    details["class_years"] = sorted(set(details["class_years"]))
    department_names = [("Bilgisayar Mühendisliği", r"bilgisayar muhendis\w*|computer engineering"),
                        ("Yazılım Mühendisliği", r"yazilim muhendis\w*|software engineering"),
                        ("Makine Mühendisliği", r"makine muhendis\w*|mechanical engineering"),
                        ("Elektrik Mühendisliği", r"elektrik muhendis\w*|electrical engineering"),
                        ("Endüstri Mühendisliği", r"endustri muhendis\w*|industrial engineering"),
                        ("İşletme", r"isletme|business administration"),
                        ("Ekonomi", r"ekonomi|economics")]
    for sentence in re.split(r"[.;\n]", d):
        if not re.search(r"ogrenci\w*|bolum\w*|student\w*|studying|enrolled", sentence):
            continue
        for label, pattern in department_names:
            match = re.search(r"\b(?:"+pattern+r")\b", sentence)
            if match and label not in details["departments"]:
                details["departments"].append(label)
                evidence.append({"field": "departments", "text": match[0]})
    return {"opportunity_type": kind, "internship_details": details}


def refresh(job):
    """Refresh derived fields after description/title repair, before commit."""
    import json
    try:
        raw = json.loads(job.raw or "{}")
    except (TypeError, ValueError):
        raw = {}
    result = classify(job.title, job.description, raw.get("employment_type", "") if isinstance(raw, dict) else "")
    job.opportunity_type = result["opportunity_type"]
    job.internship_details = json.dumps(result["internship_details"], ensure_ascii=False)
