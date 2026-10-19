"""Durable completion and scheduling without contacting LinkedIn."""
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_light
import test_workspace
from test_light import card, response, DETAIL
from jobapp import config, repair, server, service, runs
from jobapp.models import Job, RepairTask, SearchRun, SearchTask
from jobapp.transport import Details, Coordinator


class RepairTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown
    scrape = test_light.FullLightTests.scrape

    def seed(self):
        with self.factory() as session:
            session.add(Job(external_id="123", title="Engineer", company="Company", location="City", description=" ",
                            raw="{}", summary="Korunacak özet", tags="[]"))
            session.commit()

    def step(self):
        with self.factory() as session:
            started = repair.dispatch(server, session, time.time(), Coordinator().state())
        if started:
            server.state.thread.join(10)
            self.assertFalse(server.state.thread.is_alive())
        return started

    def test_legacy_missing_description_two_stages_and_export(self):
        self.seed()
        pool = Path(config.ACCOUNTLESS_OUTPUT_DIR)/"legacy"/"ilan_havuzu"
        pool.mkdir(parents=True)
        export = pool/"ap-linkedin-123.json"
        export.write_text(json.dumps({"desc":"", "_collector":{"searchId":"old"}}))
        with patch("requests.Session.get", return_value=response(DETAIL)) as get:
            self.assertTrue(self.step())
            with self.factory() as session:
                self.assertEqual(session.get(RepairTask, ("linkedin", "123")).stage, "enrich")
            self.assertTrue(self.step())
            self.assertFalse(self.step())
        self.assertEqual(get.call_count, 1)
        with self.factory() as session:
            job = session.query(Job).one()
            self.assertIn("Python", job.description)
            self.assertEqual(job.summary, "Korunacak özet")
            self.assertEqual(session.get(RepairTask, ("linkedin", "123")).status, "done")
        data = json.loads(export.read_text(encoding="utf-8"))
        self.assertIn("Python", data["desc"])
        self.assertEqual(data["_collector"]["searchId"], "old")
        self.assertTrue(data["_collector"]["descriptionAvailable"])

    def test_failed_card_is_durable_and_later_saved(self):
        self.scrape([response(card(77)), response("<html>no detail</html>"), response("")], 1)
        with self.factory() as session:
            task = session.get(RepairTask, ("linkedin", "77"))
            self.assertIsNotNone(task)
            self.assertTrue(json.loads(task.raw)["search_id"])
        with patch("requests.Session.get", return_value=response(DETAIL)):
            self.step()
            self.step()
        with self.factory() as session:
            self.assertEqual(session.query(Job).one().external_id, "77")
            self.assertEqual(session.get(RepairTask, ("linkedin", "77")).status, "done")

    def test_retry_preserves_delay_and_deduplicates(self):
        self.seed()
        with patch("requests.Session.get", return_value=response("<html>empty</html>")) as get:
            self.step()
            self.assertFalse(self.step())
        self.assertEqual(get.call_count, 1)
        with self.factory() as session:
            task = session.query(RepairTask).one()
            deadline = task.next_attempt_at
            repair.enqueue(session, {"external_id":"123"})
            session.commit()
            self.assertEqual(session.query(RepairTask).count(), 1)
            self.assertEqual(task.attempts, 1)
            self.assertGreater(deadline, time.time()+250)
            self.assertEqual(task.next_attempt_at, deadline)
        report = self.client.get("/api/completion-queue?status=retry")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json["items"][0]["external_id"], "123")
        self.assertEqual(report.json["items"][0]["attempts"], 1)
        self.assertIn("description", report.json["items"][0]["last_error"])

    def test_removed_source_and_deleted_jobs_are_not_retried(self):
        self.seed()
        with patch("requests.Session.get", return_value=response(status=404)) as get:
            self.step()
            self.assertFalse(self.step())
        self.assertEqual(get.call_count, 1)
        with self.factory() as session:
            self.assertEqual(session.query(RepairTask).one().status, "unavailable")

    def test_source_pause_allows_only_local_enrichment(self):
        self.seed()
        with self.factory() as session:
            repair.discover(session)
            session.commit()
            self.assertFalse(repair.dispatch(server, session, time.time(), {"paused":True}))
            task = session.query(RepairTask).one()
            task.stage = "enrich"
            raw = json.loads(task.raw)
            raw["description"] = "Python engineer"
            task.raw = json.dumps(raw)
            session.commit()
            with patch("requests.Session.get", side_effect=AssertionError("network during pause")):
                self.assertTrue(repair.dispatch(server, session, time.time(), {"paused":True}))
        server.state.thread.join(10)
        with self.factory() as session:
            self.assertEqual(session.query(RepairTask).one().status, "done")

    def test_empty_success_cache_is_not_reused(self):
        raw = {"external_id":"123", "card_lines":["Engineer","Company","City"]}
        Details().put(raw, "  ")
        self.assertIsNone(Details().get(raw))

    def test_manual_search_precedes_repair_and_older_routine(self):
        self.seed()
        with self.factory() as session:
            session.add(SearchRun(id="analysis", options=json.dumps({"kind":"scrape","queue_layer":"routine","service_managed":True})))
            session.add(SearchTask(id="analysis-task",run_id="analysis",keyword="classify"))
            session.add(SearchRun(id="search", options=json.dumps({"kind":"scrape","service_managed":True})))
            session.add(SearchTask(id="search-task",run_id="search",keyword="Engineer"))
            session.commit()
        with patch.object(runs, "start") as start, patch.object(repair, "dispatch") as dispatch:
            service.tick(server)
            start.assert_called_once_with(server, "search")
            dispatch.assert_not_called()

    def test_new_search_is_queued_while_completion_yields(self):
        with patch.object(server.state, "running", True), patch.object(server.state, "kind", "repair"):
            result = self.client.post("/api/scrape", json={"keywords":["Engineer"]})
            self.assertEqual(result.status_code, 200)
            self.assertTrue(server.state.stop_flag)
            with self.factory() as session:
                run = session.get(SearchRun, result.json["run_id"])
                self.assertEqual(run.status, "queued")
                self.assertTrue(json.loads(run.options)["service_managed"])
        server.state.stop_flag = False

    def test_ready_enrichment_precedes_another_network_request(self):
        self.seed()
        with patch("requests.Session.get", return_value=response(DETAIL)):
            self.step()
        with self.factory() as session:
            repair.enqueue(session, {"external_id":"456"})
            session.commit()
        with patch("requests.Session.get", side_effect=AssertionError("complete fetched job first")):
            self.step()
        with self.factory() as session:
            self.assertEqual(session.get(RepairTask, ("linkedin", "123")).status, "done")
            self.assertEqual(session.get(RepairTask, ("linkedin", "456")).status, "pending")

    def test_purged_job_is_not_resurrected(self):
        self.seed()
        with self.factory() as session:
            repair.discover(session)
            session.query(Job).delete()
            session.commit()
        with patch("requests.Session.get", side_effect=AssertionError("purged job")) as get:
            self.step()
        get.assert_not_called()
        with self.factory() as session:
            self.assertEqual(session.query(Job).count(), 0)
            self.assertEqual(session.query(RepairTask).one().status, "deleted")

    def test_restart_preserves_fetched_stage_and_no_second_http_request(self):
        self.seed()
        with patch("requests.Session.get", return_value=response(DETAIL)):
            self.step()
        runs.recover(self.factory)
        with patch("requests.Session.get", side_effect=AssertionError("already fetched")) as get:
            self.step()
        get.assert_not_called()
        with self.factory() as session:
            self.assertEqual(session.query(RepairTask).one().status, "done")


if __name__ == "__main__":
    unittest.main()
