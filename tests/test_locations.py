import unittest

from jobapp.locations import normalize, normalize_country


class LocationNormalizationTests(unittest.TestCase):
    def test_city_aliases_and_country_regions_normalize(self):
        self.assertEqual(normalize("Istanbul, Türkiye"), ("Türkiye", "İstanbul"))
        self.assertEqual(normalize("London Area, England, United Kingdom"), ("Birleşik Krallık", "Londra"))
        self.assertEqual(normalize("Berlin"), ("Almanya", "Berlin"))

    def test_preserves_remote_city_with_its_country(self):
        self.assertEqual(normalize("Remote, Germany"), ("Almanya", "Uzaktan"))

    def test_normalizes_long_us_location(self):
        self.assertEqual(normalize("San Francisco Bay Area, California, United States"), ("ABD", "San Francisco"))

    def test_normalizes_ai_country_names_and_rejects_unknown_values(self):
        self.assertEqual(normalize_country("Germany"), "Almanya")
        self.assertEqual(normalize_country("United States"), "ABD")
        self.assertEqual(normalize_country("Somewhere"), "")

    def test_normalizes_greater_and_localities(self):
        self.assertEqual(normalize("Greater Istanbul"), ("Türkiye", "İstanbul"))
        self.assertEqual(normalize("Hadımköy"), ("Türkiye", "İstanbul"))
        self.assertEqual(normalize("Riva"), ("Türkiye", "İstanbul"))
        self.assertEqual(normalize("Greater London, United Kingdom"), ("Birleşik Krallık", "Londra"))
        self.assertEqual(normalize(""), ("Belirtilmemiş", "Belirtilmemiş"))


if __name__ == "__main__":
    unittest.main()
