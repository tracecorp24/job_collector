"""Yedek davranışları ve gizli veri içermeyen tanılama kayıtları."""
import builtins
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jobapp import config, server
from jobapp.classify import llm


class SearchHistoryLoggingTests(unittest.TestCase):
    def test_bad_metadata_is_skipped_with_one_summary_and_no_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, contents in (("bad-json", "private-content-not-for-logs"),
                                   ("bad-shape", "[]"),
                                   ("valid", json.dumps({"startedAt": "2026-10-28"}))):
                destination = root / name
                destination.mkdir()
                (destination / "search.json").write_text(contents, encoding="utf-8")
            with patch.object(config, "ACCOUNTLESS_OUTPUT_DIR", folder), \
                    server.app.test_request_context("/api/searches"), \
                    self.assertLogs("jobapp.server", level="WARNING") as logs:
                response = server.api_searches()

        self.assertEqual(response.json["total"], 1)
        self.assertEqual(response.json["searches"][0]["folder"], "valid")
        self.assertEqual(response.json["searches"][0]["hasLog"], False)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("2 kayıt okunamadı", logs.output[0])
        self.assertNotIn("private-content-not-for-logs", logs.output[0])

    def test_missing_history_directory_keeps_empty_response(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(config, "ACCOUNTLESS_OUTPUT_DIR", str(Path(folder) / "missing")), \
                server.app.test_request_context("/api/searches"), \
                self.assertNoLogs("jobapp.server", level="WARNING"):
            self.assertEqual(server.api_searches().json, {"searches": [], "total": 0})


class ClaudeFallbackLoggingTests(unittest.TestCase):
    def setUp(self):
        llm._warn_unavailable.cache_clear()
        self.addCleanup(llm._warn_unavailable.cache_clear)
        self.base = {"category": "Engineering", "classified_by": "rules"}

    def test_missing_key_preserves_result_and_warns_once(self):
        with patch.object(config, "ANTHROPIC_API_KEY", ""), \
                self.assertLogs("jobapp.classify.llm", level="WARNING") as logs:
            for _ in range(3):
                self.assertIs(llm.enrich("Engineer", "Description", self.base), self.base)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("ANTHROPIC_API_KEY ayarlanmamış", logs.output[0])

    def test_missing_package_preserves_result_and_does_not_log_key(self):
        original_import = builtins.__import__

        def without_anthropic(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("private-import-details")
            return original_import(name, *args, **kwargs)

        with patch.object(config, "ANTHROPIC_API_KEY", "private-key-value"), \
                patch("builtins.__import__", side_effect=without_anthropic), \
                self.assertLogs("jobapp.classify.llm", level="WARNING") as logs:
            for _ in range(3):
                self.assertIs(llm.enrich("Engineer", "Description", self.base), self.base)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("anthropic paketi kurulu değil", logs.output[0])
        self.assertNotIn("private-key-value", logs.output[0])
        self.assertNotIn("private-import-details", logs.output[0])

    def test_provider_error_preserves_result_and_logs_only_error_type(self):
        client = SimpleNamespace(messages=SimpleNamespace(create=Mock(
            side_effect=RuntimeError("private-provider-response"))))
        with patch.object(llm, "_client", return_value=client), \
                self.assertLogs("jobapp.classify.llm", level="WARNING") as logs:
            self.assertIs(llm.enrich("Private title", "Private description", self.base), self.base)
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("private-provider-response", logs.output[0])
        self.assertNotIn("Private title", logs.output[0])
        self.assertNotIn("Private description", logs.output[0])


if __name__ == "__main__":
    unittest.main()
