"""Shared constants for the LLM-backed classifiers (Claude and local/Ollama).

Kept in one place so the two backends can't drift out of sync on valid
category/seniority/workplace values or the instructions given to the model.
"""

VALID_CATEGORIES = [
    "Engineering", "Data", "Design", "Product", "Finance",
    "Sales", "Marketing", "HR", "Operations", "Other",
]
VALID_SENIORITY = ["Intern", "Junior", "Mid", "Senior", "Lead", "Manager"]
VALID_WORKPLACE = ["Remote", "Hybrid", "Onsite", ""]
VALID_FLAGS = ["", "scam", "ghost"]

INSTRUCTIONS = (
    "You classify job postings. The posting may be in Turkish or English. "
    "Respond with ONLY a compact JSON object, no prose, using exactly these keys:\n"
    '{"category": one of '
    + str(VALID_CATEGORIES)
    + ', "seniority": one of '
    + str(VALID_SENIORITY)
    + ', "workplace_type": one of ["Remote","Hybrid","Onsite",""], '
    '"tags": array of up to 8 lowercase skill/tool keywords, '
    '"summary": a single neutral sentence (max 25 words) describing the role, '
    '"about_company": 1-2 neutral sentences describing the company itself '
    '(industry, size, product) based only on what the posting says — empty '
    'string if the posting says nothing about the company, '
    '"offerings": array of up to 6 short phrases listing benefits/perks the '
    'posting offers (e.g. "health insurance", "remote work", "stock options", '
    '"flexible hours") — empty array if none are mentioned, '
    '"salary": the salary/pay range or figure exactly as stated in the posting '
    '(e.g. "$80k-100k", "25.000-30.000 TL"), or empty string if no compensation '
    'figure is mentioned, '
    '"formatted_description": a cleaned-up rewrite of the FULL job posting text '
    'preserving ALL factual content (do not summarize or omit details) and the '
    'ORIGINAL language of the posting (do not translate). Use blank lines between '
    'paragraphs. Use "## " at the start of a line for section headers ONLY when '
    'the posting has clear distinct sections (e.g. Responsibilities, Requirements, '
    'Benefits) — do not invent sections that are not present. Use "- " at the '
    'start of a line for bullet/list items. Do not use any other markdown '
    '(no bold, italics, links, tables, images, code blocks). This value must be '
    'valid inside a JSON string — escape every line break as \\n, do not emit '
    'literal newlines, '
    '"flag": "scam" if the posting looks like a scam (asks for payment/fees, '
    'vague "make $$$ from home", personal-data harvesting, MLM/pyramid, '
    'crypto-recruiter bait), "ghost" if it smells like a perpetual/evergreen '
    'staffing-agency listing with no real specific role ("always hiring", '
    'generic talent-pool posting), or "" if it looks like a normal genuine '
    'posting, '
    '"flag_reason": a phrase of 10 words or fewer explaining the flag, or '
    'empty string when "flag" is ""}.'
)


def extract_json(text: str) -> dict:
    import json
    import re

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


_MIN_LENGTH_RATIO = 0.5  # tunable: how short a rewrite can be vs the source before we distrust it


def apply_fields(base: dict, data: dict, classified_by: str, original_description: str = "") -> dict:
    """Merge a model's parsed JSON fields onto ``base``, validating each one."""
    if not data:
        return base
    result = dict(base)
    category = data.get("category")
    if category in VALID_CATEGORIES:
        result["category"] = category
    seniority = data.get("seniority")
    if seniority in VALID_SENIORITY:
        result["seniority"] = seniority
    workplace = data.get("workplace_type")
    if workplace in VALID_WORKPLACE and workplace:
        result["workplace_type"] = workplace
    tags = data.get("tags")
    if isinstance(tags, list):
        result["tags"] = [str(t).lower() for t in tags][:8]
    summary = data.get("summary")
    if isinstance(summary, str):
        result["summary"] = summary.strip()
    about_company = data.get("about_company")
    if isinstance(about_company, str):
        result["about_company"] = about_company.strip()
    offerings = data.get("offerings")
    if isinstance(offerings, list):
        result["offerings"] = [str(o).strip() for o in offerings if str(o).strip()][:6]
    salary = data.get("salary")
    if isinstance(salary, str):
        result["salary"] = salary.strip()
    formatted_description = data.get("formatted_description")
    if isinstance(formatted_description, str):
        fd = formatted_description.strip()
        orig_len = len((original_description or "").strip())
        # Guard against the model truncating/summarizing instead of just
        # reformatting: if the rewrite is suspiciously short relative to the
        # source, distrust it so the frontend falls back to the heuristic
        # formatter on the raw description instead of showing a gutted version.
        if fd and (orig_len == 0 or len(fd) >= orig_len * _MIN_LENGTH_RATIO):
            result["formatted_description"] = fd
    flag = data.get("flag")
    if flag in VALID_FLAGS:
        result["flag"] = flag
        result["flag_reason"] = str(data.get("flag_reason") or "").strip() if flag else ""
    result["classified_by"] = classified_by
    return result
