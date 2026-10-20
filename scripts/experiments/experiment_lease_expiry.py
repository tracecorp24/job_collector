"""Offline conditional lease-expiry experiment with production transport code.

A mocked HTTP call represents a response remaining active for 80 seconds. This
does not demonstrate that production responses have that duration or that another
production collector exists. No outbound network is permitted.
"""
import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / ".qa" / "lease-experiments" / uuid.uuid4().hex
RUN.mkdir(parents=True, exist_ok=False)
os.environ["JOBAPP_DB_PATH"] = str(RUN / "bootstrap.db")
sys.path.insert(0, str(ROOT))

import requests
from sqlalchemy import create_engine
from jobapp import config
from jobapp.scraper.accountless import AccountlessScraper
from jobapp.transport import Coordinator


def run(duration, second_probe, interval=None):
    interval = config.REQUEST_INTERVAL if interval is None else interval
    engine = create_engine("sqlite:///" + (RUN / f"duration-{duration}-interval-{interval}.db").as_posix())
    now = [1_800_000_000.0]
    epoch = now[0]
    trace = []
    observed = {}

    def sleep(seconds):
        now[0] += max(seconds, 0.000001)

    first = Coordinator(engine=engine, interval=interval, clock=lambda: now[0], sleeper=sleep)
    second = Coordinator(engine=engine, interval=interval, clock=lambda: now[0], sleeper=sleep)

    def row():
        with first.transaction() as connection:
            return first.row(connection)

    def emit(kind, data):
        trace.append(dict(t=now[0] - epoch, kind=kind, **data))

    def get(session, url, **kwargs):
        initial = row()
        observed.update(first_owner=initial["lease_owner"],
                        first_lease_until=initial["lease_until"] - epoch,
                        first_next_request_at=initial["next_request_at"] - epoch,
                        effective_interval=first.state()["effective_interval"],
                        requests_timeout_argument=kwargs.get("timeout"))
        trace.append(dict(t=0, kind="mock_http_active"))
        if second_probe:
            # Still inside the first HTTP call: its logical response has not ended.
            now[0] = epoch + config.NETWORK_LEASE_SECONDS + 1
            token = second.acquire()
            observed.update(second_owner=token, overlap_while_first_http_active=True,
                            second_acquired_at=now[0] - epoch)
            assert token != initial["lease_owner"]
            trace.append(dict(t=now[0] - epoch, kind="second_owner_acquired_while_http_active"))
        now[0] = epoch + duration
        result = requests.Response()
        result.status_code = 200
        result._content = b'<div class="show-more-less-html__markup">Public description</div>'
        result.encoding = "utf-8"
        result.url = url
        trace.append(dict(t=now[0] - epoch, kind="mock_http_completed"))
        return result

    with patch("jobapp.scraper.accountless.Details", return_value=Mock()), \
            patch("jobapp.scraper.accountless.Coordinator", return_value=first):
        client = AccountlessScraper(emit=emit, max_retries=0)
    try:
        with patch.object(requests.Session, "get", autospec=True, side_effect=get):
            assert client._fetch_url("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/100") is not None
        after_first = row()
        if second_probe:
            # The first scraper's finally has released its stale owner token.
            preserved = after_first["lease_owner"] == observed["second_owner"]
            assert preserved, "stale release cleared a newer owner's lease"
            observed["stale_release_preserves_new_owner"] = preserved
            observed["second_lease_until_after_first_finishes"] = after_first["lease_until"] - epoch
            second.release(observed["second_owner"])
        else:
            assert not after_first["lease_owner"]
            token = second.acquire()
            observed.update(overlap_while_first_http_active=False,
                            second_acquired_at=now[0] - epoch)
            second.release(token)
        assert not row()["lease_owner"]
        return dict(duration_seconds=duration, second_probe_during_first=second_probe,
                    checks_passed=True, observations=observed, trace=trace)
    finally:
        client.session.close()
        engine.dispose()


def main():
    with patch("socket.socket.connect", side_effect=AssertionError("outbound network forbidden")), \
            patch("jobapp.transport.random.uniform", return_value=0):
        scenarios = [run(20, False), run(80, True), run(80, False, 120)]
        assert scenarios[2]["observations"]["second_acquired_at"] >= 120
    result = dict(kind="offline_conditional_lease_expiry", network_requests=0,
                  sandbox_dir=str(RUN.relative_to(ROOT)), lease_seconds=config.NETWORK_LEASE_SECONDS,
                  scenarios=scenarios,
                  expected_limitation="A second Coordinator can acquire after the 60-second lease expires while a modeled first HTTP call remains active for 80 seconds.",
                  stale_release_safety="Owner-qualified release preserves the newer owner's lease.",
                  interpretation="Conditional concurrency risk if multiple source clients share a database and one HTTP request remains active beyond both lease_until and next_request_at. The modeled clean database uses a 10-second interval; an existing 120-second floor prevents this particular 80-second overlap. This is not evidence of observed production overlap.",
                  timeout_limitation="The mocked get receives timeout=20; this experiment models a longer active call but does not measure real socket timeout behavior.")
    target = ROOT / ".local/performance-audit-20261020/lease-experiment.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(passed=len(scenarios), network_requests=0,
                          conditional_overlap=scenarios[1]["observations"]["overlap_while_first_http_active"],
                          stale_release_safe=True, output=str(target)), ensure_ascii=True))


if __name__ == "__main__":
    main()
