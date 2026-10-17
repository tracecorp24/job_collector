"""Sorun kuralları, süreç dışı olay klasörü (spool) ve harici olay bildirimi."""
import json
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import text
import test_light
from jobapp import config, logstore, problems, service
from jobapp.models import Incident, SearchRun, Setting
from jobapp.transport import Coordinator

ADMIN = {"Authorization": "Bearer admin-anahtari-123"}


class ProblemTests(unittest.TestCase):
    setUp_light = test_light.FullLightTests.setUp

    def setUp(self):
        self.setUp_light()
        self.now = time.time()
        for item in (patch.object(config, "ADMIN_KEY", "admin-anahtari-123"),
                     patch.object(config, "SPOOL_DIR", str(Path(self.tmp.name) / "spool")),
                     patch.object(config, "BACKUP_STATUS_PATH", str(Path(self.tmp.name) / "backup_status.json")),
                     patch.object(service, "last_error", ""),
                     patch.object(problems, "memory", {}), patch.object(problems, "inactive_since", {}),
                     patch.object(problems, "active_keys", set())):
            item.start()
            self.addCleanup(item.stop)

    def run_rules(self, shift=0):
        with self.factory() as session:
            problems.run_once(session, self.now + shift)

    def problem(self, key):
        with self.factory() as session:
            return session.query(Incident).filter_by(fingerprint=logstore.problem_fingerprint(key)).first()

    def assert_lifecycle(self, key, trigger, clear, trigger_shift=0, cleared_at=0):
        """Koşul sağlanınca açılır; kalktıktan 30 dakika sonra otomatik çözülür; tekrar sağlanınca yeniden açılır."""
        trigger()
        self.run_rules(trigger_shift)
        incident = self.problem(key)
        self.assertEqual((incident.status, incident.kind), ("open", "problem"))
        self.assertIn(key, problems.active_keys)
        clear()
        self.run_rules(cleared_at)
        self.assertEqual(self.problem(key).status, "open")  # 30 dakika dolmadı
        self.run_rules(cleared_at + 1801)
        resolved = self.problem(key)
        self.assertEqual(resolved.status, "resolved")
        self.assertEqual(resolved.issue_state, "")  # issue yoksa durum değişmez
        trigger()
        self.run_rules(cleared_at + 1801 + trigger_shift)
        self.assertEqual((self.problem(key).status, self.problem(key).reopen_count), ("open", 1))

    def set_block(self, seconds, streak=0):
        Coordinator().state()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE source_policy SET blocked_until=:until, violation_streak=:streak, reason='HTTP 429'"),
                         {"until": time.time() + seconds, "streak": streak})

    def test_source_blocked_long(self):
        self.assert_lifecycle("source_blocked_long", lambda: self.set_block(4 * 3600), lambda: self.set_block(0))

    def test_source_blocked_long_by_violation_streak(self):
        self.set_block(60, streak=5)
        self.run_rules()
        self.assertIn("source_blocked_long", problems.active_keys)

    def test_short_source_block_is_not_a_problem(self):
        self.set_block(900, streak=2)
        self.run_rules()
        self.assertEqual(problems.active_keys, set())
        self.assertIsNone(self.problem("source_blocked_long"))

    def add_run(self, **options):
        with self.factory() as session:
            run = SearchRun(id="r" + str(session.query(SearchRun).count()), status=options.pop("status", "paused"),
                            options=json.dumps(options), updated_at=datetime.utcfromtimestamp(self.now - 2 * 86400))
            session.add(run)
            session.commit()
            return run.id

    def test_queue_stalled_ignores_user_paused_and_drafts(self):
        self.add_run(user_paused=True)
        self.add_run(status="queued")  # kullanıcı taslağı
        self.run_rules()
        self.assertEqual(problems.active_keys, set())
        ident = self.add_run(auto_resume_at=0)

        def touch(offset):
            with self.factory() as session:
                session.get(SearchRun, ident).updated_at = datetime.utcfromtimestamp(self.now + offset)
                session.commit()
        self.assert_lifecycle("queue_stalled", lambda: touch(-2 * 86400), lambda: touch(3600))

    def test_queue_stalled_not_raised_while_source_is_blocked(self):
        self.add_run(auto_resume_at=0)
        self.set_block(3600)
        self.run_rules()
        self.assertNotIn("queue_stalled", problems.active_keys)

    def test_supervisor_error_needs_ten_minutes(self):
        def trigger():
            service.last_error = "veritabanı kilitli"
        self.run_rules()
        trigger()
        self.run_rules()
        self.assertEqual(problems.active_keys, set())  # henüz 10 dakika dolmadı
        self.run_rules(601)
        self.assertIn("supervisor_error", problems.active_keys)
        self.assertIn("veritabanı kilitli", self.problem("supervisor_error").sample)
        service.last_error = ""
        self.run_rules(700)
        self.run_rules(700 + 1801)
        self.assertEqual(self.problem("supervisor_error").status, "resolved")

    def test_detail_backlog_resets_when_it_shrinks(self):
        counts = iter([10, 10, 9, 9, 9])
        with patch.object(problems.details, "pending_count", side_effect=lambda session: next(counts)):
            self.run_rules()                      # 10: sayaç başlar
            self.run_rules(25 * 3600)             # hâlâ 10, 25 saat → sorun
            self.assertIn("detail_backlog", problems.active_keys)
            self.run_rules(25 * 3600 + 60)        # 9'a düştü: ilerleme var, sayaç sıfırlanır
            self.assertNotIn("detail_backlog", problems.active_keys)

    def test_backup_stale_and_failed(self):
        path = Path(config.BACKUP_STATUS_PATH)
        self.run_rules()
        self.assertEqual(problems.active_keys, set())  # dosya yok (yerel geliştirme)
        write = lambda **s: path.write_text(json.dumps(s), encoding="utf-8")
        self.assert_lifecycle("backup_stale", lambda: write(ok=True, at=self.now - 40 * 3600),
                              lambda: write(ok=True, at=self.now + 1800 * 5))
        write(ok=False, at=self.now, message="Bütünlük kontrolü başarısız")
        self.run_rules(3 * 3600)
        self.assertIn("Bütünlük kontrolü başarısız", self.problem("backup_stale").sample)

    def test_log_drops_window(self):
        stats = {"dropped": 0, "spooled": 0, "last_error": ""}
        with patch.object(logstore, "stats", side_effect=lambda: dict(stats)):
            self.run_rules()
            self.assertEqual(problems.active_keys, set())
            stats["spooled"] = 4
            stats["last_error"] = "database is locked"
            self.run_rules(10)
            self.assertIn("log_drops", problems.active_keys)
            self.run_rules(10 + 1801)              # sayaç değişmedi: pencere doldu
            self.assertNotIn("log_drops", problems.active_keys)
            self.run_rules(10 + 1801 + 1801)
            self.assertEqual(self.problem("log_drops").status, "resolved")

    def test_rule_failure_does_not_stop_other_rules(self):
        with patch.dict(problems.RULES, {"queue_stalled": lambda s, n: 1 / 0}):
            self.set_block(4 * 3600)
            self.run_rules()
        self.assertIn("source_blocked_long", problems.active_keys)

    def test_open_problem_only_refreshes_last_seen(self):
        self.set_block(4 * 3600)
        self.run_rules()
        first = self.problem("source_blocked_long").last_seen
        time.sleep(0.01)
        self.run_rules(60)
        incident = self.problem("source_blocked_long")
        self.assertEqual(incident.count, 1)
        self.assertGreater(incident.last_seen, first)

    def test_status_endpoint_lists_active_problems(self):
        self.set_block(4 * 3600)
        self.run_rules()
        with patch.object(config, "API_KEY", "okuma-anahtari-456"):
            status = self.client.get("/api/v1/status", headers={"Authorization": "Bearer okuma-anahtari-456"}).json
        self.assertEqual(status["problems"], ["source_blocked_long"])


