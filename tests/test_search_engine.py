import unittest
from jobapp.search_engine import expand_search_terms, search_fold, build_search_filter
from jobapp.models import Job


class SearchEngineTests(unittest.TestCase):
    def test_search_fold_handles_turkish_and_accents(self):
        self.assertEqual(search_fold("İSTANBUL"), "istanbul")
        self.assertEqual(search_fold("Kıdemli Yazılım Mühendisi"), "kidemli yazilim muhendisi")
        self.assertEqual(search_fold("Örnek Şirket Çözümleri"), "ornek sirket cozumleri")

    def test_search_fold_handles_european_accents(self):
        self.assertEqual(search_fold("Geschäftsführer"), "geschaftsfuhrer")
        self.assertEqual(search_fold("Großbritannien"), "grossbritannien")
        self.assertEqual(search_fold("München"), "munchen")

    def test_expand_search_terms_for_mechanical_engineer(self):
        terms = expand_search_terms("makine mühendisi")
        terms_lower = [t.lower() for t in terms]
        self.assertIn("makine mühendisi", terms)
        self.assertTrue(any("mechanical engineer" in t for t in terms_lower))
        self.assertTrue(any("maschinenbauingenieur" in t for t in terms_lower))

    def test_expand_search_terms_for_software_engineer(self):
        terms = expand_search_terms("yazılım mühendisi")
        terms_lower = [t.lower() for t in terms]
        self.assertIn("yazılım mühendisi", terms)
        self.assertTrue(any("software engineer" in t for t in terms_lower))
        self.assertTrue(any("software developer" in t for t in terms_lower))
        self.assertTrue(any("softwareentwickler" in t for t in terms_lower))

    def test_expand_search_terms_for_internship(self):
        terms = expand_search_terms("stajyer")
        terms_lower = [t.lower() for t in terms]
        self.assertIn("stajyer", terms)
        self.assertTrue(any("intern" in t for t in terms_lower))
        self.assertTrue(any("internship" in t for t in terms_lower))
        self.assertTrue(any("praktikant" in t for t in terms_lower))

    def test_expand_search_terms_for_calibration_and_system_engineer(self):
        calib_terms = [t.lower() for t in expand_search_terms("calibration engineer")]
        self.assertTrue(any("kalibrasyon mühendisliği" in t or "kalibrasyon mühendisi" in t for t in calib_terms))

        sys_terms = [t.lower() for t in expand_search_terms("system engineer")]
        self.assertTrue(any("sistem mühendisi" in t or "sistem mühendisliği" in t for t in sys_terms))

        bio_terms = [t.lower() for t in expand_search_terms("moleküler biyoloji")]
        self.assertTrue(any("molecular biology" in t or "molecular biologist" in t for t in bio_terms))

    def test_build_search_filter_returns_valid_clause(self):
        clause = build_search_filter(Job, "makine mühendisi")
        self.assertIsNotNone(clause)
        # Empty search returns None
        self.assertIsNone(build_search_filter(Job, ""))
        self.assertIsNone(build_search_filter(Job, "   "))


if __name__ == "__main__":
    unittest.main()
