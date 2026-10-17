"""Log deposunun sağlamlığı: maskeleme, parmak izi, toplu yazım, spool, istisna kancası, sürüm."""
import json
import logging
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import test_light
from jobapp import audit, config, logstore
from jobapp.models import AppLog, Incident


class ResilienceTests(unittest.TestCase):
    setUp_light = test_light.FullLightTests.setUp

    def setUp(self):
        self.setUp_light()
        self.spool = Path(self.tmp.name) / "spool"
        for item in (patch.object(config, "SPOOL_DIR", str(self.spool)),
                     patch.object(config, "VERSION_PATH", str(Path(self.tmp.name) / "version.json")),
                     patch.object(config, "ADMIN_KEY", "admin-anahtari-123"), patch.object(config, "API_KEY", "okuma-anahtari-456"),
                     patch.object(config, "GROQ_API_KEY", "groq-gizli-deger-789")):
            item.start()
            self.addCleanup(item.stop)

    def entry(self, message="x", level="info", **extra):
        return logstore.make_entry(level, "linko.test", message, **extra)

    def test_redact_masks_known_values_and_patterns(self):
        text = ("Authorization: Bearer abcdefghijkl1234 anahtar admin-anahtari-123 groq groq-gizli-deger-789 "
                "gsk_abcdefgh12345678 sk-ant-abcdefghijklmnopqrstu password=hunter2 token: abc123 tokens 5")
        masked = logstore.redact(text)
        for secret in ("abcdefghijkl1234", "admin-anahtari-123", "groq-gizli-deger-789", "gsk_abcdefgh12345678",
                       "abcdefghijklmnopqrstu", "hunter2", "abc123"):
            self.assertNotIn(secret, masked)
        self.assertIn("tokens 5", masked)

    def test_stored_log_and_traceback_are_redacted(self):
        logstore.store("error", "linko.test", "çağrı Bearer abcdefghijkl1234 başarısız", traceback="admin-anahtari-123 sızdı")
        with self.factory() as session:
            row = session.query(AppLog).one()
            self.assertNotIn("abcdefghijkl1234", row.message)
            self.assertNotIn("admin-anahtari-123", row.traceback)
            self.assertNotIn("abcdefghijkl1234", session.query(Incident).one().sample)

    def test_audit_incident_ignores_keyword_and_location(self):
        handler = logstore.DatabaseHandler()
        logging.getLogger("linko.audit").addHandler(handler)
        self.addCleanup(logging.getLogger("linko.audit").removeHandler, handler)
        with self.factory() as session:
            for keyword, location in (("Elektrik", "Istanbul"), ("AI Engineer", "Ankara"), ("Backend", "Izmir")):
                audit.record(session, "run12345xyz", None, "page_failed", {"keyword": keyword, "location": location,
                                                                         "reason": "Arama sayfası alınamadı"}, "error")
            session.commit()
        with self.factory() as session:
            incident = session.query(Incident).one()
            self.assertEqual(incident.count, 3)

    def test_distinct_audit_reasons_stay_distinct(self):
        logstore.store("error", "linko.audit", "a", key="page_failed|Arama sayfası alınamadı")
        logstore.store("error", "linko.audit", "b", key="page_failed|Kaynak bloğu")
        with self.factory() as session:
            self.assertEqual(session.query(Incident).count(), 2)

    def test_writer_holds_records_until_ready_then_writes_in_batches(self):
        writer = logstore.Writer()
        writer.thread.start()
        for n in range(450):
            writer.put(self.entry(f"satır {n}"))
        writer.put(self.entry("hata", "error"))
        writer.stopping.set()
        with self.factory() as session:
            self.assertEqual(session.query(AppLog).count(), 0)  # veritabanı hazır değil: bekliyor
        writer.ready.set()
        writer.thread.join(10)
        self.assertFalse(writer.thread.is_alive())
        self.assertEqual(writer.stats["written"], 451)
        with self.factory() as session:
            self.assertEqual(session.query(AppLog).count(), 451)
            self.assertEqual(session.query(Incident).count(), 1)

    def test_bounded_queue_counts_dropped_records(self):
        writer = logstore.Writer(limit=2)
        for n in range(5):
            writer.put(self.entry(f"satır {n}"))
        self.assertEqual((writer.queue.qsize(), writer.stats["dropped"]), (2, 3))

    def test_database_failure_spools_to_file_and_drain_restores(self):
        writer = logstore.Writer()
        writer.put(self.entry("kaybolmamalı", "error", created_at=datetime(2026, 10, 17, 12)))
        with patch.object(logstore, "store_batch", side_effect=RuntimeError("database is locked")):
            writer.write(writer.collect())
        self.assertEqual((writer.stats["spooled"], writer.stats["written"]), (1, 0))
        self.assertIn("database is locked", writer.stats["last_error"])
        files = list(self.spool.glob("applog-*.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])["message"], "kaybolmamalı")
        self.assertEqual(logstore.drain_spool(), 1)
        self.assertFalse(list(self.spool.glob("applog-*.jsonl")))
        self.assertEqual(len(list((self.spool / "done").glob("applog-*.jsonl"))), 1)
        with self.factory() as session:
            self.assertEqual(session.query(AppLog).one().message, "kaybolmamalı")
            self.assertEqual(session.query(Incident).one().count, 1)

    def test_unwritable_spool_counts_as_dropped(self):
        writer = logstore.Writer()
        writer.put(self.entry("x"))
        with patch.object(logstore, "store_batch", side_effect=RuntimeError("kilit")), \
                patch.object(logstore, "spool", side_effect=OSError("disk dolu")):
            writer.write(writer.collect())
        self.assertEqual(writer.stats["dropped"], 1)

    def test_uncaught_exception_becomes_critical_incident(self):
        handler = logstore.DatabaseHandler()
        logging.getLogger("linko").addHandler(handler)
        self.addCleanup(logging.getLogger("linko").removeHandler, handler)
        try:
            raise RuntimeError("beklenmedik çökme")
        except RuntimeError:
            logstore.log_uncaught(*sys.exc_info(), where="deneme iş parçacığı")
        with self.factory() as session:
            incident = session.query(Incident).one()
            self.assertEqual(incident.level, "critical")
            self.assertIn("beklenmedik çökme", incident.traceback)
            self.assertIn("deneme iş parçacığı", incident.sample)

    def test_version_is_recorded_and_exposed(self):
        self.assertEqual(config.version_info()["sha"], "bilinmiyor")
        Path(config.VERSION_PATH).write_text(json.dumps({"sha": "abc1234", "subject": "deneme"}), encoding="utf-8")
        self.assertEqual(config.version_info()["sha"], "abc1234")
        logstore.store("error", "linko.test", "aynı hata 1")
        Path(config.VERSION_PATH).write_text(json.dumps({"sha": "def5678", "subject": "yeni"}), encoding="utf-8")
        logstore.store("error", "linko.test", "aynı hata 2")
        with self.factory() as session:
            incident = session.query(Incident).one()
            self.assertEqual((incident.first_version, incident.last_version), ("abc1234", "def5678"))
            self.assertEqual([r.version for r in session.query(AppLog).order_by(AppLog.id)], ["abc1234", "def5678"])
            self.assertEqual(logstore.serialize(incident)["last_version"], "def5678")
        status = self.client.get("/api/v1/status", headers={"Authorization": "Bearer okuma-anahtari-456"}).json
        self.assertEqual(status["version"]["sha"], "def5678")
        self.assertIn("logging", status)
        self.assertEqual(self.client.get("/healthz").json["version"], "def5678")


if __name__ == "__main__":
    unittest.main()
