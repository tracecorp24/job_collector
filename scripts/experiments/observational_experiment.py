"""Read saved HTTP events; quantify cohorts without making network requests.

This is an observational comparison, not a causal A/B experiment. The output
does not contain raw URLs, cookies, request headers, or response bodies.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def cohort(value):
    if value < "2026-10-19T09:06:00":
        return "old"
    if value < "2026-10-19T12:11:24":
        return "new_early"
    return "new_latest"


def endpoint(url):
    path = urlsplit(url or "").path
    if "/api/jobPosting/" in path:
        return "guest_detail"
    if "seeMoreJobPostings" in path:
        return "search"
    if "/jobs/view/" in path:
        return "web_detail"
    return "other"


def wilson(k, n):
    if not n:
        return None
    z = 1.959963984540054
    p = k / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [round(100 * (center - margin), 3), round(100 * (center + margin), 3)]


def summary(rows):
    count = len(rows)
    statuses = collections.Counter(str(row["status"]) for row in rows)
    denied = sum(row["status"] in (401, 403, 429, 999) for row in rows)
    numbers = collections.Counter(str(row.get("request_number")) for row in rows)
    gaps = [row["gap_seconds"] for row in rows if row.get("gap_seconds") is not None]
    return {
        "requests": count,
        "statuses": dict(statuses),
        "rate429_percent": round(100 * statuses["429"] / count, 3) if count else None,
        "rate429_wilson95_percent_descriptive_only": wilson(statuses["429"], count),
        "access_denied_percent": round(100 * denied / count, 3) if count else None,
        "request_number_one": numbers["1"],
        "max_request_number": max((row["request_number"] for row in rows if isinstance(row.get("request_number"), int)), default=None),
        "median_gap_seconds": round(statistics.median(gaps), 3) if gaps else None,
        "first_utc": rows[0]["ts"] if rows else None,
        "last_utc": rows[-1]["ts"] if rows else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".local/performance-audit-20261020"))
    args = parser.parse_args()
    source = args.root / "live/events.jsonl"
    events = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    events.sort(key=lambda row: (timestamp(row["ts"]), row["id"]))
    starts = {}
    previous_start = None
    for event in events:
        if event["kind"] != "request_started":
            continue
        data = event["data"]
        current = timestamp(event["ts"])
        starts[data["request_id"]] = {
            "start_utc": event["ts"],
            "gap_seconds": None if previous_start is None else current - previous_start,
            "request_number": data.get("request_number"),
        }
        previous_start = current
    records = []
    for event in events:
        if event["kind"] != "request_finished":
            continue
        data = event["data"]
        records.append({
            **data,
            **starts.get(data.get("request_id"), {}),
            "ts": event["ts"],
            "cohort": cohort(event["ts"]),
            "endpoint": endpoint(data.get("url")),
        })
    cohorts = ("old", "new_early", "new_latest")
    details = [row for row in records if row["endpoint"] == "guest_detail"]
    by_cohort = {name: [row for row in details if row["cohort"] == name] for name in cohorts}
    common_urls = {row["url"] for row in by_cohort["old"]} & {
        row["url"] for row in details if row["cohort"] != "old"
    }
    output = {
        "source": str(source),
        "event_count": len(events),
        "started_count": len(starts),
        "finished_count": len(records),
        "last_event_utc": events[-1]["ts"],
        "cohort_boundaries_utc": ["2026-10-19T09:06:00Z", "2026-10-19T12:11:24Z"],
        "guest_detail": {name: summary(rows) for name, rows in by_cohort.items()},
        "common_url_count_old_vs_all_new": len(common_urls),
        "common_url_requests": {name: summary([row for row in rows if row["url"] in common_urls]) for name, rows in by_cohort.items()},
    }
    gap_results = {}
    for name, rows in by_cohort.items():
        gap_results[name] = {}
        for low, high in [(0, 20), (20, 60), (60, 115), (115, 180), (180, 900), (900, float("inf"))]:
            gap_results[name][f"{low}_to_{high}_seconds"] = summary([
                row for row in rows
                if row.get("gap_seconds") is not None and low <= row["gap_seconds"] < high
            ])
    output["gap_to_previous_observed_source_request"] = gap_results
    first_repeat = {}
    clustering = {}
    for name, rows in by_cohort.items():
        seen = set()
        first, repeats = [], []
        for row in rows:
            (repeats if row["url"] in seen else first).append(row)
            seen.add(row["url"])
        first_repeat[name] = {"unique_urls": len(seen), "first_url_attempt": summary(first), "repeated_url_attempt": summary(repeats)}
        transitions = collections.Counter()
        previous = None
        max_streak = streak = 0
        for row in rows:
            denied = row["status"] in (401, 403, 429, 999)
            if previous is not None:
                transitions[("denied" if previous else "not_denied") + "_then_" + ("denied" if denied else "not_denied")] += 1
            streak = streak + 1 if denied else 0
            max_streak = max(max_streak, streak)
            previous = denied
        clustering[name] = {
            "detail_sequence_max_consecutive_denials": max_streak,
            "detail_sequence_transitions": dict(transitions),
            "first_60_requests": summary(rows[:60]),
            "last_60_requests": summary(rows[-60:]),
            "post_900s_source_gap": summary([row for row in rows if (row.get("gap_seconds") or 0) >= 900]),
        }
    output["first_vs_repeat_within_cohort"] = first_repeat
    output["temporal_clustering"] = clustering
    groups = collections.defaultdict(list)
    for row in records:
        groups[(row["cohort"], row["endpoint"], row["ts"][:10])].append(row)
    output["cohort_endpoint_day_utc"] = [
        {"cohort": key[0], "endpoint": key[1], "day_utc": key[2], **summary(rows)}
        for key, rows in sorted(groups.items())
    ]
    groups.clear()
    for row in details:
        groups[(row["cohort"], row["ts"][11:13])].append(row)
    output["guest_detail_by_clock_hour_utc"] = [
        {"cohort": key[0], "clock_hour_utc": key[1], **summary(rows)}
        for key, rows in sorted(groups.items())
    ]
    output["retry_after_values_access_denied"] = dict(collections.Counter(
        str(row.get("retry_after")) for row in records if row["status"] in (401, 403, 429, 999)
    ))
    output["response_sizes_for_guest_429_by_cohort"] = {
        name: dict(collections.Counter(str(row.get("response_bytes")) for row in rows if row["status"] == 429))
        for name, rows in by_cohort.items()
    }
    output["limitations"] = [
        "Nonrandom historical cohorts have different dates, tasks, URL populations and inherited source policy.",
        "Only one detail URL is shared across old and new cohorts; endpoint matching is not URL matching.",
        "Interrequest gap is measured against the preceding recorded source request, including other endpoints; it is not an explicit interval_floor snapshot.",
        "Long gaps and interval floors follow errors, so gap strata are endogenous and cannot establish rate or session causation.",
        "All new requests are scraper request_number=1; only four old details are number=1, leaving almost no overlap for session-position adjustment.",
        "Wilson intervals are descriptive independent-trial references; serial dependence, cooldown and source state make them insufficient for causal significance.",
        "Missing requests outside these logs or other applications sharing the source IP cannot be excluded.",
        "Null Retry-After log values cannot prove the raw response omitted the header.",
    ]
    target = args.root / "observational-experiment.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(target), "guest_detail": output["guest_detail"], "common_urls": len(common_urls), "clustering": clustering}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
