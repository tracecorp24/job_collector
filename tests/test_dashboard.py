"""Panel sekmesi: /api/dashboard ölçümleri, kapsamı ve arayüz bağlantıları."""
import json
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import test_light
from jobapp import dashboard
from jobapp.models import Job, SearchRun, SearchTask, TaskJob, Watch

ROOT = Path(__file__).resolve().parent.parent


class DashboardTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp

    def seed(self):
        now = datetime.utcnow()
        with self.factory() as session:
            session.add_all([
                Job(source="linkedin", external_id="a", title="Python", company="Örnek", location="Istanbul", workplace_type="Remote",
                    seniority="Senior", tags='["Python", "SQL"]', profession_groups='["Yazılım"]', salary="100000 TRY aylık",
                    salary_min=100000, salary_max=120000, salary_currency="TRY", salary_period="month", description="x", summary="s",
                    embedding="[0.1]", classified_by="groq", created_at=now - timedelta(hours=2), posted_at=now - timedelta(hours=5)),
                Job(source="linkedin", external_id="b", title="Dev", company="Örnek", location="Istanbul", workplace_type="Hybrid",
                    seniority="Unknown", tags='["python", "Java"]', profession_groups='["Yazılım", "Veri"]', flag="scam",
                    created_at=now - timedelta(days=3), posted_at=now - timedelta(days=20)),
                Job(source="linkedin", external_id="c", title="Eski", company="Diğer", location="Ankara", workplace_type="",
                    seniority="Mid", tags="bozuk-json", created_at=now - timedelta(days=10)),
                Job(source="linkedin", external_id="d", title="Çöpte", company="Gizli", location="Berlin", workplace_type="Remote",
                    tags='["Gizli"]', created_at=now, deleted_at=now),
                Job(source="linkedin", external_id="e", title="Geçersiz", company="Bozuk", location="Berlin", quality_ok=False,
                    tags='["Bozuk"]', created_at=now),
            ])
            session.add(Watch(id="w1", name="A", keywords='["x"]', locations='["y"]', enabled=True, next_due_at=time.time() + 600))
            session.add(Watch(id="w2", name="B", keywords='["x"]', locations='["y"]', enabled=False, next_due_at=time.time() + 60))
            session.add(SearchRun(id="r1", status="finished", options='{"kind":"scrape"}', created_at=now - timedelta(hours=1)))
            session.add(SearchTask(id="t1", run_id="r1", keyword="x", location="y", status="finished"))
            session.add(SearchRun(id="r2", status="finished", options='{"kind":"classify"}', created_at=now))
            session.flush()
            job = session.query(Job).filter_by(external_id="a").one()
            session.add(TaskJob(task_id="t1", job_id=job.id, is_new=True, outcome="new"))
            session.commit()

    def get(self):
        dashboard._cache.update(at=0.0, data=None, owner=None)
        result = self.client.get("/api/dashboard")
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def test_empty_database_returns_zeroes_without_errors(self):
        data = self.get()
        self.assertEqual(data["totals"]["total"], 0)
        self.assertEqual(data["hourly"], [])
        self.assertEqual(data["skills"], [])
        self.assertEqual(data["collector"]["runs"], [])
        self.assertEqual(sum(row["count"] for row in data["posted_age"]), 0)

    def test_counts_skip_trash_and_invalid_rows(self):
        self.seed()
        data = self.get()
        totals = data["totals"]
        self.assertEqual((totals["total"], totals["trash"], totals["invalid"]), (3, 1, 1))
        self.assertEqual((totals["created_24h"], totals["created_7d"], totals["created_prev_7d"]), (1, 2, 1))
        self.assertEqual((totals["remote"], totals["hybrid"], totals["flagged"], totals["with_salary"]), (1, 1, 1, 1))
        self.assertEqual((totals["with_description"], totals["with_summary"], totals["with_embedding"], totals["companies"]), (1, 1, 1, 2))

    def test_distributions(self):
        self.seed()
        data = self.get()
        skills = {row["value"].lower(): row["count"] for row in data["skills"]}
        self.assertEqual(skills, {"python": 2, "sql": 1, "java": 1})
        self.assertNotIn("gizli", skills)
        self.assertEqual({r["value"]: r["count"] for r in data["professions"]}, {"Yazılım": 2, "Veri": 1, "Genel Meslekler": 1})
        self.assertEqual({r["value"]: r["count"] for r in data["workplace"]}, {"Remote": 1, "Hybrid": 1, "__missing__": 1})
        self.assertEqual({r["value"]: r["count"] for r in data["seniority"]}, {"Senior": 1, "Mid": 1, "__missing__": 1})
        self.assertEqual(data["companies"][0], {"value": "Örnek", "count": 2})
        ages = {row["key"]: row["count"] for row in data["posted_age"]}
        self.assertEqual((ages["1"], ages["30"], ages["unknown"]), (1, 1, 1))
        self.assertEqual(sum(n for _, n in data["hourly"]), 3)
        self.assertEqual(data["salary"], [dict(currency="TRY", period="month", count=1, p25=110000, median=110000, p75=110000, min=110000, max=110000)])

    def test_collector_ignores_maintenance_runs_and_reports_watches(self):
        self.seed()
        collector = self.get()["collector"]
        self.assertEqual([r["id"] for r in collector["runs"]], ["r1"])
        self.assertEqual((collector["runs"][0]["new"], collector["runs"][0]["tasks"]), (1, 1))
        self.assertEqual(collector["run_statuses"], {"finished": 1})
        self.assertEqual((collector["watches"]["total"], collector["watches"]["enabled"]), (2, 1))
        self.assertGreater(collector["watches"]["next_due_at"], time.time() + 300)  # yalnızca etkin alarm sayılır
        self.assertFalse(collector["source"]["paused"])

    def test_response_is_cached_briefly_and_refresh_has_a_floor(self):
        self.seed()
        self.get()
        with self.factory() as session:
            session.query(Job).delete()
            session.commit()
        self.assertEqual(self.client.get("/api/dashboard").json["totals"]["total"], 3)
        self.assertEqual(self.client.get("/api/dashboard?refresh=1").json["totals"]["total"], 3)  # alt sınırdan genç önbellek
        dashboard._cache["at"] -= dashboard.MIN_REFRESH_SECONDS + 1
        self.assertEqual(self.client.get("/api/dashboard?refresh=1").json["totals"]["total"], 0)

    def test_page_exposes_the_tab_next_to_listings(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="view-dashboard"', html)
        nav = html[html.index('aria-label="Ana menü"'):]
        self.assertLess(nav.index('data-tab="jobs"'), nav.index('data-tab="dashboard"'))
        self.assertLess(nav.index('data-tab="dashboard"'), nav.index('data-tab="watches"'))
        script = (ROOT / "jobapp/static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("const TABS=['jobs','dashboard',", script)


if __name__ == "__main__":
    unittest.main()
