"""Catalog contract and serialization query budget, isolated from production."""
import gzip
import json
import unittest
from unittest.mock import patch
from sqlalchemy import event
import test_light
import test_workspace
from jobapp import config
from jobapp.models import Job


class CatalogTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown

    def get(self, url, **kwargs):
        headers = {'Authorization': 'Bearer catalog-test-key', **kwargs.pop('headers', {})}
        with patch.object(config, 'API_KEY', 'catalog-test-key'):
            return self.client.get(url, headers=headers, **kwargs)

    def seed(self, count=12):
        with self.factory() as session:
            session.add_all([Job(source='linkedin', external_id=str(i), title='Engineer', company='Test',
                description='Python special-description-word', location_country='Türkiye',
                location_city='İstanbul', quality_ok=True) for i in range(count)])
            session.commit()

    def test_compact_catalog_excludes_descriptions_and_refreshes_after_change(self):
        self.seed()
        response = self.get('/api/v1/jobs/catalog', headers={'Accept-Encoding':'gzip'})
        self.assertEqual(response.status_code, 200)
        etag = response.headers.get('ETag')
        self.assertTrue(bool(etag))
        cached_resp = self.get('/api/v1/jobs/catalog', headers={'Accept-Encoding':'gzip', 'If-None-Match': etag})
        self.assertEqual(cached_resp.status_code, 304)
        self.assertEqual(cached_resp.data, b'')
        data = json.loads(gzip.decompress(response.data))
        self.assertEqual(len(data['items']), 12)
        self.assertNotIn('description', data['items'][0])
        self.assertEqual(data['items'][0]['country'], 'Türkiye')
        with self.factory() as session:
            session.query(Job).filter_by(external_id='0').update({'deleted_at': __import__('datetime').datetime.now()})
            session.commit()
        after = self.get('/api/v1/jobs/catalog').json
        self.assertNotEqual(after['token'], data['token'])
        self.assertEqual(len(after['items']), 11)
        self.assertEqual(self.get('/api/v1/jobs/detail/linkedin/0').status_code, 404)

    def test_job_page_does_not_issue_one_query_per_listing(self):
        self.seed()
        queries = []
        engine = self.factory.kw['bind']
        def executed(conn, cursor, statement, *args):
            if statement.lstrip().upper().startswith('SELECT'): queries.append(statement)
        event.listen(engine, 'before_cursor_execute', executed)
        try:
            response = self.get('/api/v1/jobs?limit=12')
        finally:
            event.remove(engine, 'before_cursor_execute', executed)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['items']), 12)
        self.assertLessEqual(len(queries), 3)

    def test_description_search_returns_ids_and_details_are_lazy(self):
        self.seed()
        ids = self.get('/api/v1/jobs/search-ids?q=special-description-word').json['ids']
        self.assertEqual(len(ids), 12)
        response = self.get('/api/v1/jobs/detail/linkedin/1')
        self.assertIn('special-description-word', response.json['item']['description'])
        self.assertEqual(self.get('/api/v1/jobs/search-ids?q=doesnotexist').json['ids'], [])

    def test_cold_preview_reads_only_fifty_rows_and_keeps_full_count(self):
        self.seed(80)
        response = self.get('/api/v1/jobs/catalog?limit=50')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['items']), 50)
        self.assertEqual(response.json['total'], 80)
        self.assertNotIn('description', response.json['items'][0])
