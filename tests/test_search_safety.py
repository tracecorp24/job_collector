"""Arama dış ağdan bağımsız kalır; Unicode ve jokerler sonuç kaybettirmez."""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, literal, select

import test_light
from jobapp import filters, search_engine as search, search_text
from jobapp.models import Job


def translation_response(payload):
    response = MagicMock()
    response.__enter__.return_value = response
    response.raw.read.return_value = json.dumps(payload).encode("utf-8")
    return response


class TranslationSafetyTests(unittest.TestCase):
    def setUp(self):
        for item in (patch.object(search, "TRANSLATE_ENABLED", True),
                     patch.object(search, "_TRANSLATE_RETRY_AT", 0.0),
                     patch.dict(search._TRANSLATE_CACHE, {}, clear=True),
                     patch.object(search, "_TRANSLATE_INFLIGHT", set())):
            item.start()
            self.addCleanup(item.stop)
        self.session = MagicMock()
        item = patch.object(search, "_translation_session", return_value=self.session)
        item.start()
        self.addCleanup(item.stop)

    def test_disabled_or_short_queries_never_open_network(self):
        with patch.object(search, "TRANSLATE_ENABLED", False):
            self.assertEqual(search.translate_query("unlistedword"), "unlistedword")
            self.assertTrue(any("artificial intelligence" == term.lower()
                                for term in search.expand_search_terms("yapay zeka")))
        for text in ("", "a", "AI", "ML", "x" * 401):
            self.assertEqual(search.translate_query(text), text)
        self.session.get.assert_not_called()

    def test_success_is_cached_per_target_and_bounds_response(self):
        self.session.get.return_value = translation_response([[["software engineer"]]])
        self.assertEqual(search.translate_query("yazılım mühendisi"), "software engineer")
        self.assertEqual(search.translate_query("yazılım mühendisi"), "software engineer")
        self.session.get.assert_called_once()
        self.assertEqual(self.session.get.call_args.kwargs["timeout"], 2.5)
        self.session.get.return_value.raw.read.assert_called_once_with(50001, decode_content=True)
        search.translate_query("yazılım mühendisi", target="de")
        self.assertEqual(self.session.get.call_count, 2)

    def test_timeout_has_ten_minute_negative_cache_and_global_cooldown(self):
        self.session.get.side_effect = search.requests.Timeout("private-query-and-provider-data")
        with patch.object(search.time, "monotonic", return_value=100), \
                self.assertLogs(search.log, level="WARNING") as logs:
            self.assertEqual(search.translate_query("original"), "original")
        self.assertNotIn("private-query-and-provider-data", logs.output[0])
        with patch.object(search.time, "monotonic", return_value=159):
            search.translate_query("different")
        self.assertEqual(self.session.get.call_count, 1)
        self.session.get.side_effect = None
        self.session.get.return_value = translation_response([[["translated"]]])
        with patch.object(search.time, "monotonic", return_value=161):
            self.assertEqual(search.translate_query("different"), "translated")
            self.assertEqual(search.translate_query("original"), "original")
        self.assertEqual(self.session.get.call_count, 2)
        with patch.object(search.time, "monotonic", return_value=701):
            self.assertEqual(search.translate_query("original"), "translated")
        self.assertEqual(self.session.get.call_count, 3)

    def test_invalid_and_oversized_responses_are_cached_failures(self):
        for payload in (b"not-json", b"[]", b"{}", b"[[[]]]", b"x" * 50001):
            with self.subTest(payload=payload[:12]):
                search._TRANSLATE_CACHE.clear()
                search._TRANSLATE_RETRY_AT = 0
                response = translation_response([])
                response.raw.read.return_value = payload
                self.session.get.return_value = response
                self.session.get.reset_mock()
                with self.assertLogs(search.log, level="WARNING"):
                    self.assertEqual(search.translate_query("original"), "original")
                self.assertEqual(search.translate_query("original"), "original")
                self.session.get.assert_called_once()
                self.assertFalse(search._TRANSLATE_INFLIGHT)

    def test_same_query_does_not_wait_for_inflight_translation(self):
        started, release = threading.Event(), threading.Event()

        def blocking_get(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise TimeoutError("Test çevirisi serbest bırakılmadı.")
            return translation_response([[["translated"]]])

        self.session.get.side_effect = blocking_get
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(search.translate_query, "original")
            try:
                self.assertTrue(started.wait(2))
                second = executor.submit(search.translate_query, "original")
                self.assertEqual(second.result(timeout=2), "original")
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), "translated")
        self.session.get.assert_called_once()

    def test_failure_cache_is_bounded(self):
        self.session.get.side_effect = search.requests.Timeout()
        with patch.object(search, "_MAX_CACHE", 3), patch.object(search.log, "warning"):
            for index in range(6):
                search._TRANSLATE_RETRY_AT = 0
                search.translate_query("query-" + str(index))
        self.assertEqual(len(search._TRANSLATE_CACHE), 3)


