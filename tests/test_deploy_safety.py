"""Dağıtım yedeği/geri alma gerçek SQLite dosyalarıyla, yalnızca geçici dizinde sınanır."""
import json
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import tempfile
import unittest

from deploy import safety


@contextmanager
def opened(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        yield connection


class DeploySafetyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "jobs.db"
        self.backup = Path(self.folder.name) / "backups" / "jobs.db"
        with opened(self.database) as connection:
            connection.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY, title TEXT)")
            connection.execute("INSERT INTO jobs(title) VALUES ('korunacak')")

    def test_vacuum_snapshot_and_restore_preserve_data_and_sha(self):
        report = safety.snapshot(self.database, self.backup, "a" * 40)
        with opened(self.database) as connection:
            connection.execute("UPDATE jobs SET title='yeni sürüm'")
        restored = safety.restore(self.backup, self.database)
        self.assertEqual(report, restored)
        self.assertEqual(restored["sha"], "a" * 40)
        with opened(self.database) as connection:
            self.assertEqual(connection.execute("SELECT title FROM jobs").fetchone()[0], "korunacak")
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_modified_backup_cannot_replace_live_database(self):
        safety.snapshot(self.database, self.backup, "a" * 40)
        with opened(self.backup) as connection:
            connection.execute("DELETE FROM jobs")
        with self.assertRaisesRegex(ValueError, "parmak izi"):
            safety.restore(self.backup, self.database)
        with opened(self.database) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_existing_destination_and_invalid_sha_are_rejected(self):
        with self.assertRaises(ValueError):
            safety.snapshot(self.database, self.backup, "not-a-sha")
        with self.assertRaises(ValueError):
            safety.snapshot(self.database, self.database, "a" * 40)
        safety.snapshot(self.database, self.backup, "a" * 40)
        before = self.backup.read_bytes()
        with self.assertRaises(ValueError):
            safety.snapshot(self.database, self.backup, "a" * 40)
        self.assertEqual(self.backup.read_bytes(), before)

    def test_missing_manifest_is_fail_closed(self):
        self.backup.parent.mkdir()
        self.backup.write_bytes(self.database.read_bytes())
        with self.assertRaises(FileNotFoundError):
            safety.restore(self.backup, self.database)

    def test_manifest_records_only_backup_metadata(self):
        safety.snapshot(self.database, self.backup, "b" * 40)
        report = json.loads(self.backup.with_suffix(".db.json").read_text(encoding="utf-8"))
        self.assertEqual(set(report), {"sha", "database", "sha256", "created_at"})
        self.assertNotIn("korunacak", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
