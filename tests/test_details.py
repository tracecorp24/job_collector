"""Önce kart, detay sonra: taramada detay ertelenir, arka plan tamamlayıcı kaynağa saygılı doldurur."""
import json
import unittest
from unittest.mock import patch
import test_light
from test_light import response, card, DETAIL
from jobapp import audit, config, details, groq_client, pipeline, server
from jobapp.models import Job, SearchEvent
from jobapp.scraper.accountless import AccountlessScraper
from jobapp.transport import Coordinator

DEFER = dict(defer_details=True)


class DeferredDetailTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp

    def job(self, external_id="1"):
        with self.factory() as session:
            job = session.query(Job).filter_by(external_id=external_id).one()
            return job, json.loads(job.raw)

    def test_scan_lists_cards_without_detail_requests(self):
        with patch("requests.Session.get", side_effect=[response(card(1) + card(2)), response("")]) as get:
            pipeline.run_scrape(["AI"], ["Istanbul"], search_options=DEFER)
        self.assertEqual(get.call_count, 2)  # yalnızca arama sayfaları; detay isteği yok
        job, raw = self.job("1")
        self.assertEqual((job.title, job.company, job.description), ("AI Engineer", "Örnek Şirket", ""))
        self.assertTrue(raw["detail_pending"])
        self.assertTrue(job.to_dict()["detail_pending"])

    def test_service_runs_defer_details_by_default(self):
        with patch.object(config, "DEFER_DETAILS", True),              patch("requests.Session.get", side_effect=[response(card(1) + card(2)), response("")]) as get:
            ident = self.client.post("/api/scrape", json={"tasks": [dict(keyword="AI", location="Istanbul")]}).json["run_id"]
            server.state.thread.join(timeout=15)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(self.client.get("/api/runs/" + ident).json["status"], "finished")
        self.assertTrue(self.job("2")[1]["detail_pending"])

    def test_known_job_description_is_never_blanked(self):
        self.scrape_full()
        with patch.object(config, "DETAIL_CACHE_TTL_SECONDS", 0), \
             patch("requests.Session.get", side_effect=[response(card(1)), response("")]) as get:
            pipeline.run_scrape(["AI"], ["Istanbul"], search_options=DEFER)
        self.assertEqual(get.call_count, 2)
        job, raw = self.job("1")
        self.assertIn("PyTorch", job.description)
        self.assertNotIn("detail_pending", raw)

    def scrape_full(self):
        with patch("requests.Session.get", side_effect=[response(card(1)), response(DETAIL), response("")]):
            pipeline.run_scrape(["AI"], ["Istanbul"])

    def deferred(self):
        with patch("requests.Session.get", side_effect=[response(card(1)), response("")]):
            pipeline.run_scrape(["AI"], ["Istanbul"], search_options=DEFER)

    def fill(self, *replies):
        scraper = AccountlessScraper(should_stop=lambda: server.state.running, max_retries=0)
        with patch("requests.Session.get", side_effect=list(replies)) as get:
            done = details.fill_one(server, scraper)
        return done, get.call_count

    def test_filler_completes_pending_job_and_reclassifies(self):
        self.deferred()
        with self.factory() as session:
            self.assertEqual(details.pending_count(session), 1)
        self.assertEqual(self.fill(response(DETAIL)), (True, 1))
        job, raw = self.job()
        self.assertIn("PyTorch", job.description)
        self.assertNotIn("detail_pending", raw)
        self.assertIn("pytorch", [t.lower() for t in json.loads(job.tags)])
        self.assertEqual(self.fill(), (False, 0))  # bekleyen kalmadı

    def test_removed_posting_stops_waiting(self):
        self.deferred()
        self.fill(response(status=404))
        job, raw = self.job()
        self.assertTrue(raw["detail_missing"])
        self.assertNotIn("detail_pending", raw)

    def test_unparseable_detail_gives_up_after_max_attempts(self):
        self.deferred()
        for _ in range(details.MAX_ATTEMPTS):
            self.fill(response("<html><body>boş</body></html>"))
        job, raw = self.job()
        self.assertTrue(raw["detail_failed"])
        with self.factory() as session:
            self.assertEqual(details.pending_count(session), 0)

    def test_filler_yields_to_scans_and_source_pauses(self):
        self.deferred()
        with patch.object(server.state, "running", True):
            self.assertEqual(self.fill(), (False, 0))
        Coordinator().pause("Kaynak erişimi sınırlandırdı (HTTP 429).", 429, "600")
        self.assertEqual(self.fill(), (False, 0))
        with self.factory() as session:
            self.assertEqual(details.pending_count(session), 1)

    def test_rate_limit_during_fill_pauses_source_without_counting_attempt(self):
        self.deferred()
        self.assertEqual(self.fill(response(status=429, **{"Retry-After": "120"})), (False, 1))
        self.assertTrue(Coordinator().state()["paused"])
        job, raw = self.job()
        self.assertTrue(raw["detail_pending"])
        self.assertNotIn("detail_attempts", raw)

    def test_pending_job_skips_llm_until_description_arrives(self):
        events = []
        reply = {"summary": "PyTorch ile model geliştirme.", "tags": ["pytorch"]}
        with patch.object(config, "GROQ_API_KEY", "test"),              patch.object(groq_client, "chat_json", return_value=reply) as chat:
            with patch("requests.Session.get", side_effect=[response(card(1)), response("")]):
                pipeline.run_scrape(["AI"], ["Istanbul"], classify_backend="groq", search_options=DEFER,
                                    emit=lambda kind, data: events.append((kind, data)))
            chat.assert_not_called()  # açıklama yokken Groq kotası harcanmaz
            job, raw = self.job()
            self.assertEqual(job.classified_by, "rules")
            result = next(d for k, d in events if k == "processing_result")
            self.assertFalse(result["classification_fallback"])
            self.assertTrue(result["deferred_llm"])
            stage = next(d for k, d in events if k == "processing_stage" and d.get("stage") == "classify" and d["phase"] == "finished")
            self.assertFalse(stage["classification_fallback"])
            with self.factory() as session:
                self.assertEqual(audit.report(session, raw["run_id"])["metrics"]["model_fallbacks"], 0)
            self.assertEqual(self.fill(response(DETAIL)), (True, 1))
            chat.assert_called_once()  # açıklama gelince koşunun arka ucuyla yeniden sınıflanır
            self.assertIn("PyTorch", chat.call_args[0][0][1]["content"])
        job, raw = self.job()
        self.assertEqual(job.classified_by, "groq")
        self.assertEqual(job.summary, "PyTorch ile model geliştirme.")

    def test_llm_still_used_when_description_present(self):
        with patch.object(config, "GROQ_API_KEY", "test"),              patch.object(groq_client, "chat_json", return_value={"tags": ["pytorch"]}) as chat,              patch("requests.Session.get", side_effect=[response(card(1)), response(DETAIL), response("")]):
            pipeline.run_scrape(["AI"], ["Istanbul"], classify_backend="groq")
        chat.assert_called_once()
        self.assertEqual(self.job()[0].classified_by, "groq")

    def events(self, run_id):
        with self.factory() as session:
            return [(e.kind, e.level, json.loads(e.data)) for e in
                    session.query(SearchEvent).filter_by(run_id=run_id).order_by(SearchEvent.id)]

    def filler_events(self, run_id):
        return [e for e in self.events(run_id) if e[2].get("source") == "detail_filler"]

    def test_filler_requests_are_recorded_on_the_jobs_run(self):
        self.deferred()
        run_id = self.job()[1]["run_id"]
        self.assertTrue(run_id)
        self.fill(response(DETAIL))
        events = self.filler_events(run_id)
        self.assertEqual([e[0] for e in events], ["request_started", "request_finished", "detail_filled"])
        self.assertEqual(events[1][2]["status"], 200)
        self.assertEqual(events[0][2]["search_id"], self.job()[1]["search_id"])
        with self.factory() as session:
            metrics = audit.report(session, run_id)["metrics"]
        self.assertEqual((metrics["detail_requests"], metrics["rate_429"]), (1, 0.0))

    def test_rate_limit_during_fill_records_source_pause(self):
        self.deferred()
        run_id = self.job()[1]["run_id"]
        with self.assertLogs("linko.audit", "WARNING") as logs:
            self.fill(response(status=429, **{"Retry-After": "120"}))
        events = self.filler_events(run_id)
        self.assertEqual([e[0] for e in events], ["request_started", "request_finished", "source_paused"])
        kind, level, data = events[-1]
        self.assertEqual((level, data["status_code"]), ("warning", 429))
        self.assertGreater(data["remaining_seconds"], 0)
        self.assertTrue(data["reason"])
        self.assertTrue(any("source_paused" in line for line in logs.output))
        with self.factory() as session:
            metrics = audit.report(session, run_id)["metrics"]
        # 2 arama sayfası (200) + 1 detay isteği (429)
        self.assertEqual((metrics["detail_requests"], metrics["rate_429"], metrics["source_pauses"]), (1, 0.3333, 1))
        self.assertEqual(metrics["pause_seconds"], 0)  # tamamlayıcı beklemesi koşunun donma oranına girmez

    def test_job_without_run_uses_system_run_id(self):
        self.deferred()
        with self.factory() as session:
            job = session.query(Job).one()
            raw = json.loads(job.raw)
            raw.pop("run_id"), raw.pop("search_id")
            job.raw = json.dumps(raw)
            session.commit()
        self.fill(response(status=404))
        self.assertEqual([e[0] for e in self.events(details.SYSTEM_RUN)],
                         ["request_started", "request_finished", "detail_missing"])
        self.assertEqual(self.client.get("/api/runs").status_code, 200)


if __name__ == "__main__":
    unittest.main()
