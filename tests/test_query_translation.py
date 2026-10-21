import unittest
from unittest.mock import patch

from jobapp import query_translation as translation
from jobapp.locations import normalize


class QueryTranslationTests(unittest.TestCase):
    def test_localities_are_normalized_at_the_source_without_foreign_homonym_leak(self):
        for location, city in [('Ümraniye', 'İstanbul'), ('Karabağlar, Türkiye', 'İzmir'), ('Çankaya', 'Ankara'), ('Bursa', 'Bursa')]:
            self.assertEqual(normalize(location), ('Türkiye', city))
        self.assertEqual(normalize('Bala, United Kingdom')[0], 'Birleşik Krallık')
        self.assertEqual(normalize('Kazan, Russia'), ('Rusya', 'Kazan'))
        self.assertEqual(normalize('Türkiye'), ('Türkiye', 'Belirtilmemiş'))

    def test_localizes_any_source_language_without_changing_destination(self):
        with patch.object(translation.config, 'GROQ_API_KEY', 'test'), patch.object(
                translation.groq_client, 'chat_json', return_value={'keyword': 'Softwareentwickler', 'language': 'de'}) as chat:
            result = translation.plan('yazılım geliştirici', 'Berlin, Germany')
        self.assertEqual(result['keyword'], 'Softwareentwickler')
        self.assertEqual(result['original_keyword'], 'yazılım geliştirici')
        self.assertEqual(result['location'], 'Berlin, Germany')
        self.assertIn('Berlin, Germany', chat.call_args.args[0][1]['content'])
        self.assertEqual(chat.call_args.kwargs['request_timeout'], 8)

    def test_unavailable_or_invalid_translation_preserves_original(self):
        for response in [{}, {'keyword': [], 'language': 'tr'}, {'keyword': 'x', 'language': 'invalid language'}, []]:
            with patch.object(translation.config, 'GROQ_API_KEY', 'test'), patch.object(
                    translation.groq_client, 'chat_json', return_value=response):
                self.assertEqual(translation.plan('C++ engineer', 'Tokyo')['keyword'], 'C++ engineer')
        with patch.object(translation.config, 'GROQ_API_KEY', ''):
            self.assertEqual(translation.plan('工程师', 'Istanbul')['keyword'], '工程师')

    def test_http_timeout_uses_short_translation_budget_and_preserves_original(self):
        client = translation.groq_client
        with patch.object(translation.config, 'GROQ_API_KEY', 'test'), \
                patch.dict(client._quota, tokens_left=None, requests_left=None), \
                patch.object(client.requests, 'post', side_effect=client.requests.Timeout()) as post:
            result = translation.plan('C++ engineer', 'Tokyo')
        self.assertEqual(result['keyword'], 'C++ engineer')
        self.assertEqual(result['status'], 'translation_unavailable')
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['timeout'], 8)
