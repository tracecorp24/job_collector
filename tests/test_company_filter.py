import unittest
from unittest.mock import patch
from jobapp import server, config


class CompanyFilterTests(unittest.TestCase):
    def setUp(self):
        self.admin_key = "test-company-admin-key"
        self.patcher = patch.object(config, "ADMIN_KEY", self.admin_key)
        self.patcher.start()
        self.client = server.create_app().test_client()
        self.headers = {"Authorization": f"Bearer {self.admin_key}"}

    def tearDown(self):
        self.patcher.stop()

    def test_facets_returns_company_counts(self):
        res = self.client.get("/api/facets", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("company", data)
        company_facets = data["company"]
        self.assertIsInstance(company_facets, list)
        if company_facets:
            first = company_facets[0]
            self.assertIn("value", first)
            self.assertIn("count", first)
            self.assertGreater(first["count"], 0)

    def test_jobs_filter_by_company_exact_and_case_insensitive(self):
        # Fetch top company from facets
        res = self.client.get("/api/facets", headers=self.headers)
        companies = res.get_json().get("company", [])
        if not companies:
            self.skipTest("No companies in test database")

        top_company = companies[0]["value"]
        expected_count = companies[0]["count"]

        # Exact match
        res_exact = self.client.get(f"/api/jobs?company={top_company}", headers=self.headers)
        self.assertEqual(res_exact.status_code, 200)
        exact_data = res_exact.get_json()
        self.assertEqual(exact_data["total"], expected_count)
        for job in exact_data.get("jobs", []):
            self.assertEqual(job["company"].strip().lower(), top_company.strip().lower())

        # Case-insensitive match (lowercase)
        res_lower = self.client.get(f"/api/jobs?company={top_company.lower()}", headers=self.headers)
        self.assertEqual(res_lower.status_code, 200)
        lower_data = res_lower.get_json()
        self.assertEqual(lower_data["total"], expected_count)

    def test_jobs_filter_multi_company(self):
        res = self.client.get("/api/facets", headers=self.headers)
        companies = res.get_json().get("company", [])
        if len(companies) < 2:
            self.skipTest("Need at least 2 companies for multi-company test")

        c1, c2 = companies[0], companies[1]
        expected_total = c1["count"] + c2["count"]

        res_multi = self.client.get(f"/api/jobs?company={c1['value']}&company={c2['value']}", headers=self.headers)
        self.assertEqual(res_multi.status_code, 200)
        multi_data = res_multi.get_json()
        self.assertEqual(multi_data["total"], expected_total)


if __name__ == "__main__":
    unittest.main()
