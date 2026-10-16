"""Full Light job board regression tests using temporary data and mocked HTTP."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from jobapp import config, db, embed, pipeline, server
from jobapp.models import Job
from jobapp.scraper.accountless import AccountlessScraper


def response(html="", status=200, **headers):
    r = requests.Response()
    r.status_code = status
    r._content = html.encode("utf-8")
    r._content_consumed = True
    r.encoding = "utf-8"
    r.headers.update(headers)
    return r


def card(i):
    return f'''<div class="base-search-card" data-entity-urn="urn:li:jobPosting:{i}">
    <h3 class="base-search-card__title">AI Engineer</h3>
    <h4 class="base-search-card__subtitle">Örnek Şirket</h4>
    <span class="job-search-card__location">Istanbul, Turkey (Remote)</span></div>'''


DETAIL = '<div class="show-more-less-html__markup">Python, PyTorch. En az 3 yıl deneyim.</div>'


class FullLightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = create_engine("sqlite:///" + str(Path(self.tmp.name) / "jobs.db"))
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine)
        for item in (patch.object(db, "engine", self.engine),
                     patch.object(pipeline, "SessionLocal", self.factory),
                     patch.object(server, "SessionLocal", self.factory),
                     patch.object(config, "ACCOUNTLESS_OUTPUT_DIR", str(Path(self.tmp.name) / "searches")),
                     patch.object(AccountlessScraper, "REQUEST_INTERVAL", 0),
                     patch.object(config, "MIN_REQUEST_INTERVAL", 0),
                     patch.object(server.state, "running", False)):
            item.start()
            self.addCleanup(item.stop)
        self.client = server.create_app().test_client()

    def scrape(self, replies, limit=None):
        events = []
        with patch("requests.Session.get", side_effect=replies) as get:
            result = pipeline.run_scrape(["AI Engineer"], ["Istanbul"], limit=limit,
                                        emit=lambda t, d: events.append((t, d)))
        return result, events, get

    def test_full_ui_retained_without_login_option(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Linko Scrapper Light", html)
        self.assertIn("classify-backend", html)
        self.assertIn("use-embeddings", html)
        self.assertIn("Limitsiz", html)
        self.assertNotIn('id="require-login"', html)
        self.assertNotIn("_kill_stray_chrome", vars(server))
        routes = {rule.rule for rule in server.app.url_map.iter_rules()}
        for route in ("/api/jobs", "/api/facets", "/api/profile", "/api/embed",
                      "/api/classify", "/api/ollama/models", "/api/jobs/<int:job_id>/similar", "/events"):
            self.assertIn(route, routes)

    def test_ten_jobs_database_and_json(self):
        replies = [response("".join(card(i) for i in range(20)))]
        replies.extend(response(DETAIL) for _ in range(10))
        result, events, get = self.scrape(replies, 10)
        self.assertEqual(result["new"], 10)
        self.assertEqual(get.call_count, 11)
        self.assertEqual(events[-1][0], "finished")
        folder = Path(result["output_folders"][0])
        files = list((folder / "ilan_havuzu").glob("*.json"))
        self.assertEqual(len(files), 10)
        job = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(job["company"], "Örnek Şirket")
        self.assertEqual(job["type"], "Remote")
        self.assertEqual(job["experience"], "3+ yıl")
        self.assertIn("Python", job["skills"])
        with self.factory() as session:
            self.assertEqual(session.query(Job).count(), 10)
        self.assertEqual(self.client.get("/api/jobs").status_code, 200)
        self.assertEqual(self.client.get("/api/facets").status_code, 200)

    def test_profile_and_embedding_features(self):
        with patch.object(embed, "embed_text", return_value=[1.0, 0.0]):
            result = self.client.post("/api/profile", json={"text": "Python AI engineer"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get("/api/profile").json["text"], "Python AI engineer")

    def test_authenticated_api_and_pipeline_rejected(self):
        self.assertEqual(self.client.post("/api/scrape", json={
            "keywords": ["AI"], "require_login": True}).status_code, 400)
        with self.assertRaisesRegex(ValueError, "accountless"):
            pipeline.run_scrape(["AI"], ["Istanbul"], require_login=True)
        self.assertNotIn("selenium", sys.modules)
        self.assertNotIn("undetected_chromedriver", sys.modules)

    def test_block_keeps_partial_output(self):
        result, events, get = self.scrape([response(card(1) + card(2)), response(DETAIL), response(status=429)])
        self.assertEqual(result["new"], 1)
        self.assertEqual(events[-1][0], "source_paused")
        folder = next((Path(self.tmp.name) / "searches").iterdir())
        self.assertTrue((folder / "ilan_havuzu/ap-linkedin-1.json").is_file())
        self.assertEqual(json.loads((folder / "search.json").read_text())["status"], "paused")
        self.assertEqual(get.call_count, 3)

    def test_unlimited_exceeds_old_limits(self):
        replies = []
        for page in range(11):
            replies.append(response("".join(card(page * 10 + i) for i in range(10))))
            replies.extend(response(DETAIL) for _ in range(10))
        replies.append(response(card(0)))
        result, events, get = self.scrape(replies)
        self.assertEqual(result["new"], 110)
        self.assertEqual(get.call_count, 122)
        self.assertEqual(events[-1][0], "finished")

    def test_optional_login_form_and_real_challenge(self):
        result, _, _ = self.scrape([response(card(1)), response(
            DETAIL + '<form action="/uas/login-submit"><input name="session_password"></form>')], 1)
        self.assertEqual(result["new"], 1)
        _, events, get = self.scrape([response(status=302, Location="/authwall")])
        self.assertEqual(events[-1][0], "source_paused")
        self.assertEqual(get.call_count, 1)

    def test_repeated_search_folders_and_database_dedup(self):
        a, _, _ = self.scrape([response(card(1)), response(DETAIL)], 1)
        b, _, _ = self.scrape([response(card(1)), response(DETAIL)], 1)
        self.assertNotEqual(a["output_folders"], b["output_folders"])
        self.assertEqual(b["unchanged"], 1)

    def test_portable_without_main_project(self):
        root = Path(__file__).resolve().parent.parent
        target = Path(self.tmp.name) / "portable"
        shutil.copytree(root / "jobapp", target / "jobapp",
                        ignore=shutil.ignore_patterns("__pycache__", "*.db", "*.db-*"))
        shutil.copy2(root / "run_accountless.py", target / "run_accountless.py")
        completed = subprocess.run([sys.executable, "run_accountless.py", "--help"], cwd=target,
                                   capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        script = (
            "from jobapp.server import create_app; from jobapp import config; import sys; "
            "a=create_app(); assert a.test_client().get('/').status_code==200; "
            "assert not hasattr(config,'CHROME_PROFILE_DIR'); "
            "assert 'undetected_chromedriver' not in sys.modules"
        )
        completed = subprocess.run([sys.executable, "-c", script], cwd=target,
                                   capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_search_log_and_termination_reason_recorded(self):
        replies = [response(card(101)), response(DETAIL)]
        result, events, get = self.scrape(replies, limit=1)
        self.assertEqual(result["new"], 1)
        folder = Path(result["output_folders"][0])

        # Verify search.json metadata
        meta = json.loads((folder / "search.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "finished")
        self.assertEqual(meta["count"], 1)
        self.assertIn("terminationReason", meta)
        self.assertIn("terminationMessage", meta)
        self.assertIn("stats", meta)
        self.assertEqual(meta["stats"]["savedCount"], 1)

        # Verify search.log existence and content
        log_file = folder / "search.log"
        self.assertTrue(log_file.is_file())
        log_text = log_file.read_text(encoding="utf-8")
        self.assertIn("LINKEDIN PUBLIC ARAMA DETAY LOGU", log_text)
        self.assertIn("ARAMA TAMAMLANDI", log_text)

        # Verify API endpoints
        searches_resp = self.client.get("/api/searches").json
        self.assertTrue(any(s["folder"] == folder.name and s["hasLog"] for s in searches_resp["searches"]))

        log_resp = self.client.get(f"/api/searches/{folder.name}/log")
        self.assertEqual(log_resp.status_code, 200)
        self.assertIn("LINKEDIN", log_resp.json["log"])

    def test_package_queue_with_distinct_locations(self):
        keywords = [
            {"keyword": "AI Engineer", "location": "Istanbul, Turkey", "limit": 1},
            {"keyword": "Backend Developer", "location": "Germany", "limit": 1},
        ]
        replies = [
            response(card(201)), response(DETAIL),
            response(card(202)), response(DETAIL),
        ]
        with patch("requests.Session.get", side_effect=replies):
            result = pipeline.run_scrape(keywords, locations=["Default"], limit=1)

        self.assertEqual(result["new"], 2)
        self.assertEqual(len(result["output_folders"]), 2)
        self.assertIn("Istanbul", result["output_folders"][0])
        self.assertIn("Germany", result["output_folders"][1])


if __name__ == "__main__":
    unittest.main()