class TranslationSessionTests(unittest.TestCase):
    def test_http_sessions_are_reused_without_sharing_between_threads(self):
        ready = threading.Barrier(2)

        def session_pair():
            first = search._translation_session()
            ready.wait(timeout=3)
            return first, search._translation_session()

        with patch.object(search, "_HTTP_LOCAL", threading.local()), \
                patch.object(search.requests, "Session", side_effect=object), \
                ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(session_pair)
            second = executor.submit(session_pair)
            a, b = first.result(timeout=5), second.result(timeout=5)
            self.assertIs(a[0], a[1])
            self.assertIs(b[0], b[1])
            self.assertIsNot(a[0], b[0])


class SearchTextTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)

    def test_query_and_sql_use_the_same_unicode_rules(self):
        with self.engine.connect() as connection:
            for stored, query in (("Straße", "strasse"), ("STRAẞE", "STRASSE"),
                                  ("Málaga", "malaga"), ("Kraków", "krakow"),
                                  ("Gdańsk", "gdansk"), ("Łódź", "lodz"),
                                  ("İSTANBUL", "istanbul"), ("IĞDIR", "igdir"),
                                  ("Cafe\u0301", "cafe"), ("C++", "C++"), ("C#", "C#")):
                with self.subTest(stored=stored):
                    self.assertEqual(connection.scalar(select(search.folded_column(literal(stored)))),
                                     search.search_fold(query))
                    self.assertTrue(connection.scalar(select(search.contains(literal(stored), query))))
                    self.assertTrue(connection.scalar(select(search.contains(literal(stored), stored))))

    def test_like_metacharacters_are_literals_in_all_search_paths(self):
        with self.engine.connect() as connection, patch.object(search, "TRANSLATE_ENABLED", False):
            for query, unrelated in (("a_b", "axb"), ("100%", "1000"), ("a\\b", "ab")):
                with self.subTest(query=query):
                    for contains in (search.contains, filters.contains):
                        self.assertTrue(connection.scalar(select(contains(literal(query), query))))
                        self.assertFalse(connection.scalar(select(contains(literal(unrelated), query))))

    def test_extended_search_does_not_treat_underscore_as_a_wildcard(self):
        from sqlalchemy.orm import Session
        Job.__table__.create(self.engine)
        with Session(self.engine) as session, patch.object(search, "TRANSLATE_ENABLED", False):
            session.add_all([Job(external_id="literal", title="a_b"),
                             Job(external_id="other", title="axb")])
            session.commit()
            rows = session.query(Job).filter(search.build_search_filter(Job, "a_b")).all()
            self.assertEqual([row.external_id for row in rows], ["literal"])


class SearchEndpointSafetyTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp

    def test_jobs_and_facets_do_not_use_network_by_default(self):
        with patch.object(search, "TRANSLATE_ENABLED", False), patch.object(search, "_translation_session") as http:
            for path in ("/api/jobs?search=unlistedword", "/api/facets?search=unlistedword&country=Almanya"):
                self.assertEqual(self.client.get(path).status_code, 200)
            http.assert_not_called()

    def test_facet_timeout_is_attempted_once_even_with_country_expansion(self):
        with patch.object(search, "TRANSLATE_ENABLED", True), \
                patch.object(search, "_TRANSLATE_RETRY_AT", 0), \
                patch.dict(search._TRANSLATE_CACHE, {}, clear=True), \
                patch.object(search, "_translation_session") as http, \
                self.assertLogs(search.log, level="WARNING"):
            http.return_value.get.side_effect = search.requests.Timeout()
            result = self.client.get("/api/facets?search=unlistedword&country=Almanya")
            self.assertEqual(result.status_code, 200)
            http.return_value.get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
