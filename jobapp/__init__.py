"""jobapp - Standalone LinkedIn job board.

Pipeline: scrape (accountless HTTP) -> parse -> classify (rules / optional LLM) -> SQLite.
A read-only Flask UI displays the stored jobs and can trigger new scrapes.
"""

__version__ = "1.0.0"
