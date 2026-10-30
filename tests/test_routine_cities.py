"""Tests for routine city pool configuration, country annotations and API."""
import json
import unittest

import test_light
import test_workspace
from jobapp import locations, routine_cities
from jobapp.models import SearchRun, SearchTask


class RoutineCitiesTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp
    tearDown = test_workspace.WorkspaceTests.tearDown

    def test_routine_cities_structure_and_countries(self):
        self.assertEqual(len(routine_cities.ROUTINE_CITIES), 30)
        self.assertEqual(routine_cities.CITY_COUNT, 30)
        self.assertIn("Kalibrasyon Mühendisliği", routine_cities.ROUTINE_PROFESSIONS)
        self.assertIn("Sistem Mühendisliği", routine_cities.ROUTINE_PROFESSIONS)
        self.assertEqual(routine_cities.ROUTINE_PROFESSION_KEYWORDS_INTL["Kalibrasyon Mühendisliği"], "Calibration Engineer")
        self.assertEqual(routine_cities.ROUTINE_PROFESSION_KEYWORDS_INTL["Sistem Mühendisliği"], "System Engineer")

        countries = set()
        for city_info in routine_cities.ROUTINE_CITIES:
            self.assertIn("city", city_info)
            self.assertIn("country", city_info)
            self.assertIn("location", city_info)
            self.assertIn("quota", city_info)
            self.assertIn("critical", city_info)
            self.assertIn("order", city_info)

            country = city_info["country"]
            self.assertTrue(bool(country), f"Country missing for {city_info['city']}")
            countries.add(country)

            # Check consistency with locations._CITY_COUNTRY
            expected_country = locations._CITY_COUNTRY.get(city_info["city"])
            self.assertEqual(country, expected_country, f"Country mismatch for {city_info['city']}")

        self.assertEqual(len(countries), 19)

        # Istanbul must be first and critical with country Türkiye
        istanbul = routine_cities.ROUTINE_CITIES[0]
        self.assertEqual(istanbul["city"], "İstanbul")
        self.assertEqual(istanbul["country"], "Türkiye")
        self.assertEqual(istanbul["order"], 1)
        self.assertTrue(istanbul["critical"])

    def test_routine_cities_api_returns_countries(self):
        resp = self.client.get("/api/routine-cities")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        self.assertEqual(data["total"], 30)
        self.assertEqual(data["country_count"], 19)
        self.assertEqual(len(data["cities"]), 30)

        for city in data["cities"]:
            self.assertIn("country", city)
            self.assertTrue(bool(city["country"]))
            self.assertEqual(city["country"], locations._CITY_COUNTRY.get(city["city"]))

    def test_dispatch_includes_country_in_run_options_and_tasks(self):
        with self.factory() as session:
            run_id = routine_cities.dispatch(session, now=1000, source={"paused": False})
            self.assertIsNotNone(run_id)

            run = session.get(SearchRun, run_id)
            options = json.loads(run.options)
            self.assertEqual(options["routine_city"], "İstanbul")
            self.assertEqual(options["routine_country"], "Türkiye")

            tasks = session.query(SearchTask).filter_by(run_id=run_id).all()
            self.assertEqual(len(tasks), len(routine_cities.ROUTINE_PROFESSIONS))
            # Türkiye şehri Türkçe anahtar kelimelerle taranır
            self.assertEqual(tasks[1].keyword, "Yazılım Mühendisliği")

    def test_foreign_city_dispatches_with_international_keywords(self):
        with self.factory() as session:
            schedules = routine_cities._ensure_schedules(session)
            for row in schedules.values():
                row.next_due_at = 999999
            schedules["Amsterdam"].next_due_at = 500
            session.commit()

            run_id = routine_cities.dispatch(session, now=1000, source={"paused": False})
            self.assertIsNotNone(run_id)

            run = session.get(SearchRun, run_id)
            options = json.loads(run.options)
            self.assertEqual(options["routine_city"], "Amsterdam")
            self.assertEqual(options["routine_country"], "Hollanda")

            tasks = session.query(SearchTask).filter_by(run_id=run_id).order_by(SearchTask.position).all()
            # Yabancı şehir için LinkedIn İngilizce meslek terimleriyle aranır
            self.assertEqual(tasks[1].keyword, "Software Engineer")
            self.assertEqual(tasks[2].keyword, "Mechanical Engineer")


if __name__ == "__main__":
    unittest.main()
