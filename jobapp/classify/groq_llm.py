"""Optional LLM classification via Groq's free tier.

The free tier allows ~8k tokens/minute, so unlike the Claude/Ollama backends this one does
not ask for a full ``formatted_description`` rewrite (the frontend's heuristic formatter is
used instead) and truncates long postings. On quota exhaustion, missing key or any API error
it returns the rule-based result unchanged so the pipeline never breaks.
"""

from .. import config, groq_client, professions
from ._shared import VALID_CATEGORIES, VALID_SENIORITY, apply_fields

INSTRUCTIONS = (
    "You classify job postings. The posting may be in Turkish or English. "
    "Respond with ONLY a compact JSON object using exactly these keys: "
    '{"category": one of ' + str(VALID_CATEGORIES) + ', "seniority": one of ' + str(VALID_SENIORITY) + ', '
    '"workplace_type": one of ["Remote","Hybrid","Onsite",""], '
    '"tags": up to 8 lowercase skill/tool keywords, '
    '"profession_groups": broad occupation categories from the title and description, chosen from '
    + str(professions.MAIN_GROUPS)
    + ', "profession_subgroups": specific profession families chosen from '
    + str(professions.SUBGROUPS)
    + ', '
    '"summary": one neutral sentence (max 25 words) describing the role, in the posting\'s language, '
    '"about_company": one short sentence about the company from the posting, or "", '
    '"offerings": up to 6 short benefit phrases, or [], '
    '"salary": pay range exactly as stated, or "", '
    '"flag": "scam" (asks for fees, MLM, data harvesting), "ghost" (evergreen agency talent-pool listing) or "", '
    '"flag_reason": max 10 words, or "", '
    '"min_experience_years": minimum years of work experience REQUIRED FROM THE CANDIDATE as an integer '
    '(lower bound of a range; 0 for internships/new graduates), never the company\'s age or history, or null}.'
)
MAX_DESCRIPTION = 4000


def enrich(title: str, description: str, base: dict, patient: bool = False) -> dict:
    """Refine ``base`` (the rules result) with Groq; fall back on any failure.

    ``patient``: wait for the per-minute quota to refill (bulk re-analysis). During a scrape
    it is False so collection is never slowed by more than a few seconds."""
    if not config.GROQ_API_KEY:
        return base
    job_text = f"TITLE: {title}\n\nDESCRIPTION:\n{(description or '')[:MAX_DESCRIPTION]}"
    try:
        data = groq_client.chat_json(
            [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": job_text}],
            model=config.GROQ_CLASSIFY_MODEL, max_tokens=700, max_wait=65 if patient else 8,
        )
    except groq_client.GroqError:
        return base
    data.pop("formatted_description", None)
    return apply_fields(base, data, "groq", original_description=description)
