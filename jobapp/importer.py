"""Backfill the DB from existing ``imports/*.json`` files.

Re-parses and re-classifies old scrapes with the new logic (so the positional
title/company bug is fixed and everything gets categories), letting the UI show
data immediately — before running any new scrape. Old files have no LinkedIn
job id, so a content hash is used as ``external_id`` (prefixed ``legacy-``),
which also deduplicates identical cards that were saved across multiple files.

Run:  python -m jobapp.importer
"""

import glob
import hashlib
import json
import os

from . import config
from .db import SessionLocal, init_db
from .pipeline import process_raw


def _legacy_external_id(card_lines, description) -> str:
    basis = "\n".join(card_lines) + "\n" + (description or "")[:300]
    return "legacy-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _record_to_raw(record: dict) -> dict:
    card_lines = record.get("ozet_bilgi_ham")
    if not card_lines:
        info = record.get("siniflandirilmis_bilgi", {})
        card_lines = [
            info.get("ilan_basligi", ""),
            info.get("sirket", ""),
            info.get("lokasyon", ""),
        ] + list(info.get("ek_bilgiler", []))
    card_lines = [l for l in card_lines if l]
    description = record.get("detayli_aciklama", "")
    return {
        "external_id": _legacy_external_id(card_lines, description),
        "url": "",
        "card_lines": card_lines,
        "description": description,
        "search_term": record.get("arama_terimi", ""),
        "search_location": "",
    }


def import_all(job_list_dir: str = None) -> dict:
    job_list_dir = job_list_dir or config.LEGACY_JOB_LIST_DIR
    init_db()
    session = SessionLocal()
    stats = {"files": 0, "new": 0, "updated": 0, "skipped": 0}

    files = sorted(glob.glob(os.path.join(job_list_dir, "*.json")))
    for path in files:
        stats["files"] += 1
        try:
            with open(path, encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[skip] {os.path.basename(path)}: {e}")
            continue

        for record in records or []:
            raw = _record_to_raw(record)
            try:
                job, created = process_raw(session, raw, use_llm=False)
                session.commit()
            except Exception as e:
                session.rollback()
                print(f"[skip record] {e}")
                stats["skipped"] += 1
                continue
            if not job.quality_ok:
                stats["skipped"] += 1
            elif created:
                stats["new"] += 1
            else:
                stats["updated"] += 1

    session.close()
    return stats


def main():
    print(f"Importing from: {config.LEGACY_JOB_LIST_DIR}")
    stats = import_all()
    print(
        f"Done. files={stats['files']} new={stats['new']} "
        f"updated={stats['updated']} skipped(noise/dupe)={stats['skipped']}"
    )


if __name__ == "__main__":
    main()
