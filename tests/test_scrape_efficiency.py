"""Request budgets, saved result deletion, refresh queues and variable page sizes."""
import json
import unittest
from unittest.mock import patch

import test_light
from test_light import card, response, DETAIL
from jobapp import config, details, pipeline, server
from jobapp.models import DetailCache, Job, SearchEvent, SearchRun, TaskJob
from jobapp.scraper.accountless import AccountlessScraper
from jobapp.transport import Details


class ScrapeEfficiencyTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp

    def scan(self, html, **options):
        with patch("requests.Session.get", side_effect=[response(html)]) as get:
            result = pipeline.run_scrape(["Python Developer"], ["Istanbul"], limit=2,
                search_options={"defer_details": True}, **options)
        return result, get.call_count

    def fill(self, *responses):
        scraper = AccountlessScraper(max_retries=0)
        try:
            with patch("requests.Session.get", side_effect=list(responses)) as get:
                while details.fill_one(server, scraper):
                    pass
            return get.call_count
        finally:
            scraper.session.close()

    def test_delete_results_repeat_search_keeps_cache_and_history(self):
        self.assertEqual(self.scan(card(1) + card(2))[1], 1)
        self.assertEqual(self.fill(response(DETAIL), response(DETAIL)), 2)
        with self.factory() as session:
            ids = [j.id for j in session.query(Job).all()]
            events_before = session.query(SearchEvent).count()
            self.assertEqual(session.query(DetailCache).count(), 2)
        deleted = self.client.post("/api/trash/jobs", json={"ids": ids, "action": "delete"})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/jobs").json["total"], 0)
        repeated, requests = self.scan(card(1) + card(2))
        self.assertEqual(requests, 1)
        self.assertEqual(repeated["unchanged"], 2)
        self.assertEqual(self.fill(), 0)
        with self.factory() as session:
            self.assertEqual(session.query(Job).count(), 2)
            self.assertEqual(session.query(Job).filter(Job.deleted_at.isnot(None)).count(), 2)
            self.assertEqual(session.query(DetailCache).count(), 2)
            self.assertEqual(session.query(SearchRun).count(), 2)
            self.assertEqual(session.query(TaskJob).count(), 4)
            self.assertGreater(session.query(SearchEvent).count(), events_before)

    def test_overlapping_searches_queue_one_detail_per_id(self):
        with patch("requests.Session.get", side_effect=[response(card(1) + card(2)), response(card(2) + card(3))]) as get:
            pipeline.run_scrape(["Python", "Backend"], ["Istanbul"], limit=2, search_options={"defer_details": True})
        self.assertEqual(get.call_count, 2)
        with self.factory() as session:
            self.assertEqual(session.query(Job).count(), 3)
            self.assertEqual(session.query(TaskJob).count(), 4)
            self.assertEqual(details.pending_count(session), 3)
        self.assertEqual(self.fill(response(DETAIL), response(DETAIL), response(DETAIL)), 3)

    def test_changed_card_is_deferred_and_old_description_remains(self):
        self.scan(card(1) + card(2))
        self.fill(response(DETAIL), response(DETAIL))
        changed = card(1).replace("AI Engineer", "Senior AI Engineer") + card(2)
        self.assertEqual(self.scan(changed)[1], 1)
        with self.factory() as session:
            job = session.query(Job).filter_by(external_id="1").one()
            self.assertIn("PyTorch", job.description)
            self.assertTrue(json.loads(job.raw)["detail_pending"])
            self.assertEqual(details.pending_count(session), 1)
        self.assertEqual(self.fill(response(DETAIL.replace("PyTorch", "SQL"))), 1)
        with self.factory() as session:
            job = session.query(Job).filter_by(external_id="1").one()
            self.assertIn("SQL", job.description)
            self.assertNotIn("detail_pending", json.loads(job.raw))

    def test_filler_uses_cache_populated_after_discovery(self):
        self.scan(card(1) + card(2))
        with self.factory() as session:
            raws = [json.loads(j.raw) for j in session.query(Job).all()]
        for raw in raws:
            Details().put(raw, "Already fetched Python description")
        self.assertEqual(self.fill(), 0)
        with self.factory() as session:
            self.assertEqual(details.pending_count(session), 0)
            self.assertTrue(all("Already fetched" in j.description for j in session.query(Job).all()))

    def test_pending_old_description_cannot_seed_a_fresh_cache(self):
        self.scan(card(1) + card(2))
        self.fill(response(DETAIL), response(DETAIL))
        self.scan(card(1).replace("AI Engineer", "Senior AI Engineer") + card(2))
        with self.factory() as session:
            raw = json.loads(session.query(Job).filter_by(external_id="1").one().raw)
            session.query(DetailCache).filter_by(external_id="1").delete()
            session.commit()
        self.assertIsNone(Details().get(raw, allow_stale=True))
        self.assertEqual(self.fill(response(DETAIL)), 1)

    def test_negative_cache_expires_even_with_stale_positive_reuse(self):
        raw = {"external_id": "gone", "card_lines": ["Title", "Company", "City"]}
        Details(clock=lambda: 100).put(raw, "", 404)
        clock = lambda: 100 + config.DETAIL_MISSING_TTL_SECONDS + 1
        self.assertIsNone(Details(clock=clock).get(raw, allow_stale=True))

    def test_page_offset_uses_all_returned_slots_including_duplicate_and_invalid(self):
        first = "".join(card(i) for i in range(23)) + card(0) + '<div class="base-search-card"></div>'
        with patch("requests.Session.get", side_effect=[response(first), response(card(23) + card(24)), response("")]) as get:
            result = pipeline.run_scrape(["Python"], ["Istanbul"], search_options={"defer_details": True})
        self.assertEqual([call.kwargs["params"]["start"] for call in get.call_args_list], [0, 25, 27])
        self.assertEqual(result["new"], 25)

    def test_resume_uses_recorded_offset_and_supports_old_checkpoints(self):
        for checkpoint, expected in (({"page": 1, "offset": 25}, 25), ({"page": 2}, 20)):
            with self.subTest(checkpoint=checkpoint), patch("requests.Session.get", return_value=response("")) as get:
                pipeline.run_scrape(["Python"], ["Istanbul"], checkpoint=checkpoint,
                                    search_options={"defer_details": True})
                self.assertEqual(get.call_args.kwargs["params"]["start"], expected)

    def test_abnormal_card_drop_logs_warning_without_interrupting(self):
        logs = []
        scraper = AccountlessScraper(emit=lambda kind, data: logs.append((kind, data)) if kind == "log" else None,
                                     max_retries=0, search_options={"defer_details": True})
        page1 = "".join(card(i) for i in range(10))
        page2 = card(10) + card(11)  # only 2 cards (less than 50% of 10)
        try:
            with patch("requests.Session.get", side_effect=[response(page1), response(page2), response("")]):
                scraper.scrape([{"keyword": "Python", "limit": 100}], ["Istanbul"], lambda job: "new")
            warnings = [d["msg"] for k, d in logs if d.get("level") == "warning"]
            self.assertTrue(any("Kart sayısında beklenmeyen düşüş" in w for w in warnings))
        finally:
            scraper.session.close()

    def test_low_yield_threshold_stops_pagination_early_and_records_reason(self):
        # Seed 9 known jobs in DB (ids 0 to 8)
        with self.factory() as session:
            for i in range(9):
                session.add(Job(source=config.SOURCE_LINKEDIN, external_id=str(i),
                                url=f"https://www.linkedin.com/jobs/view/{i}",
                                title="AI Engineer", company="Test Corp", location="Istanbul",
                                description="Existing job description"))
            session.commit()

        events = []
        page1 = "".join(card(i) for i in range(10))  # 9 known, 1 new (id 9) -> 10% new (< 20%)
        page2 = "".join(card(i) for i in range(10, 20))
        scraper = AccountlessScraper(emit=lambda kind, data: events.append((kind, data)),
                                     max_retries=0,
                                     search_options={"defer_details": True, "stop_when_known": True, "low_yield_threshold": 0.20})
        try:
            with patch("requests.Session.get", side_effect=[response(page1), response(page2)]) as get:
                collected, reason, stats = scraper._search("Python", "Istanbul", 50, lambda job: "new")
            # Should stop after page 1; page 2 is never requested
            self.assertEqual(get.call_count, 1)
            self.assertEqual(reason, "low_yield_threshold")
            self.assertEqual(stats["termination_reason"], "low_yield_threshold")
            self.assertTrue(stats["low_yield_stopped"])
            self.assertEqual(collected, 10)
            # Verify event or log mentions threshold stopping
            log_messages = [d.get("msg", "") for k, d in events if k == "log"]
            self.assertTrue(any("Yeni ilan verimi eşik altına düştü" in m for m in log_messages))
        finally:
            scraper.session.close()


if __name__ == "__main__":
    unittest.main()
