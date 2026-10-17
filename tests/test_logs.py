"""Sunucu log deposu, log/hata kaydı API'si ve GitHub issue senkronu."""
import json
import logging
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import test_light
from jobapp import config, logstore, maintenance
from jobapp.models import AppLog, Incident

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import incident_sync  # noqa: E402

ADMIN = {"Authorization": "Bearer admin"}


class LogTests(unittest.TestCase):
    setUp_light = test_light.FullLightTests.setUp

    def setUp(self):
        self.setUp_light()
        for item in (patch.object(config, "ADMIN_KEY", "admin"), patch.object(config, "API_KEY", "reader")):
            item.start()
            self.addCleanup(item.stop)

    def test_handler_persists_records_and_groups_errors_into_incident(self):
        logger = logging.getLogger("linko.test")
        handler = logstore.DatabaseHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        logger.warning("Kaynak beklemesi 900 sn")
        try:
            raise RuntimeError("bozuk")
        except RuntimeError:
            logger.exception("Görev 12 başarısız run=abcdef1234")
        logger.error("Görev 57 başarısız run=0123456789")
        with self.factory() as session:
            self.assertEqual(session.query(AppLog).count(), 3)
            incident = session.query(Incident).one()
            self.assertEqual((incident.count, incident.status), (2, "open"))
            self.assertIn("RuntimeError: bozuk", incident.traceback)

    def test_resolved_incident_reopens_and_keeps_history(self):
        logstore.store("error", "linko.x", "Patladı 1")
        with self.factory() as session:
            logstore.resolve(session.query(Incident).one(), "düzeltildi", 4)
            session.commit()
        logstore.store("error", "linko.x", "Patladı 2")
        with self.factory() as session:
            incident = session.query(Incident).one()
            self.assertEqual((incident.status, incident.reopen_count, incident.count), ("open", 1, 2))
            self.assertEqual([h["event"] for h in json.loads(incident.history)], ["opened", "resolved", "reopened"])

    def test_logs_api_requires_admin_and_filters(self):
        old = datetime.utcnow() - timedelta(hours=5)
        logstore.store("info", "linko", "eski satır", created_at=old)
        logstore.store("warning", "linko.audit", "source_paused HTTP 429")
        logstore.store("error", "linko.service", "Collector supervisor failed")
        self.assertEqual(self.client.get("/api/v1/logs").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/logs", headers={"Authorization": "Bearer reader"}).status_code, 403)
        items = self.client.get("/api/v1/logs?since=1h", headers=ADMIN).json["items"]
        self.assertEqual([i["message"] for i in items], ["source_paused HTTP 429", "Collector supervisor failed"])
        items = self.client.get("/api/v1/logs?level=error", headers=ADMIN).json["items"]
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["incident_id"])
        self.assertEqual(len(self.client.get("/api/v1/logs?q=429", headers=ADMIN).json["items"]), 1)
        page = self.client.get("/api/v1/logs?limit=1&order=desc", headers=ADMIN).json
        self.assertTrue(page["has_more"])
        self.assertEqual(page["items"][0]["message"], "Collector supervisor failed")
        self.assertEqual(self.client.get("/api/v1/logs?since=dün", headers=ADMIN).status_code, 400)

    def test_export_streams_range_as_ndjson(self):
        logstore.store("info", "linko", "eski", created_at=datetime(2026, 1, 1, 12))
        logstore.store("info", "linko", "aralıkta", created_at=datetime(2026, 1, 2, 12))
        self.assertEqual(self.client.get("/api/v1/logs/export", headers=ADMIN).status_code, 400)
        reply = self.client.get("/api/v1/logs/export?since=2026-01-02T00:00:00Z&until=2026-01-03T00:00:00%2B00:00", headers=ADMIN)
        self.assertEqual(reply.status_code, 200)
        self.assertIn("attachment", reply.headers["Content-Disposition"])
        rows = [json.loads(x) for x in reply.get_data(as_text=True).splitlines()]
        self.assertEqual([r["message"] for r in rows], ["aralıkta"])
        self.assertEqual(self.client.get("/api/v1/logs/export?since=2026-01-01T00:00:00Z&until=2026-03-01T00:00:00Z", headers=ADMIN).status_code, 400)

    def test_maintenance_prunes_logs_but_never_incidents(self):
        logstore.store("error", "linko", "eski hata", created_at=datetime.utcnow() - timedelta(days=400))
        with self.factory() as session:
            result = maintenance.run(session)
            self.assertEqual(result["app_logs_deleted"], 1)
            self.assertEqual(session.query(Incident).count(), 1)

    def test_incident_api_link_and_resolve(self):
        logstore.store("error", "linko", "Patladı")
        ident = self.client.get("/api/v1/incidents?needs_issue=1", headers=ADMIN).json["items"][0]["id"]
        reply = self.client.post(f"/api/v1/incidents/{ident}", headers=ADMIN, json={"action": "link", "issue_number": 9})
        self.assertEqual(reply.json["issue_state"], "open")
        self.assertEqual(self.client.get("/api/v1/incidents?needs_issue=1", headers=ADMIN).json["items"], [])
        self.client.post(f"/api/v1/incidents/{ident}", headers=ADMIN, json={"action": "resolve", "resolution": "ok"})
        self.assertEqual(self.client.get("/api/v1/incidents", headers=ADMIN).json["items"], [])
        detail = self.client.get(f"/api/v1/incidents/{ident}", headers=ADMIN).json
        self.assertEqual(detail["status"], "resolved")
        self.assertEqual(len(detail["recent_logs"]), 1)


