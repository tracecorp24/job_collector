"""Job classification: rule-based by default, optional LLM upgrade.

``classify_job`` is the single entry point the pipeline calls. It runs the
offline rule-based classifier, then—depending on ``backend``—asks either the
Claude API or a local Ollama model to refine the result, falling back to the
rules on any error.
"""

from . import rules

_BACKENDS = ("rules", "claude", "local")


def classify_job(title: str, description: str, workplace_type: str = "",
                 backend: str = "rules", model: str = None) -> dict:
    result = rules.classify(title, description, workplace_type)
    if backend == "claude":
        from . import llm  # imported lazily so `anthropic` stays optional
        result = llm.enrich(title, description, result)
    elif backend == "local":
        from . import local_llm
        result = local_llm.enrich(title, description, result, model=model)
    return result
