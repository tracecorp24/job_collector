"""Small, isolated scrape benchmarks; retain history/cache when hiding results.

Live runs keep normal source pacing and stop on source blocks. Replay runs use
recorded public responses without network access; their timings are CPU timings.
All databases, captured responses and reports must stay inside this repo's .qa/.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent


def qa_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(ROOT / ".qa"):
        raise ValueError("Benchmark artifacts must be inside the repository's .qa directory.")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--source-root", default=str(ROOT))
    parser.add_argument("--policy-db")
    parser.add_argument("--keyword", default="Python Developer")
    parser.add_argument("--location", default="Istanbul, Turkey")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--mode", choices=("immediate", "deferred"), default="deferred")
    parser.add_argument("--delete-after", action="store_true")
    parser.add_argument("--max-requests", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=120)
    transport = parser.add_mutually_exclusive_group(required=True)
    transport.add_argument("--live", action="store_true")
    transport.add_argument("--replay", help="Captured responses.jsonl; never falls back to network.")
    args = parser.parse_args()
    if not 1 <= args.limit <= 30 or not 1 <= args.max_requests <= 40:
        parser.error("Use a small sample: limit 1..30, max-requests 1..40.")
    if not args.label.replace("-", "").replace("_", "").isalnum():
        parser.error("label must contain only letters, digits, hyphens or underscores")
    output = qa_path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / (args.label + ".json")
    if report_path.exists():
        parser.error("That report already exists; use a new label to retain all measurements.")
    os.environ["JOBAPP_DB_PATH"] = str(output / "jobs.db")
    os.environ["JOBAPP_ACCOUNTLESS_OUTPUT_DIR"] = str(output / "searches")
    sys.path.insert(0, str(Path(args.source_root).resolve()))
    import requests
    from sqlalchemy import create_engine
    from jobapp import config, db, details, pipeline, server
    from jobapp.models import DetailCache, Job, SearchEvent, SearchRun, TaskJob
    from jobapp.scraper.accountless import AccountlessScraper
    from jobapp.transport import Coordinator

    logging.basicConfig(level=logging.ERROR)
    config.API_KEY = config.ADMIN_KEY = ""  # isolated Flask test client only
    client = server.create_app().test_client()
    policy_engine = create_engine("sqlite:///" + str(qa_path(args.policy_db))) if args.policy_db else db.engine
    if args.replay:
        config.MIN_REQUEST_INTERVAL = config.REQUEST_INTERVAL = config.REQUEST_JITTER = 0
        AccountlessScraper.REQUEST_INTERVAL = 0
    coordinator = Coordinator(engine=policy_engine)
    source_before = coordinator.state()
    recorded = {}
    if args.replay:
        for line in qa_path(args.replay).read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            recorded.setdefault(item["key"], item)
    original_get = requests.Session.get
    started = time.monotonic()
    events, requests_made, job_ids = [], [], set()
    first_card = None

    def stopped():
        return time.monotonic() - started >= args.timeout or len(requests_made) >= args.max_requests

    def emit(kind, data):
        nonlocal first_card
        elapsed = round(time.monotonic() - started, 4)
        event = dict(kind=kind, elapsed_s=elapsed, data=data)
        events.append(event)
        with (output / (args.label + "-events.jsonl")).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        if kind == "processing_result" and data.get("status") == "saved":
            job_ids.add(data["job_id"])
            if first_card is None:
                first_card = elapsed
        if kind in ("request_finished", "source_paused", "error"):
            print(json.dumps(dict(label=args.label, kind=kind, elapsed_s=elapsed,
                                  status=data.get("status"), cards=data.get("cards_returned"),
                                  message=data.get("message") or data.get("msg")), ensure_ascii=False), flush=True)

    def get(session, url, **kwargs):
        key = json.dumps([url, kwargs.get("params") or {}], sort_keys=True)
        tick = time.monotonic()
        entry = dict(url=url, params=kwargs.get("params"), kind="list" if "seeMoreJobPostings" in url else "detail")
        requests_made.append(entry)
        try:
            if args.live:
                response = original_get(session, url, **kwargs)
            else:
                if key not in recorded:
                    raise AssertionError("Replay has no response for " + key)
                saved = recorded[key]
                response = requests.Response()
                response.status_code = saved["status"]
                response._content = saved["html"].encode("utf-8")
                response._content_consumed = True
                response.encoding = "utf-8"
                response.headers.update(saved["headers"])
            entry.update(status=response.status_code, duration_s=round(time.monotonic() - tick, 4))
            if args.live:
                saved = dict(key=key, status=response.status_code, html=response.text,
                             headers={k: v for k, v in response.headers.items()
                                      if k.lower() in ("retry-after", "location", "content-type")})
                with (output / "responses.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(saved, ensure_ascii=False) + "\n")
            return response
        except Exception as exc:
            entry.update(error=type(exc).__name__, duration_s=round(time.monotonic() - tick, 4))
            raise

    def configure(scraper):
        scraper.max_retries = 0  # short benchmark; normal pacing and blocks still apply
        scraper.coordinator = coordinator

    result = {}
    error = None
    list_done = None
    try:
        with patch.object(requests.Session, "get", get):
            result = pipeline.run_scrape([args.keyword], [args.location], limit=args.limit,
                classify_backend="rules", use_embeddings=False, emit=emit, should_stop=stopped,
                on_scraper_ready=configure, search_options={"defer_details": args.mode == "deferred", "sort_recent": True})
            list_done = round(time.monotonic() - started, 4)
            if args.mode == "deferred" and not result.get("paused") and not stopped():
                scraper = AccountlessScraper(emit=emit, should_stop=stopped, max_retries=0)
                configure(scraper)
                try:
                    # Bound completion to this benchmark's rows and request budget.
                    for _ in range(args.limit * details.MAX_ATTEMPTS):
                        if stopped() or coordinator.state()["paused"] or not details.fill_one(server, scraper):
                            break
                finally:
                    scraper.session.close()
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    elapsed = round(time.monotonic() - started, 4)
    with server.SessionLocal() as session:
        rows = session.query(Job).filter(Job.id.in_(job_ids)).all() if job_ids else []
        listings = [dict(id=j.id, external_id=j.external_id, title=j.title, url=j.url,
                         has_description=bool(j.description), hidden=bool(j.deleted_at)) for j in rows]
        counts_before = dict(jobs=session.query(Job).count(), cache=session.query(DetailCache).count(),
                             runs=session.query(SearchRun).count(), events=session.query(SearchEvent).count(),
                             discoveries=session.query(TaskJob).count())
    deletion = None
    if args.delete_after and job_ids:
        response = client.post("/api/trash/jobs", json={"ids": sorted(job_ids), "action": "delete"})
        deletion = dict(status=response.status_code, result=response.json)
    with server.SessionLocal() as session:
        counts_after = dict(jobs=session.query(Job).count(), visible=session.query(Job).filter(Job.deleted_at.is_(None)).count(),
                            cache=session.query(DetailCache).count(), runs=session.query(SearchRun).count(),
                            events=session.query(SearchEvent).count(), discoveries=session.query(TaskJob).count())
    report = dict(label=args.label, transport="live" if args.live else "recorded-response replay (CPU timing only)",
                  mode=args.mode, keyword=args.keyword, location=args.location, limit=args.limit,
                  first_card_s=first_card, list_complete_s=list_done, complete_s=elapsed,
                  requests=len(requests_made), list_requests=sum(r["kind"] == "list" for r in requests_made),
                  detail_requests=sum(r["kind"] == "detail" for r in requests_made),
                  cache_hits=sum(e["kind"] == "cache_hit" for e in events),
                  completed_details=sum(j["has_description"] for j in listings), result=result,
                  error=error, source_before=source_before, source_after=coordinator.state(),
                  listings=listings, deletion=deletion, counts_before=counts_before, counts_after=counts_after,
                  request_log=requests_made)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("label", "transport", "first_card_s", "list_complete_s", "complete_s",
                                           "requests", "list_requests", "detail_requests", "cache_hits", "completed_details", "error")}, ensure_ascii=False), flush=True)
    print("REPORT " + str(report_path), flush=True)
    if error or result.get("paused") or not job_ids:
        return 2
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
