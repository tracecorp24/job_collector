"""Mocked source to database, JSON snapshot and service API contract."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_light
from jobapp import config, pipeline
from jobapp.models import Job


class InternshipCollectionTests(unittest.TestCase):
    setUp=test_light.FullLightTests.setUp

    def test_source_filter_and_api_snapshots(self):
        replies=[test_light.response(test_light.card(1).replace('AI Engineer','Software Intern')),
                 test_light.response('<div class="show-more-less-html__markup">Paid internship. Summer internship. 8 weeks. 3 days per week.</div>')]
        with patch('requests.Session.get',side_effect=replies) as get:
            result=pipeline.run_scrape(['Software'],['Istanbul'],limit=1,search_options={'opportunity_type':'internship'})
        self.assertEqual(get.call_args_list[0].kwargs['params']['f_JT'],'I')
        with self.factory() as session:
            row=session.query(Job).one()
            self.assertEqual(row.opportunity_type,'internship')
            self.assertTrue(row.to_dict()['internship_details']['paid'])
        snapshot=json.loads(next((Path(result['output_folders'][0])/'ilan_havuzu').glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(snapshot['opportunityType'],'internship')
        self.assertEqual(snapshot['internshipDetails']['duration_weeks'],8)
        response=self.client.get('/api/jobs?opportunity_type=internship')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['total'],1)
        facets=self.client.get('/api/facets').json
        self.assertEqual(facets['opportunity_type'],[{'value':'internship','count':1}])
        with patch.object(config,'API_KEY','internship-test-key'):
            response=self.client.get('/api/v1/jobs?opportunity_type=internship',headers={'Authorization':'Bearer internship-test-key'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertTrue(response.json['items'][0]['internship_details']['paid'])
            changes=self.client.get('/api/v1/jobs/changes',headers={'Authorization':'Bearer internship-test-key'})
            upserts=[x['job'] for x in changes.json['items'] if x['operation']=='upsert']
            self.assertTrue(any(x['opportunity_type']=='internship' and isinstance(x['internship_details'],dict) for x in upserts))

    def test_collection_choice_is_persistent_and_validated(self):
        response=self.client.post('/api/queue',json={'tasks':[{'keyword':'Software','location':'Istanbul','limit':5}],'opportunity_type':'internship'})
        self.assertEqual(response.status_code,200,response.json)
        run=self.client.get('/api/runs/'+response.json['run_id']).json
        self.assertEqual(run['opportunity_type'],'internship')
        invalid=self.client.post('/api/queue',json={'tasks':[{'keyword':'Software'}],'opportunity_type':'made-up'})
        self.assertEqual(invalid.status_code,400)
