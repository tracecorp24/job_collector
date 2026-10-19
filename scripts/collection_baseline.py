"""Read-only collection measurements and optional SQLite online backup (no app imports)."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def capture(database, backup_dir=None):
    path = Path(database).resolve(strict=True)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source:
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        result = {"captured_at": datetime.now(timezone.utc).isoformat(), "counts": {}, "events": {}}
        for name in ("jobs", "search_runs", "search_tasks", "task_jobs", "detail_cache"):
            if name in tables:
                result["counts"][name] = source.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        if "search_events" in tables:
            result["events"] = dict(source.execute("SELECT kind,count(*) FROM search_events GROUP BY kind"))
        if "source_policy" in tables:
            source.row_factory = sqlite3.Row
            result["source_policy"] = [dict(r) for r in source.execute(
                "SELECT source, next_request_at, blocked_until, violation_streak, interval_floor FROM source_policy")]
        if backup_dir:
            destination = Path(backup_dir)
            destination.mkdir(parents=True, exist_ok=True)
            backup = destination / ("collection-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".db")
            with sqlite3.connect(backup) as target:
                source.backup(target)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("Yedek bütünlük kontrolü başarısız.")
            result["backup"] = str(backup)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup-dir")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = capture(args.db, args.backup_dir)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Ölçüm kaydedildi; kaynak veritabanı değiştirilmedi.")
