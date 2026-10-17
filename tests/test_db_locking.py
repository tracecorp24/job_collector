"""SQLite kilit beklemesi, salt okuma kaynak durumu ve tek seferlik init_db."""
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine

from jobapp import config, db
from jobapp.transport import Coordinator, Details


class DbLockingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "jobs.db"
        self.engine = create_engine("sqlite:///" + str(self.path), connect_args={"timeout": 5})
        self.addCleanup(self.engine.dispose)

    def test_busy_timeout_is_30_seconds(self):
        self.assertEqual(config.DB_BUSY_TIMEOUT_MS, 30000)
        with closing(sqlite3.connect(self.path)) as connection:
            db._set_sqlite_pragma(connection, None)
            self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

    def test_state_does_not_wait_for_write_lock(self):
        coordinator = Coordinator(engine=self.engine)
        coordinator.state()  # satır ilk çağrıda bir kez oluşur
        with closing(sqlite3.connect(self.path, isolation_level=None)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE source_policy SET reason='kilit'")
            started = time.monotonic()
            state = coordinator.state()
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertFalse(state["paused"])
            writer.execute("ROLLBACK")

    def test_table_checks_run_once_per_engine(self):
        Coordinator(engine=self.engine)
        Details(engine=self.engine)
        with patch("jobapp.models.SourcePolicy.__table__.create") as policy, \
                patch("jobapp.models.DetailCache.__table__.create") as cache:
            Coordinator(engine=self.engine)
            Details(engine=self.engine)
        policy.assert_not_called()
        cache.assert_not_called()

    def test_init_db_migrates_once_unless_forced(self):
        with patch.object(db, "engine", self.engine), \
                patch.object(config, "ACCOUNTLESS_OUTPUT_DIR", str(Path(self.tmp.name) / "searches")):
            db.init_db()
            with patch.object(db, "_migrate") as migrate:
                db.init_db()
                migrate.assert_not_called()
                db.init_db(force=True)
                migrate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
