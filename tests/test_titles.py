"""Groq entegrasyonu: unvan önerisi, kota yönetimi ve ilan sınıflandırması."""
import json
import unittest
from unittest.mock import patch
import requests
import test_light
from jobapp import config, groq_client, titles, watches
from jobapp.classify import classify_job
from jobapp.models import Watch


class FakeResponse:
    def __init__(self, content="{}", status=200, headers=None):
        self.status_code, self.content, self.headers = status, content, headers or {}

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


class Groq:
    """Sıradaki yanıtları döndüren sahte Groq; gönderilen istekleri saklar."""
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append(dict(url=url, json=json, headers=headers))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return item if isinstance(item, FakeResponse) else FakeResponse(globals()["json"].dumps(item))


class GroqBase(unittest.TestCase):
    setUp_light = test_light.FullLightTests.setUp

    def setUp(self):
        self.setUp_light()
        for item in (patch.object(config, "GROQ_API_KEY", "test-key"),
                     patch.dict(groq_client._quota, {"tokens_left": None, "tokens_reset_at": 0.0,
                                                     "requests_left": None, "requests_reset_at": 0.0})):
            item.start()
            self.addCleanup(item.stop)

    def groq(self, *responses):
        fake = Groq(*responses)
        item = patch.object(groq_client.requests, "post", fake)
        item.start()
        self.addCleanup(item.stop)
        return fake


class TitleSuggestionTests(GroqBase):
    def test_endpoint_returns_clean_unique_titles(self):
        fake = self.groq({"titles": ["1. Data Scientist", "data scientist", " Veri  Bilimci ", "", "x" * 200,
                                     "Data Analyst", "Veri Analisti", "Data Engineer"]})
        result = self.client.post("/api/title-suggestions", json={"field": "veri bilimi"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["titles"], ["Data Scientist", "Veri Bilimci", "Data Analyst", "Veri Analisti", "Data Engineer"])
        self.assertEqual(fake.calls[0]["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(fake.calls[0]["json"]["messages"][1]["content"], "veri bilimi")
        self.assertIn("5 adet", fake.calls[0]["json"]["messages"][0]["content"])

    def test_empty_field_and_missing_key(self):
        self.assertEqual(self.client.post("/api/title-suggestions", json={"field": " "}).status_code, 400)
        with patch.object(config, "GROQ_API_KEY", ""):
            result = self.client.post("/api/title-suggestions", json={"field": "muhasebe"})
        self.assertEqual(result.status_code, 503)
        self.assertIn("GROQ_API_KEY", result.json["error"])

    def test_upstream_errors_are_reported(self):
        self.groq(FakeResponse(status=429, headers={"retry-after": "120"}))
        with self.assertRaises(titles.TitleError) as caught:
            titles.suggest("muhasebe")
        self.assertEqual(caught.exception.status, 429)

        def down(*args, **kwargs):
            raise requests.ConnectionError()
        with self.assertRaises(titles.TitleError):
            titles.suggest("muhasebe", post=down)
        self.groq({"titles": []})
        with self.assertRaises(titles.TitleError):
            titles.suggest("muhasebe")


class QuotaTests(GroqBase):
    def test_waits_for_minute_quota_and_stops_on_daily_quota(self):
        now = [1000.0]
        sleeps = []
        fake = self.groq(FakeResponse('{"ok": 1}', headers={"x-ratelimit-remaining-tokens": "100",
                                                            "x-ratelimit-reset-tokens": "7.5s",
                                                            "x-ratelimit-remaining-requests": "999",
                                                            "x-ratelimit-reset-requests": "1m26s"}))
        messages = [{"role": "user", "content": "hi"}]
        groq_client.chat(messages, clock=lambda: now[0], sleep=sleeps.append)
        groq_client.chat(messages, clock=lambda: now[0], sleep=sleeps.append, max_wait=10)
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 7.7)
        with self.assertRaises(groq_client.GroqError):  # Bekleme sınırı aşılırsa beklemez, hemen düşer.
            groq_client.chat(messages, clock=lambda: now[0], sleep=sleeps.append, max_wait=2)
        groq_client._quota.update(requests_left=0, requests_reset_at=now[0] + 3600)
        with self.assertRaises(groq_client.GroqError) as caught:
            groq_client.chat(messages, clock=lambda: now[0], sleep=sleeps.append)
        self.assertIn("günlük", str(caught.exception))
        self.assertEqual(len(fake.calls), 2)

    def test_duration_formats(self):
        self.assertEqual(groq_client._seconds("2m59.5s"), 179.5)
        self.assertEqual(groq_client._seconds("120ms"), 0.12)
        self.assertEqual(groq_client._seconds("1h2m"), 3720)
        self.assertEqual(groq_client._seconds("3"), 3)


class ClassifyTests(GroqBase):
    def test_groq_backend_enriches_and_falls_back(self):
        fake = self.groq({"category": "Data", "seniority": "Junior", "tags": ["Python", "SQL"],
                          "summary": "Veri analizi yapan rol.", "salary": "40.000 TL", "flag": "",
                          "formatted_description": "yeniden yazım istenmez"})
        result = classify_job("Data Analyst", "Python ve SQL bilen veri analisti arıyoruz. " * 300, backend="groq")
        self.assertEqual((result["classified_by"], result["category"], result["seniority"]), ("groq", "Data", "Junior"))
        self.assertEqual(result["tags"], ["python", "sql"])
        self.assertNotIn("yeniden", result.get("formatted_description", ""))
        self.assertEqual(fake.calls[0]["json"]["model"], config.GROQ_CLASSIFY_MODEL)
        self.assertLess(len(fake.calls[0]["json"]["messages"][1]["content"]), 4100)
        self.groq(FakeResponse(status=500))
        self.assertEqual(classify_job("Data Analyst", "metin", backend="groq")["classified_by"], "rules")

    def test_scrape_endpoint_accepts_groq(self):
        result = self.client.post("/api/queue", json={"tasks": [{"id": "g1", "keyword": "AI", "location": "Istanbul", "limit": 5}],
                                                      "classify_backend": "groq"})
        self.assertEqual(result.status_code, 200, result.json)

    def test_watches_use_groq_when_key_is_set(self):
        with self.factory() as session:
            session.add(Watch(id="w1", name="AI", keywords='["AI"]', locations='["Istanbul"]', interval_seconds=3600,
                              limit=5, posted_within=86400, enabled=True, next_due_at=0))
            session.commit()
            run_id = watches.dispatch(session, 10, {})
            session.commit()
            from jobapp.models import SearchRun
            self.assertEqual(json.loads(session.get(SearchRun, run_id).options)["classify_backend"], "groq")


if __name__ == "__main__":
    unittest.main()
