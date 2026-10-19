"""Three-layer ordering, safe preemption and selected-field repair."""
import json
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import test_light
import test_workspace
from test_light import card, response, DETAIL
from jobapp import repair, runs, scheduling, server, service, watches
from jobapp.models import Job, RepairTask, SearchRun, SearchTask


class SchedulingTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown

    def run_row(self, session, ident, layer="manual", status="queued", **options):
        run = SearchRun(id=ident, status=status, options=json.dumps(dict(queue_layer=layer,
            kind="scrape", service_managed=True, **options)))
        session.add(run)
        session.add(SearchTask(id=ident+"-task", run_id=ident, keyword=ident, location="City", limit=1, status=status))
        session.flush()
        return run

    def missing(self, session):
        repair.enqueue(session, {"external_id":"123", "card_layout":"guest", "card_lines":["Dev","Company","City"]})
        session.commit()

    def test_manual_analysis_precedes_repair_and_routine(self):
        with self.factory() as session:
            self.run_row(session, "old-routine", "routine")
            run = self.run_row(session, "manual")
            run.options = json.dumps(dict(kind="classify", queue_layer="manual", service_managed=True))
            self.missing(session)
        with patch.object(runs, "start") as start, patch.object(repair, "dispatch") as dispatch:
            service.tick(server)
        start.assert_called_once_with(server, "manual")
        dispatch.assert_not_called()

    def test_repair_precedes_existing_and_due_routine(self):
        with self.factory() as session:
            self.run_row(session, "routine", "routine")
            self.missing(session)
        with patch.object(repair, "dispatch", return_value=True) as dispatch, patch.object(runs, "start") as start, patch.object(watches, "dispatch") as watch:
            service.tick(server)
        dispatch.assert_called_once()
        start.assert_not_called()
        watch.assert_not_called()

    def test_retry_deadline_does_not_block_routine(self):
        with self.factory() as session:
            self.run_row(session, "routine", "routine")
            self.missing(session)
            task = session.query(RepairTask).one()
            task.status, task.next_attempt_at = "retry", time.time()+1000
            session.commit()
        with patch.object(runs, "start") as start:
            service.tick(server)
        start.assert_called_once_with(server, "routine")

    def test_manual_paused_by_user_is_not_automatically_resumed(self):
        with self.factory() as session:
            self.run_row(session, "paused-manual", status="paused", user_paused=True, auto_resume_at=0)
            self.run_row(session, "routine", "routine")
            session.commit()
        with patch.object(runs, "start") as start:
            service.tick(server)
        start.assert_called_once_with(server, "routine")

    def test_active_routine_yields_to_new_repair(self):
        with self.factory() as session:
            self.run_row(session, "routine", "routine", "running")
            self.missing(session)
        with patch.object(server.state, "running", True), patch.object(server.state, "run_id", "routine"), patch.object(server.state, "kind", "scrape"):
            service.tick(server)
            self.assertTrue(server.state.stop_flag)
        with self.factory() as session:
            options = json.loads(session.get(SearchRun, "routine").options)
            self.assertEqual(options["priority_yield"], "repair")
            self.assertEqual(options["auto_resume_at"], 0)

    def test_equal_manual_priority_does_not_interrupt_current_work(self):
        with self.factory() as session:
            self.run_row(session, "active", status="running")
            session.commit()
        with patch.object(server.state, "running", True), patch.object(server.state, "run_id", "active"), patch.object(server.state, "kind", "scrape"):
            reply = self.client.post("/api/scrape", json={"tasks":[{"keyword":"new"}]})
            self.assertEqual(reply.status_code, 200)
            self.assertTrue(reply.json["queued"])
            self.assertFalse(server.state.stop_flag)

    def test_manual_arrival_preserves_routine_checkpoint_then_resumes(self):
        entered, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(10))
            return response(DETAIL)
        replies = [response(card(1)+card(2)), response(DETAIL), blocked]
        def get(*args, **kwargs):
            reply = replies.pop(0)
            return reply(*args, **kwargs) if callable(reply) else reply
        with self.factory() as session:
            self.run_row(session, "routine", "routine")
            session.get(SearchTask, "routine-task").limit = 2
            session.commit()
        with patch("requests.Session.get", side_effect=get):
            with runs.lock:
                runs.start(server, "routine")
            try:
                self.assertTrue(entered.wait(10))
                manual = self.client.post("/api/scrape", json={"tasks":[{"keyword":"manual", "limit":1}]})
                self.assertEqual(manual.status_code, 200)
                self.assertTrue(manual.json["queued"])
            finally:
                release.set()
                server.state.thread.join(10)
        with self.factory() as session:
            run = session.get(SearchRun, "routine")
            task = session.get(SearchTask, "routine-task")
            checkpoint = json.loads(task.checkpoint)
            self.assertEqual(run.status, "paused")
            self.assertIn("öncelikli", run.status_reason)
            self.assertEqual(checkpoint["collected"], 1)
            self.assertIn("1", checkpoint["seen"])
            self.assertTrue(checkpoint["page_snapshot"])
        with patch("requests.Session.get", side_effect=[response(card(9)), response(DETAIL)]):
            service.tick(server)
            server.state.thread.join(10)
        with self.factory() as session:
            self.assertEqual(session.get(SearchRun, manual.json["run_id"]).status, "finished")
        with patch("requests.Session.get", return_value=response(DETAIL)) as get:
            service.tick(server)
            server.state.thread.join(10)
        self.assertEqual(get.call_count, 1)
        self.assertIn("/jobPosting/2", get.call_args.args[0])
        with self.factory() as session:
            self.assertEqual(session.get(SearchRun, "routine").status, "finished")
            self.assertEqual(json.loads(session.get(SearchTask, "routine-task").checkpoint)["collected"], 2)

    def test_manual_source_work_is_accepted_during_cooldown(self):
        source = dict(paused=True, remaining_seconds=300, blocked_until=time.time()+300)
        with patch("jobapp.transport.Coordinator.state", return_value=source), patch.object(runs, "start") as start:
            reply = self.client.post("/api/scrape", json={"tasks":[{"keyword":"new"}]})
            self.assertEqual(reply.status_code, 200)
            self.assertTrue(reply.json["queued"])
            start.assert_not_called()

    def test_watch_and_explicit_run_now_have_different_layers(self):
        ident = self.client.post("/api/watches", json={"keywords":["Dev"], "locations":["City"]}).json["watch"]["id"]
        with self.factory() as session:
            routine_id = watches.dispatch(session, time.time(), {"paused":False})
            self.assertEqual(scheduling.layer(json.loads(session.get(SearchRun, routine_id).options)), "routine")
            session.get(SearchRun, routine_id).status = "finished"
            session.commit()
        reply = self.client.post(f"/api/watches/{ident}/run-now")
        self.assertEqual(reply.status_code, 200)
        with self.factory() as session:
            self.assertEqual(json.loads(session.get(SearchRun, reply.json["run_id"]).options)["queue_layer"], "manual")

    def test_restart_retains_priority_and_checkpoint(self):
        with self.factory() as session:
            self.run_row(session, "routine", "routine", "running")
            self.run_row(session, "manual")
            task = session.get(SearchTask, "routine-task")
            task.checkpoint = json.dumps(dict(collected=2, page=3, seen=["1","2"]))
            session.commit()
        runs.recover(self.factory)
        with patch.object(runs, "start") as start:
            service.tick(server)
        start.assert_called_once_with(server, "manual")
        with self.factory() as session:
            self.assertEqual(session.get(SearchRun, "routine").status, "paused")
            self.assertEqual(json.loads(session.get(SearchTask, "routine-task").checkpoint)["page"], 3)
            self.assertEqual(scheduling.layer(json.loads(session.get(SearchRun, "routine").options)), "routine")

    def test_status_exposes_exact_three_layers_and_counts(self):
        with self.factory() as session:
            self.run_row(session, "manual")
            self.run_row(session, "routine", "routine")
            self.missing(session)
        status = self.client.get("/api/scrape/status").json["queue_layers"]
        self.assertEqual(status["order"], ["manual","repair","routine"])
        self.assertEqual([l["ready"] for l in status["layers"]], [1,1,1])

    def seed_job(self):
        with self.factory() as session:
            job = Job(external_id="123", title="Dev", company="Old Company", location="City", description="Original description",
                summary="Keep summary", tags="[]", raw=json.dumps({"posted":"2026-10-01", "detail_fetched_at":12345}), created_at=datetime.utcnow()-timedelta(days=7))
            session.add(job)
            session.commit()
            return job.id, job.created_at

    def step(self, layer="manual"):
        from jobapp.transport import Coordinator
        with self.factory() as session:
            self.assertTrue(repair.dispatch(server, session, time.time(), Coordinator().state(), layer))
        server.state.thread.join(10)
        self.assertFalse(server.state.thread.is_alive())

    def test_selected_company_refresh_preserves_other_fields(self):
        ident, created = self.seed_job()
        result = self.client.post(f"/api/jobs/{ident}/repair", json={"fields":["company"]})
        self.assertEqual(result.status_code, 202)
        with patch("requests.Session.get", return_value=response('<a class="topcard__org-name-link">New Company</a>')) as get:
            self.step()
            self.step()
        self.assertEqual(get.call_count, 1)
        with self.factory() as session:
            job = session.get(Job, ident)
            self.assertEqual(job.company, "New Company")
            self.assertEqual(job.description, "Original description")
            self.assertEqual(job.title, "Dev")
            self.assertEqual(job.summary, "Keep summary")
            self.assertEqual(job.created_at, created)
            self.assertEqual(json.loads(job.raw)["posted"], "2026-10-01")
            self.assertEqual(json.loads(job.raw)["detail_fetched_at"], 12345)
            self.assertEqual(session.query(RepairTask).one().status, "done")

    def test_derived_field_repair_does_not_fetch_source(self):
        ident, _ = self.seed_job()
        with self.factory() as session:
            session.get(Job, ident).description = "Python. En az 3 yıl deneyim."
            session.commit()
        self.assertEqual(self.client.post(f"/api/jobs/{ident}/repair", json={"fields":["tags","experience_years"]}).status_code, 202)
        with patch("requests.Session.get", side_effect=AssertionError("local repair")) as get:
            self.step()
        get.assert_not_called()
        with self.factory() as session:
            job = session.get(Job, ident)
            self.assertIn("Python", json.loads(job.tags))
            self.assertEqual(job.experience_years, 3)

    def test_deferred_repair_uses_original_backend_and_clears_pending(self):
        from jobapp import config, groq_client, pipeline
        with patch.object(config, "GROQ_API_KEY", "test"), patch.object(groq_client, "chat_json", return_value={"summary":"Completed", "tags":["python"]}) as chat:
            with patch("requests.Session.get", side_effect=[response(card(7)), response("")]):
                pipeline.run_scrape(["AI"], ["City"], classify_backend="groq", search_options={"defer_details":True})
            chat.assert_not_called()
            with patch("requests.Session.get", return_value=response(DETAIL)):
                self.step("repair")
                self.step("repair")
            chat.assert_called_once()
        with self.factory() as session:
            job = session.query(Job).one()
            self.assertFalse(json.loads(job.raw).get("detail_pending"))
            self.assertEqual(job.classified_by, "groq")
            self.assertEqual(job.summary, "Completed")

    def test_manual_detail_alias_queues_without_network(self):
        ident, _ = self.seed_job()
        with patch("requests.Session.get", side_effect=AssertionError("request handler must only enqueue")) as get:
            reply = self.client.post(f"/api/jobs/{ident}/fetch-detail")
        self.assertEqual(reply.status_code, 202)
        self.assertTrue(reply.json["queued"])
        get.assert_not_called()

    def test_invalid_or_unavailable_fields_are_not_invented(self):
        ident, _ = self.seed_job()
        self.assertEqual(self.client.post(f"/api/jobs/{ident}/repair", json={"fields":["salary"]}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/jobs/{ident}/repair", json={"fields":["company"]}).status_code, 202)
        with patch("requests.Session.get", return_value=response("<html>missing field</html>")):
            self.step()
        with self.factory() as session:
            self.assertEqual(session.get(Job, ident).company, "Old Company")
            self.assertEqual(session.query(RepairTask).one().status, "retry")

    def test_paused_completion_stays_parked_until_explicit_resume(self):
        with self.factory() as session:
            self.missing(session)
            self.run_row(session, "routine", "routine")
            session.commit()
        self.assertEqual(self.client.post("/api/completion-queue/pause").status_code, 200)
        runs.recover(self.factory)
        with patch.object(runs, "start") as start:
            service.tick(server)
        start.assert_called_once_with(server, "routine")
        self.assertTrue(self.client.get("/api/scrape/status").json["completion_queue"]["paused"])
        from jobapp import problems
        with self.factory() as session:
            self.assertIsNone(problems.detail_backlog(session, time.time()+100000))
        self.assertEqual(self.client.post("/api/completion-queue/resume").status_code, 200)
        with patch.object(repair, "dispatch", return_value=True) as dispatch, patch.object(runs, "start") as start:
            service.tick(server)
        dispatch.assert_called_once()
        start.assert_not_called()

    def test_newer_scan_is_not_overwritten_by_already_fetched_detail(self):
        ident, _ = self.seed_job()
        self.client.post(f"/api/jobs/{ident}/repair", json={"fields":["description"]})
        with patch("requests.Session.get", return_value=response(DETAIL)):
            self.step()
        with self.factory() as session:
            session.get(Job, ident).description = "A newer scan owns this description"
            session.get(Job, ident).company = "New company from scan"
            session.commit()
        self.step()
        with self.factory() as session:
            self.assertEqual(session.get(Job, ident).description, "A newer scan owns this description")
            self.assertEqual(session.get(Job, ident).company, "New company from scan")
            self.assertEqual(session.query(RepairTask).one().stage, "detail")
            self.assertEqual(session.query(RepairTask).one().status, "pending")

    def test_source_pause_does_not_count_as_failed_field_attempt(self):
        ident, _ = self.seed_job()
        self.client.post(f"/api/jobs/{ident}/repair", json={"fields":["description"]})
        with patch("requests.Session.get", return_value=response(status=429, **{"Retry-After":"120"})):
            self.step()
        from jobapp.transport import Coordinator
        with self.factory() as session:
            task = session.query(RepairTask).one()
            self.assertEqual(task.attempts, 0)
            self.assertEqual(task.status, "retry")
            self.assertGreaterEqual(task.next_attempt_at, Coordinator().state()["blocked_until"])


if __name__ == "__main__":
    unittest.main()
