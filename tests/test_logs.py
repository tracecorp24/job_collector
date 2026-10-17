"""Sunucu log deposu, log/hata kaydı API'si ve GitHub issue senkronu."""
import json
import logging
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import test_light
from jobapp import config, logstore, maintenance
from jobapp.models import AppLog, Incident


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

    def test_log_key_opens_only_log_and_incident_endpoints(self):
        logstore.store("error", "linko", "Patladı")
        log = {"Authorization": "Bearer log-anahtari-1234"}
        with patch.object(config, "LOG_KEY", "log-anahtari-1234"):
            self.assertEqual(self.client.get("/api/v1/logs", headers=log).status_code, 200)
            self.assertEqual(self.client.get("/api/v1/logs/export?since=1h", headers=log).status_code, 200)
            ident = self.client.get("/api/v1/incidents", headers=log).json["items"][0]["id"]
            self.assertEqual(self.client.post(f"/api/v1/incidents/{ident}", headers=log,
                                              json={"action": "link", "issue_number": 3}).status_code, 200)
            # Yönetim ve veri uçlarında log anahtarı geçmez.
            self.assertEqual(self.client.post("/api/v1/collections", headers=log, json={"tasks": [{"keyword": "AI"}]}).status_code, 401)
            self.assertEqual(self.client.get("/api/v1/jobs", headers=log).status_code, 401)
            self.assertEqual(self.client.get("/api/v1/status", headers=log).status_code, 401)
            # Okuma anahtarı hâlâ log okuyamaz; yönetici anahtarı geçişte çalışmaya devam eder.
            self.assertEqual(self.client.get("/api/v1/logs", headers={"Authorization": "Bearer reader"}).status_code, 403)
            self.assertEqual(self.client.get("/api/v1/logs", headers=ADMIN).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/logs", headers=log).status_code, 401)  # anahtar tanımlı değilken

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


if __name__ == "__main__":
    unittest.main()
