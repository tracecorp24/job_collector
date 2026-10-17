"""Kural tabanlı çıkarım: deneyim şart cümlesinden, kıdem tam kelimeden; eski kayıtlar ağ isteği olmadan düzelir."""
import json
import unittest
from unittest.mock import patch

import test_light
from jobapp import db, pipeline, skills
from jobapp.classify import _shared, rules
from jobapp.models import Job, Setting


class ExperienceTests(unittest.TestCase):
    def test_requirement_sentences(self):
        for text, expected in [
            ("We require 3 years of experience in Python.", 3),
            ("3-5 years of experience", 3),
            ("3-5 yıl deneyimli", 3),
            ("En az 3 yıllık iş deneyimi olan", 3),
            ("Minimum 2 years experience", 2),
            ("at least 4+ years", 4),
            ("5+ yıl", 5),
            ("robot sektöründe 3 yıl tecrübe", 3),
            ("up to 2 years of experience", 0),
            ("minimum 10 yıl deneyim ve en az 3 yıl ekip yönetimi", 10),
        ]:
            self.assertEqual(skills.extract_experience_years(text), expected, text)

    def test_company_age_and_dates_are_not_experience(self):
        for text in ("30 yılı aşkın deneyimiyle kablo sektöründe faaliyet gösteren firmamız",
                     "At DAL we draw on more than 35 years of industry experience.",
                     "Grafton, Avrupa'da 40 yılı aşan tecrübesi ile işe alım hizmeti",
                     "50 yıllık tecrübesiyle", "1993 yılında kurulan şirketimiz"):
            self.assertIsNone(skills.extract_experience_years(text), text)

    def test_seniority_words_only_count_in_title(self):
        self.assertIsNone(skills.extract_experience_years("We lead Turkey's market.", "Teknik Temsilci"))
        self.assertEqual(skills.extract_experience_years("We mentor junior engineers.", "Senior Embedded Engineer"), 5)
        self.assertEqual(skills.extract_experience_years("", "Elektrik Stajyeri"), 0)

    def test_model_value_fills_gap_but_never_overrides_rule(self):
        self.assertEqual(pipeline.experience_years("Şirketimiz 30 yılı aşkın deneyimiyle", "Mühendis", {"experience_years": 2}), 2)
        self.assertEqual(pipeline.experience_years("En az 4 yıl deneyim", "Mühendis", {"experience_years": 9}), 4)
        self.assertEqual(pipeline.experience_years("", "Senior Engineer", {}), 5)
        merged = _shared.apply_fields({"classified_by": "rules"}, {"min_experience_years": 3}, "groq")
        self.assertEqual(merged["experience_years"], 3)
        for bad in (True, "3", 99, -1):
            self.assertNotIn("experience_years", _shared.apply_fields({}, {"min_experience_years": bad}, "groq"))


class RuleTests(unittest.TestCase):
    def test_seniority_whole_words(self):
        for title, expected in [
            ("Machine Learning Engineer at International Startup", "Mid"), ("Internal Auditor", "Mid"),
            ("Internet Marketing Specialist", "Mid"), ("Sales Engineer - Leading Automotive Company", "Mid"),
            ("Satış Yönetici Asistanı", "Junior"), ("Müdür Yardımcısı", "Manager"), ("Uzman Yardımcısı", "Junior"),
            ("Elektrik Dizayn Şefi", "Manager"), ("Senior Manager", "Manager"), ("Stajyer Mühendis", "Intern"),
            ("Project Leader", "Lead"), ("New Graduate Engineer", "Junior"), ("Sr. Developer", "Senior"),
        ]:
            self.assertEqual(rules.classify_seniority(title), expected, title)

    def test_turkish_standard_is_not_typescript_and_quality_control_is_operations(self):
        result = rules.classify("Kalite Kontrol Uzmanı", "TS EN ISO 9001 standartlarına hakimiyet.", "")
        self.assertNotIn("typescript", result["tags"])
        self.assertEqual(result["category"], "Operations")
        self.assertIn("typescript", rules.classify("Frontend Developer", "React ve TypeScript", "")["tags"])


class ReprocessTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp

    def test_old_rule_values_are_recomputed_once_without_touching_llm_results(self):
        with self.factory() as session:
            session.add(Job(external_id="r1", title="Elektrik Mühendisi", description="30 yılı aşkın deneyimiyle. En az 2 yıl deneyim.",
                            experience_years=30, seniority="Intern", category="Finance", classified_by="rules", tags='["typescript"]'))
            session.add(Job(external_id="g1", title="Internal Auditor", description="Grafton 40 yılı aşan tecrübesi ile",
                            experience_years=40, seniority="Senior", category="Finance", classified_by="groq", tags='["audit"]'))
            session.query(Setting).filter_by(key=db.RULES_VERSION).delete()
            session.commit()
        db._reprocess_rule_fields()
        with self.factory() as session:
            ruled = session.query(Job).filter_by(external_id="r1").one()
            self.assertEqual((ruled.experience_years, ruled.seniority, json.loads(ruled.tags)), (2, "Mid", []))
            llm = session.query(Job).filter_by(external_id="g1").one()
            self.assertIsNone(llm.experience_years)  # şirket yaşı temizlendi
            self.assertEqual((llm.seniority, llm.category, llm.tags), ("Senior", "Finance", '["audit"]'))  # model sonucu korunur
            self.assertEqual(json.loads(session.get(Setting, db.RULES_VERSION).value)["changed"], 2)
            ruled.experience_years = 30
            session.commit()
        db._reprocess_rule_fields()  # işaret var: ikinci kez çalışmaz
        with self.factory() as session:
            self.assertEqual(session.query(Job).filter_by(external_id="r1").one().experience_years, 30)

    def test_unchanged_rows_are_not_updated(self):
        with self.factory() as session:
            session.add(Job(external_id="u1", title="Engineer", description="En az 3 yıl deneyim", experience_years=3,
                            seniority="Mid", category="Engineering", classified_by="rules", tags="[]"))
            session.query(Setting).filter_by(key=db.RULES_VERSION).delete()
            session.commit()
            before = session.execute(db.text("SELECT COUNT(*) FROM job_changes")).scalar()
        db._reprocess_rule_fields()
        with self.factory() as session:
            self.assertEqual(session.execute(db.text("SELECT COUNT(*) FROM job_changes")).scalar(), before)


if __name__ == "__main__":
    unittest.main()
