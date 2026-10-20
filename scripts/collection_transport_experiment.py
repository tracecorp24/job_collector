"""Reproducible loopback experiments; these are NOT LinkedIn error measurements.

Run with the application's dependencies installed, for example:
  .qa/collection-venv/Scripts/python.exe scripts/collection_transport_experiment.py

Each arm runs in a separate process and database. The real production Coordinator
paces real requests.Session traffic to a local HTTP/1.1 fixture. Time advances
virtually; cooldowns are respected without real sleep. Outbound socket connections
are explicitly limited to 127.0.0.1. No production application state is changed.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / ".qa"
SCENARIOS = ("warm_cookie", "ip_window_budget", "retry_after", "description_selector")
MODES = ("fresh_per_job", "persistent")
BODY = '<div class="show-more-less-html__markup">Fixture description</div>'


class VirtualClock:
    def __init__(self):
        self.now = 1700000000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += max(0.0, seconds)

    def until(self, deadline):
        self.now = max(self.now, deadline)


class Fixture(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, scenario, clock):
        self.scenario = scenario
        self.clock = clock
        self.records = []
        self.connections = {}
        self.accepted = 0
        self.window_started = clock()
        self.window_requests = 0
        super().__init__(("127.0.0.1", 0), Handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.accepted += 1
        # Keep object references so recycled object IDs cannot fake socket reuse.
        self.connections[connection] = self.accepted
        return connection, address


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        fixture = self.server
        index = len(fixture.records) + 1
        warm = "fixture_session=warm" in self.headers.get("Cookie", "")
        status, body, retry = 200, BODY, None
        if fixture.scenario == "warm_cookie" and not warm:
            status, body, retry = 429, "Synthetic cookie continuity requirement", "60"
        elif fixture.scenario == "ip_window_budget":
            if fixture.clock() - fixture.window_started >= 90:
                fixture.window_started = fixture.clock()
                fixture.window_requests = 0
            fixture.window_requests += 1
            if fixture.window_requests > 2:
                status, body, retry = 429, "Synthetic IP budget; cookies irrelevant", "90"
        elif fixture.scenario == "retry_after" and index in (1, 5):
            status, body, retry = 429, "Synthetic Retry-After", "90"
            if index == 5:
                retry = format_datetime(datetime.fromtimestamp(fixture.clock() + 90, timezone.utc), usegmt=True)
        elif fixture.scenario == "description_selector":
            variant = (index - 1) % 4
            if variant == 1:
                body = '<div class="show-more-less-html__markup">  </div>'
            elif variant in (2, 3):
                status, body = (404 if variant == 2 else 410), "Removed fixture job"
        record = {"index": index, "virtual_time": fixture.clock(), "status": status,
                  "warm_cookie_received": warm,
                  "connection_id": fixture.connections[self.connection],
                  "retry_after": retry}
        fixture.records.append(record)
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "fixture_session=warm; Path=/; HttpOnly")
        if retry:
            self.send_header("Retry-After", retry)
        self.end_headers()
        self.wfile.write(payload)
        self.wfile.flush()


def loopback_only():
    original = socket.socket.connect

    def guarded(connection, address):
        if not isinstance(address, tuple) or address[0] != "127.0.0.1":
            raise RuntimeError("Offline experiment forbids non-loopback connections")
        return original(connection, address)

    socket.socket.connect = guarded


def run_arm(scenario, mode, directory, requests_count):
    # Set before importing the application. Nothing may touch the real jobs.db.
    os.environ.update({"JOBAPP_DB_PATH": str(directory / "gate.db"),
                       "JOBAPP_ACCOUNTLESS_OUTPUT_DIR": str(directory / "exports"),
                       "JOBAPP_SPOOL_DIR": str(directory / "spool"),
                       "JOBAPP_REQUEST_INTERVAL": "10", "JOBAPP_MIN_REQUEST_INTERVAL": "10",
                       "JOBAPP_REQUEST_JITTER": "0", "JOBAPP_RETRY_BASE_COOLDOWN": "60",
                       "JOBAPP_ACCESS_FAILURE_THRESHOLD": "3", "JOBAPP_ACCESS_PAUSE_SECONDS": "900",
                       "JOBAPP_ACCESS_FAILURE_WINDOW_SECONDS": "3600",
                       "JOBAPP_MAX_ACCESS_PAUSE_SECONDS": "21600"})
    sys.path.insert(0, str(ROOT))
    import requests
    from bs4 import BeautifulSoup
    from jobapp import db
    from jobapp.transport import Coordinator, SourcePaused, retry_after_seconds

    loopback_only()
    clock = VirtualClock()
    gates = [Coordinator(source="offline_fixture", engine=db.engine, clock=clock, sleeper=clock.sleep)
             for _ in range(2)]
    server = Fixture(scenario, clock)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/jobs-guest/jobs/api/jobPosting/fixture"
    session = None
    session_count = 0
    events = []
    pause_checks = 0
    pool_closes = 0
    try:
        for index in range(requests_count):
            gate = gates[index % 2]
            state = gate.state()
            # Advance time to the persisted deadline, never clear/rewrite policy.
            clock.until(max(state["blocked_until"], state["next_request_at"]))
            if session is None:
                session = requests.Session()
                session.trust_env = False
                session_count += 1
            owner = gate.acquire()
            cookie_before = bool(session.cookies)
            try:
                with session.get(url, timeout=5, allow_redirects=False) as response:
                    # Fully consume the response before measuring HTTP pool reuse.
                    body = response.text
                    status = response.status_code
                    retry = response.headers.get("Retry-After")
                    parsed_retry = retry_after_seconds(retry, clock())
                    if status == 429:
                        paused = gate.pause("Offline fixture rate limit", status_code=429, retry_after=retry)
                        assert paused["blocked_until"] >= clock() + (parsed_retry or 0)
                        for observer in gates:
                            before_count = len(server.records)
                            try:
                                observer.ensure_allowed()
                            except SourcePaused:
                                pause_checks += 1
                            else:
                                raise AssertionError("Shared gate failed to preserve block")
                            assert len(server.records) == before_count
                        outcome = "source_paused"
                    elif status in (404, 410):
                        outcome = "unavailable"
                    else:
                        soup = BeautifulSoup(body, "html.parser")
                        box = soup.select_one(".show-more-less-html__markup, .description__text")
                        outcome = "description_present" if box is not None and box.get_text(strip=True) else "description_empty"
                        gate.success()
                    events.append({"index": index + 1, "session_number": session_count,
                                   "virtual_time": clock(), "status": status, "outcome": outcome,
                                   "cookie_present_before": cookie_before, "retry_after_seconds": parsed_retry,
                                   "effective_interval": gate.state()["effective_interval"],
                                   "blocked_until": gate.state()["blocked_until"]})
            finally:
                gate.release(owner)
            if mode == "fresh_per_job":
                session.close()
                pool_closes += 1
                session = None
            elif mode == "persistent_close_pool_midway" and index + 1 == requests_count // 2:
                # Requests Session.close() closes adapter pools, NOT the cookie jar.
                session.close()
                pool_closes += 1
    finally:
        if session is not None:
            session.close()
            pool_closes += 1
        server.shutdown()
        server.server_close()
        thread.join(2)
        db.engine.dispose()

    for event, received in zip(events, server.records):
        assert event["cookie_present_before"] == received["warm_cookie_received"]
    summary = {"scenario": scenario, "mode": mode, "requests": len(events),
               "status_counts": dict(collections.Counter(str(event["status"]) for event in events)),
               "outcome_counts": dict(collections.Counter(event["outcome"] for event in events)),
               "session_objects": session_count, "tcp_connections": server.accepted,
               "requests_reusing_tcp": len(events) - server.accepted,
               "warm_cookie_requests": sum(record["warm_cookie_received"] for record in server.records),
               "pool_close_calls": pool_closes, "shared_block_checks_passed": pause_checks,
               "virtual_elapsed_seconds": clock() - 1700000000.0,
               "coordinator": "production jobapp.transport.Coordinator; two clients share one SQLite DB",
               "request_details": events, "server_records": server.records}
    (directory / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Default; only loopback network connections allowed")
    parser.add_argument("--requests", type=int, default=8, choices=range(8, 21), metavar="8..20")
    parser.add_argument("--output", type=Path, default=QA / "collection-transport-experiment.json")
    parser.add_argument("--worker", choices=SCENARIOS, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=MODES + ("persistent_close_pool_midway",), help=argparse.SUPPRESS)
    parser.add_argument("--sandbox", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    QA.mkdir(exist_ok=True)
    if args.worker:
        sandbox = args.sandbox.resolve()
        if not sandbox.is_relative_to(QA.resolve()):
            parser.error("Sandbox must be inside the workspace .qa directory")
        run_arm(args.worker, args.mode, sandbox, args.requests)
        return
    output = args.output.resolve()
    if not output.is_relative_to(QA.resolve()):
        parser.error("Output must be inside the workspace .qa directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="transport-offline-", dir=QA))
    arms = []
    combinations = [(scenario, mode) for scenario in SCENARIOS for mode in MODES]
    combinations.append(("warm_cookie", "persistent_close_pool_midway"))
    for scenario, mode in combinations:
        sandbox = run_root / (scenario + "--" + mode)
        sandbox.mkdir()
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", scenario,
                                 "--mode", mode, "--sandbox", str(sandbox), "--requests", str(args.requests)],
                                cwd=ROOT, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError(f"Experiment arm failed: {scenario}/{mode}\n{result.stdout}\n{result.stderr}")
        arms.append(json.loads((sandbox / "result.json").read_text(encoding="utf-8")))
    by_arm = {(row["scenario"], row["mode"]): row for row in arms}
    fresh = by_arm["warm_cookie", "fresh_per_job"]
    persistent = by_arm["warm_cookie", "persistent"]
    closed = by_arm["warm_cookie", "persistent_close_pool_midway"]
    checks = {
        "cookie_continuity_lost_with_new_session": fresh["warm_cookie_requests"] == 0,
        "cookie_continuity_retained_with_persistent_session": persistent["warm_cookie_requests"] == args.requests - 1,
        "cookie_model_persistent_has_fewer_errors": persistent["status_counts"].get("429", 0) < fresh["status_counts"].get("429", 0),
        "persistent_reuses_actual_tcp_socket": persistent["tcp_connections"] == 1,
        "fresh_uses_one_socket_per_job": fresh["tcp_connections"] == args.requests,
        "close_preserves_cookies_but_reopens_socket": closed["warm_cookie_requests"] == args.requests - 1 and closed["tcp_connections"] == 2,
        "ip_budget_is_independent_of_session_mode": by_arm["ip_window_budget", "fresh_per_job"]["status_counts"] == by_arm["ip_window_budget", "persistent"]["status_counts"],
        "retry_after_is_independent_of_session_mode": by_arm["retry_after", "fresh_per_job"]["status_counts"] == by_arm["retry_after", "persistent"]["status_counts"],
        "missing_details_independent_of_session_mode": by_arm["description_selector", "fresh_per_job"]["outcome_counts"] == by_arm["description_selector", "persistent"]["outcome_counts"],
        "persistent_never_rotates_after_block": all(row["session_objects"] == 1 for row in arms if row["mode"].startswith("persistent")),
        "shared_blocks_checked_on_every_429": all(row["shared_block_checks_passed"] == 2 * row["status_counts"].get("429", 0) for row in arms),
    }
    document = {"kind": "synthetic_offline_experiment", "external_source_requests": 0,
                "limitations": ["Synthetic fixture behavior cannot establish LinkedIn's blocking mechanism or predict its error rate.",
                                "Description scenario probes the production CSS selector predicate, not the whole repair worker.",
                                "Independent arm databases are safe because every request goes to an independent loopback fixture.",
                                "Production default cooldown policy is used, with jitter disabled and virtual time."],
                "sandbox_root": str(run_root), "checks": checks, "all_checks_passed": all(checks.values()), "arms": arms}
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "all_checks_passed": document["all_checks_passed"],
                      "checks": checks, "arms": [{key: row[key] for key in ("scenario", "mode", "requests", "status_counts", "outcome_counts", "session_objects", "tcp_connections")} for row in arms]}, ensure_ascii=False, indent=2))
    if not document["all_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
