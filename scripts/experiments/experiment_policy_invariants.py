"""Offline experiments against production policy and scraper; no outbound network.

Run from repository root. Each scenario owns a new SQLite database and virtual
clock. Simulated source behavior is a model, never evidence about LinkedIn.
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / ".qa" / "policy-experiments" / uuid.uuid4().hex
RUN.mkdir(parents=True, exist_ok=False)
os.environ["JOBAPP_DB_PATH"] = str(RUN / "bootstrap.db")
sys.path.insert(0, str(ROOT))

import requests
from sqlalchemy import create_engine
from jobapp import config
from jobapp.scraper.accountless import AccountlessScraper
from jobapp.transport import Coordinator, SourcePaused

URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/100"
PUBLIC = '<div class="show-more-less-html__markup">Public job description</div>'
CHALLENGE = '<html><title>Security verification</title><form action="/checkpoint"></form></html>'


def response(status=200, body=PUBLIC, **headers):
    result = requests.Response()
    result.status_code = status
    result._content = body.encode("utf-8")
    result.headers.update(headers)
    result.encoding = "utf-8"
    result.url = URL
    return result


class Sandbox:
    def __init__(self, name, mode):
        self.name, self.mode = name, mode
        self.path = RUN / (name + "-" + mode + ".db")
        self.engine = create_engine("sqlite:///" + self.path.as_posix())
        self.now = 1_800_000_000.0
        self.events, self.calls, self.clients = [], [], []
        self.saved = None
        self.coordinator = self.reopen()

    def reopen(self):
        return Coordinator(engine=self.engine, interval=config.REQUEST_INTERVAL,
                           clock=lambda: self.now, sleeper=self.sleep)

    def sleep(self, seconds):
        # At epoch-scale doubles sub-microsecond remainders need a small advance.
        self.now += max(seconds, 0.000001)

    def client(self, callback=None):
        if self.mode == "persistent" and self.saved is not None:
            self.saved.emit = callback or self.emit
            return self.saved
        with patch("jobapp.scraper.accountless.Details", return_value=Mock()), \
                patch("jobapp.scraper.accountless.Coordinator", return_value=self.coordinator):
            client = AccountlessScraper(emit=callback or self.emit, max_retries=0)
        self.clients.append(client)
        if self.mode == "persistent":
            self.saved = client
        return client

    def emit(self, kind, data):
        self.events.append((kind, dict(data)))

    def fetch(self, item, callback=None, url=URL):
        client = self.client(callback)

        def get(session, requested, **kwargs):
            self.calls.append({"t": self.now, "session": id(session), "url": requested})
            return item() if callable(item) else item

        with patch.object(requests.Session, "get", autospec=True, side_effect=get):
            return client._fetch_url(url)

    def blocked(self, item=None):
        before = len(self.calls)
        try:
            self.fetch(item or response())
        except SourcePaused:
            pass
        else:
            raise AssertionError("expected source pause")
        assert len(self.calls) == before, "HTTP attempted during persisted pause"

    def lease_empty(self):
        with self.coordinator.transaction() as connection:
            row = self.coordinator.row(connection)
        assert not row["lease_owner"] and row["lease_until"] == 0

    def finish(self):
        state = self.coordinator.state()
        result = dict(scenario=self.name, mode=self.mode, passed=True,
                      http_calls=len(self.calls), client_count=len(self.clients),
                      session_count=len(set(c["session"] for c in self.calls)),
                      virtual_seconds=self.now - 1_800_000_000.0,
                      state=state, events=[dict(kind=k, **v) for k, v in self.events])
        for client in self.clients:
            client.session.close()
        self.engine.dispose()
        return result


def paused_case(name, mode):
    s = Sandbox(name, mode)
    if name == "429_numeric":
        item, minimum = response(429, **{"Retry-After": "240"}), 240
    elif name == "429_http_date":
        date = format_datetime(datetime.fromtimestamp(s.now + 420, timezone.utc), usegmt=True)
        item, minimum = response(429, **{"Retry-After": date}), 420
    elif name == "403":
        item, minimum = response(403), config.ACCESS_PAUSE_SECONDS
    elif name == "999":
        item, minimum = response(999), config.ACCESS_PAUSE_SECONDS
    elif name == "200_challenge":
        item, minimum = response(200, CHALLENGE), config.ACCESS_PAUSE_SECONDS
    elif name == "login_redirect":
        item, minimum = response(302, **{"Location": "https://www.linkedin.com/checkpoint/challenge"}), config.ACCESS_PAUSE_SECONDS
    else:
        raise AssertionError(name)
    try:
        s.fetch(item)
    except SourcePaused:
        pass
    else:
        raise AssertionError("expected pause")
    original = s.coordinator.state()
    assert original["remaining_seconds"] >= minimum
    s.lease_empty()
    s.blocked()
    # New HTTP session cannot remove a database policy block.
    if s.saved is not None:
        s.saved._reset_session()
    s.blocked()
    # New engine and new Coordinator model a process restart using the same DB.
    s.engine.dispose()
    s.engine = create_engine("sqlite:///" + s.path.as_posix())
    s.coordinator = s.reopen()
    if s.saved is not None:
        s.saved.coordinator = s.coordinator
    restarted = s.coordinator.state()
    assert restarted["blocked_until"] == original["blocked_until"]
    assert restarted["interval_floor"] == original["interval_floor"]
    try:
        s.coordinator.acknowledge()
    except SourcePaused:
        pass
    else:
        raise AssertionError("acknowledge shortened active source pause")
    s.blocked()
    s.now = original["blocked_until"] + 0.01
    assert s.fetch(response()) is not None
    assert len(s.calls) == 2
    s.lease_empty()
    return s.finish()


def callback_case(name, mode):
    s = Sandbox(name, mode)

    def callback(kind, data):
        s.emit(kind, data)
        if kind == ("request_started" if name == "callback_start" else "request_finished"):
            raise RuntimeError("synthetic observer failure")

    try:
        s.fetch(response(429, **{"Retry-After": "300"}), callback)
    except RuntimeError as exc:
        assert str(exc) == "synthetic observer failure"
    else:
        raise AssertionError("observer should fail")
    s.lease_empty()
    if name == "callback_start":
        assert len(s.calls) == 0
    else:
        assert len(s.calls) == 1
        assert s.coordinator.state()["remaining_seconds"] >= 300
        s.blocked()
    return s.finish()


def ip_budget(mode):
    s = Sandbox("session_independent_ip_budget_model", mode)
    # Explicitly synthetic model: shared upstream/IP budget, unrelated to cookies.
    assert s.fetch(response()) is not None
    assert s.fetch(response()) is not None
    try:
        s.fetch(response(429, **{"Retry-After": "600"}))
    except SourcePaused:
        pass
    else:
        raise AssertionError("modeled IP budget must pause")
    s.blocked()
    assert len(s.calls) == 3
    assert all(b["t"] - a["t"] >= config.MIN_REQUEST_INTERVAL
               for a, b in zip(s.calls, s.calls[1:]))
    return s.finish()


def main():
    results = []
    with patch("socket.socket.connect", side_effect=AssertionError("outbound network forbidden")), \
            patch("jobapp.transport.random.uniform", return_value=config.REQUEST_JITTER / 2):
        for mode in ("persistent", "per_job"):
            for case in ("429_numeric", "429_http_date", "403", "999", "200_challenge", "login_redirect"):
                results.append(paused_case(case, mode))
            for case in ("callback_start", "callback_finished"):
                results.append(callback_case(case, mode))
            results.append(ip_budget(mode))
    budget = [r for r in results if r["scenario"] == "session_independent_ip_budget_model"]
    assert budget[0]["http_calls"] == budget[1]["http_calls"] == 3
    assert budget[0]["state"]["blocked_until"] == budget[1]["state"]["blocked_until"]
    output = dict(kind="offline_production_policy_invariants", network_requests=0,
                  sandbox_dir=str(RUN.relative_to(ROOT)), passed=len(results), scenarios=results,
                  limitations=["Synthetic upstream responses do not establish real source rejection causes.",
                               "No live environment or source policy was changed.",
                               "Session modes share identical policy protections in these scenarios."])
    target = ROOT / ".local/performance-audit-20261020/policy-experiment.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(passed=len(results), failed=0, network_requests=0, output=str(target)), ensure_ascii=True))


if __name__ == "__main__":
    main()