class SyncTests(unittest.TestCase):
    def fake(self, incidents, issues):
        calls = []
        def http(method, url, token, body=None):
            calls.append((method, url.split(".com")[-1] if "github" in url else url.split("site")[-1], body))
            if "/api/v1/incidents?" in url:
                wanted = [i for i in incidents if i["status"] == "open"]
                if "needs_issue=1" in url:
                    wanted = [i for i in wanted if not i["issue_number"] or i["issue_state"] != "open"]
                return {"items": wanted}
            if "/api/v1/incidents/" in url:
                incident = next(i for i in incidents if url.endswith("/" + str(i["id"])))
                if body["action"] == "link":
                    incident.update(issue_number=body["issue_number"], issue_state="open")
                else:
                    incident.update(status="resolved", issue_state="closed")
                return incident
            if method == "POST" and url.endswith("/issues"):
                return {"number": 77}
            if method == "GET" and "/issues/" in url:
                return issues[int(url.rsplit("/", 1)[1])]
            return {}
        return http, calls

    def incident(self, **extra):
        return dict(dict(id=1, status="open", issue_number=None, issue_state="", count=3, logger="linko", title="[linko] Patladı",
                         sample="Patladı", first_seen="2026-10-17T00:00:00Z", last_seen="2026-10-17T01:00:00Z"), **extra)

    def test_new_incident_opens_issue_with_marker(self):
        incidents = [self.incident()]
        http, calls = self.fake(incidents, {})
        incident_sync.Sync("https://site", "k", "o/r", "t", http).run()
        created = next(c for c in calls if c[0] == "POST" and c[1].endswith("/issues"))
        self.assertIn("<!-- linko-incident:1 -->", created[2]["body"])
        self.assertEqual(created[2]["labels"], ["hata-kaydı"])
        self.assertEqual(incidents[0]["issue_number"], 77)

    def test_closed_issue_resolves_unless_seen_again(self):
        incidents = [self.incident(issue_number=5, issue_state="open")]
        http, calls = self.fake(incidents, {5: {"number": 5, "state": "closed", "closed_at": "2026-10-17T02:00:00Z"}})
        incident_sync.Sync("https://site", "k", "o/r", "t", http).run()
        self.assertEqual(incidents[0]["status"], "resolved")
        self.assertTrue(any("Çözüldü" in (c[2] or {}).get("body", "") for c in calls))

        incidents = [self.incident(issue_number=5, issue_state="open", last_seen="2026-10-17T03:00:00Z")]
        http, calls = self.fake(incidents, {5: {"number": 5, "state": "closed", "closed_at": "2026-10-17T02:00:00Z"}})
        incident_sync.Sync("https://site", "k", "o/r", "t", http).run()
        self.assertEqual(incidents[0]["status"], "open")
        self.assertIn(("PATCH", "/repos/o/r/issues/5", {"state": "open"}), calls)

    def test_reopened_incident_reopens_existing_issue(self):
        incidents = [self.incident(issue_number=5, issue_state="closed")]
        http, calls = self.fake(incidents, {})
        incident_sync.Sync("https://site", "k", "o/r", "t", http).run()
        self.assertIn(("PATCH", "/repos/o/r/issues/5", {"state": "open"}), calls)
        self.assertEqual(incidents[0]["issue_state"], "open")
        self.assertFalse(any(c[0] == "POST" and c[1].endswith("/issues") for c in calls))


if __name__ == "__main__":
    unittest.main()