class ExternalEventTests(unittest.TestCase):
    setUp_light = test_light.FullLightTests.setUp

    def setUp(self):
        self.setUp_light()
        self.spool = Path(self.tmp.name) / "spool"
        for item in (patch.object(config, "ADMIN_KEY", "admin-anahtari-123"), patch.object(config, "SPOOL_DIR", str(self.spool))):
            item.start()
            self.addCleanup(item.stop)

    def test_shell_spool_events_become_external_incidents(self):
        self.spool.mkdir()
        lines = [json.dumps({"source": "deploy", "level": "error", "title": "Deploy geri alındı", "at": time.time(),
                             "message": "Başarısız sürüm: abc1234 token=hunter2hunter2"}),
                 "bozuk satır",
                 json.dumps({"source": "deploy", "level": "error", "title": "Deploy geri alındı", "at": time.time(), "message": "Başarısız sürüm: def5678"}),
                 json.dumps({"source": "systemd", "level": "error", "title": "linko.service beklenmedik şekilde durdu", "at": time.time()})]
        (self.spool / "external-20261017.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(logstore.drain_spool(), 3)
        self.assertEqual(len(list((self.spool / "done").glob("external-*.jsonl"))), 1)
        with self.factory() as session:
            incidents = {i.logger: i for i in session.query(Incident)}
            self.assertEqual({i.kind for i in incidents.values()}, {"external"})
            self.assertEqual(incidents["linko.deploy"].count, 2)  # sabit başlık: tekrarlar tek kayıtta
            self.assertEqual(incidents["linko.deploy"].title, "[linko.deploy] Deploy geri alındı")
            self.assertNotIn("hunter2hunter2", incidents["linko.deploy"].sample + incidents["linko.deploy"].traceback)

    def test_report_endpoint_records_resolved_outage_and_reopens_on_repeat(self):
        body = {"source": "uptime", "title": "Site erişilemiyor", "message": "Site 12 dakika erişilemedi.", "level": "critical",
                "status": "resolved", "issue_number": 12, "at": "2026-10-17T10:00:00Z"}
        self.assertEqual(self.client.post("/api/v1/incidents/report", json=body).status_code, 401)
        reply = self.client.post("/api/v1/incidents/report", headers=ADMIN, json=body)
        self.assertEqual(reply.status_code, 200, reply.json)
        self.assertEqual((reply.json["status"], reply.json["issue_number"], reply.json["kind"]), ("resolved", 12, "external"))
        self.assertTrue(reply.json["first_seen"].startswith("2026-10-17T10:00"))
        again = self.client.post("/api/v1/incidents/report", headers=ADMIN, json=dict(body, issue_number=15, at="2026-10-18T10:00:00Z"))
        self.assertEqual((again.json["status"], again.json["count"], again.json["reopen_count"], again.json["issue_number"]),
                         ("resolved", 2, 1, 15))
        detail = self.client.get(f"/api/v1/incidents/{again.json['id']}", headers=ADMIN).json
        events = [h["event"] for h in detail["history"]]
        self.assertEqual(events.count("resolved"), 2)
        self.assertIn("reopened", events)

    def test_report_endpoint_validates_input(self):
        for body in ({}, {"source": "Büyük Harf", "title": "x"}, {"source": "uptime", "title": ""},
                     {"source": "uptime", "title": "x", "level": "info"}, {"source": "uptime", "title": "x", "status": "bitti"},
                     {"source": "uptime", "title": "x", "issue_number": "12"}):
            self.assertEqual(self.client.post("/api/v1/incidents/report", headers=ADMIN, json=body).status_code, 400, body)

    def test_auto_resolved_problem_keeps_issue_open_for_sync(self):
        with self.factory() as session:
            ident = logstore.raise_problem(session, "backup_stale", "Yedek eskidi", "40 saat")
            logstore.link_issue(session.get(Incident, ident), 21)
            session.commit()
            logstore.clear_problem(session, "backup_stale", "koşul kalktı")
            incident = session.get(Incident, ident)
            self.assertEqual((incident.status, incident.issue_state, incident.issue_number), ("resolved", "open", 21))


if __name__ == "__main__":
    unittest.main()
