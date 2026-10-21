"""Internship facts must survive collection, repairs, persistence and API filtering."""
import json
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from werkzeug.datastructures import MultiDict
from jobapp.models import Base, Job
from jobapp.opportunities import classify, refresh
from jobapp.db import upsert_job
from jobapp.filters import filtered
from unittest.mock import patch


class OpportunityTests(unittest.TestCase):
    def test_title_classification_avoids_false_friends_and_program_managers(self):
        for title in ('International Sales Manager', 'Internal Auditor', 'Internship Coordinator', 'Staj Koordinatörü', 'Senior Engineer'):
            self.assertEqual(classify(title, 'Stajyerlere mentorluk yapar. Mentoring interns.')['opportunity_type'], 'job', title)
        for title in ('Software Intern', 'Yazılım Stajyeri', 'Yaz stajı', 'Praktikum Software'):
            self.assertEqual(classify(title)['opportunity_type'], 'internship', title)
        self.assertEqual(classify('Management Trainee')['opportunity_type'], 'graduate')
        self.assertEqual(classify('Yeni Mezun Mühendis')['opportunity_type'], 'graduate')
        self.assertEqual(classify('Trainee')['opportunity_type'], 'unknown')

    def test_explicit_source_and_description_evidence(self):
        self.assertEqual(classify('Software Developer', employment_type='internship')['opportunity_type'], 'internship')
        self.assertEqual(classify('Software Developer', 'This role is an internship.')['opportunity_type'], 'internship')
        self.assertEqual(classify('Software Developer', 'This role is not an internship.')['opportunity_type'], 'job')

    def test_unknown_is_not_free_voluntary_or_zero_days(self):
        d=classify('Software Intern')['internship_details']
        for key in ('paid', 'mandatory', 'period', 'duration_weeks', 'weekly_days', 'deadline'):
            self.assertIsNone(d[key], key)
        self.assertEqual(d['class_years'], [])

    def test_turkish_requirements_ranges_deadline_and_evidence(self):
        d=classify('Yaz Dönemi Stajyeri', 'Zorunlu staj. Ücretli staj. 8–12 hafta, haftada 3 gün. 3. veya 4. sınıf öğrencileri. Bilgisayar Mühendisliği bölümü öğrencileri. Son başvuru: 30.11.2026.')['internship_details']
        self.assertEqual((d['period'], d['mandatory'], d['paid']), ('summer', True, True))
        self.assertEqual((d['duration_min_weeks'], d['duration_weeks'], d['weekly_days']), (8,12,3))
        self.assertEqual(d['class_years'], [3,4])
        self.assertEqual(d['departments'], ['Bilgisayar Mühendisliği'])
        self.assertEqual(d['deadline'], '2026-11-30')
        self.assertTrue(d['evidence'])

    def test_conflicts_and_negation_remain_unknown(self):
        d=classify('Summer Internship', 'Uzun dönem. Zorunlu staj şartı aranmıyor. Paid internship or unpaid internship. Son başvuru: 2026-02-30')['internship_details']
        for key in ('period','mandatory','paid','deadline'):
            self.assertIsNone(d[key], key)

    def test_upsert_then_detail_refresh_and_multifilter(self):
        engine=create_engine('sqlite://')
        Base.metadata.create_all(engine)
        try:
            with sessionmaker(bind=engine)() as session:
                job,created=upsert_job(session,dict(source='linkedin',external_id='one',title='Software Intern',company='Example',workplace_type='Remote',description=''))
                session.commit()
                self.assertTrue(created)
                self.assertEqual(job.opportunity_type,'internship')
                self.assertIsNone(json.loads(job.internship_details)['paid'])
                job,_=upsert_job(session,dict(source='linkedin',external_id='one',description='Paid internship. 8 weeks. 3 days per week.'))
                session.commit()
                self.assertTrue(json.loads(job.internship_details)['paid'])
                result=filtered(session,MultiDict([('opportunity_type','internship'),('workplace','Remote')])).all()
                self.assertEqual([x.id for x in result],[job.id])
                self.assertEqual(job.to_dict()['internship_details']['weekly_days'],3)
                job.title='International Sales Manager';refresh(job);session.commit()
                self.assertEqual(job.opportunity_type,'job')
                self.assertEqual(filtered(session,MultiDict([('opportunity_type','internship')])).count(),0)
        finally:
            engine.dispose()

    def test_backfill_uses_migration_engine_and_is_idempotent(self):
        from jobapp import db
        engine=create_engine('sqlite://')
        Base.metadata.create_all(engine)
        factory=sessionmaker(bind=engine)
        try:
            with factory() as session:
                session.add(Job(source='linkedin',external_id='old',title='Yazılım Stajyeri',description='Ücretli staj.',seniority='Intern'))
                session.commit()
            with patch.object(db,'engine',engine):
                db._backfill_opportunities()
                db._backfill_opportunities()
            with factory() as session:
                job=session.query(Job).one()
                self.assertEqual(job.opportunity_type,'internship')
                self.assertTrue(job.to_dict()['internship_details']['paid'])
                self.assertEqual(session.query(Job).count(),1)
        finally:
            engine.dispose()

if __name__=='__main__':
    unittest.main()
