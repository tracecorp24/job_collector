"""Günlük bakım budaması, sunucu loglaması ve servis panelindeki depolama/yedek durumu."""
import json
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text
import test_light
from jobapp import audit, config, maintenance
from jobapp.models import SearchEvent


class MaintenanceTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp

    def test_prunes_only_records_older_than_retention(self):
        now = time.time()
        with self.factory() as session:
            session.add(SearchEvent(run_id="r", kind="log", created_at=datetime.utcnow() - timedelta(days=200)))
            session.add(SearchEvent(run_id="r", kind="log", created_at=datetime.utcnow() - timedelta(days=1)))
            session.execute(text("INSERT INTO job_changes(job_id,operation,payload,created_at) VALUES (1,'upsert','{}','2020-01-01T00:00:00Z'),(2,'upsert','{}',:recent)"),
                            {"recent": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")})
            session.commit()
            self.assertTrue(maintenance.due(session, now))
            result = maintenance.run(session, now)
            self.assertEqual((result["events_deleted"], result["changes_deleted"]), (1, 1))
            self.assertEqual(session.query(SearchEvent).count(), 1)
            self.assertEqual(session.execute(text("SELECT COUNT(*) FROM job_changes WHERE job_id=2")).scalar(), 1)
            self.assertFalse(maintenance.due(session, now + 3600))
            self.assertTrue(maintenance.due(session, now + 86400))

    def test_service_status_reports_storage_and_offsite_backup(self):
        status_file = Path(self.tmp.name) / "backup_status.json"
        status_file.write_text(json.dumps({"ok": True, "at": time.time(), "message": "gönderildi", "size": "2.2M"}), encoding="utf-8")
        with patch.object(config, "BACKUP_STATUS_PATH", str(status_file)):
            storage = self.client.get("/api/service/status").json["storage"]
        self.assertTrue(storage["offsite_backup"]["ok"])
        self.assertEqual(storage["event_retention_days"], config.EVENT_RETENTION_DAYS)
        self.assertIn("job_changes", storage["counts"])

    def test_warnings_and_key_events_reach_process_log_but_requests_do_not(self):
        with self.factory() as session:
            with self.assertLogs("linko.audit", "INFO") as logs:
                audit.record(session, "run12345xyz", None, "source_paused", {"reason": "HTTP 429", "seconds": 900}, "warning")
                audit.record(session, "run12345xyz", None, "request_started", {"url": "https://example.test"})
                audit.record(session, "run12345xyz", None, "watch_run_created", {"name": "Elektrik"})
        self.assertEqual(len(logs.records), 2)
        self.assertIn("source_paused run=run12345 task=- reason=HTTP 429 seconds=900", logs.output[0])
        self.assertTrue(logs.output[0].startswith("WARNING"))
        self.assertIn("name=Elektrik", logs.output[1])


if __name__ == "__main__":
    unittest.main()
