"""Düzenli taramalar, kaynağı yormayan tarama seçenekleri ve hesapsız kart ayrıştırması."""
import json
import time
import unittest
from unittest.mock import patch
import test_light
from test_light import response, card, DETAIL
from jobapp import config, db, parse, pipeline, watches
from jobapp.models import Job, SearchRun, SearchTask, Setting, Watch
from jobapp.transport import Coordinator


def guest_card(i, company="Bupa Acıbadem Sigorta", location="Maltepe"):
    return f'''<div class="base-search-card" data-entity-urn="urn:li:jobPosting:{i}">
    <h3 class="base-search-card__title">Agentic AI Engineer</h3>
    <h4 class="base-search-card__subtitle">{company}</h4>
    <span class="job-search-card__location">{location}</span></div>'''


class GuestCardTests(unittest.TestCase):
    def test_single_word_location_is_kept(self):
        parsed = parse.parse_guest_card(["Agentic AI Engineer", "Bupa Acıbadem Sigorta", "Maltepe"])
        self.assertEqual((parsed["company"], parsed["location"]), ("Bupa Acıbadem Sigorta", "Maltepe"))

    def test_company_named_turkiye_is_not_a_location(self):
        parsed = parse.parse_guest_card(["Intern", "Honda Türkiye A.Ş.", "Maltepe"])
        self.assertEqual((parsed["company"], parsed["location"]), ("Honda Türkiye A.Ş.", "Maltepe"))

    def test_workplace_suffix_is_split_from_location(self):
        parsed = parse.parse_guest_card(["Dev", "Firma", "İstanbul, Türkiye (Hibrit)"])
        self.assertEqual((parsed["location"], parsed["workplace_type"]), ("İstanbul, Türkiye", "Hybrid"))

    def test_real_titles_with_noise_words_are_kept(self):
        for title in ("Applied Scientist", "Applied AI Engineer", "Incident Response Analyst",
                      "Emergency Response Coordinator", "Bağlantı Elemanı", "Promoted Products Manager",
                      "Network Connection Engineer", "Okuldan Mezun Stajyer"):
            parsed = parse.parse_guest_card([title, "Firma", "İstanbul"])
            self.assertTrue(parsed["quality_ok"], title)
            self.assertEqual(parsed["title"], title)

    def test_empty_or_badge_only_guest_title_is_rejected(self):
        for lines in ([], ["", "Firma", "İstanbul"], ["Promoted", "Firma", "İstanbul"], ["Tanıtıldı", "F", "L"]):
            self.assertFalse(parse.parse_guest_card(lines)["quality_ok"], lines)

    def test_logged_in_card_still_filters_noise_lines(self):
        parsed = parse.parse_card(["Promoted", "Data Engineer", "Firma", "Ankara, Türkiye"])
        self.assertEqual((parsed["title"], parsed["company"]), ("Data Engineer", "Firma"))
        self.assertFalse(parse.parse_card(["2 former employees work here"])["quality_ok"])

    def test_legacy_import_lines_still_use_meaning_based_parser(self):
        raw = {"external_id": "abc", "card_lines": ["T", "T with verification", "Şirket", "Ankara, Türkiye"]}
        self.assertFalse(parse.is_guest_card(raw))


class WatchTests(unittest.TestCase):
    setUp = test_light.FullLightTests.setUp

    def create(self, **body):
        data = dict(name="Elektrik", keywords=["Elektrik stajyeri", "Power Systems Intern"],
                    locations=["Istanbul, Turkey", "Kocaeli, Turkey"], interval_seconds=21600, limit=20)
        data.update(body)
        return self.client.post("/api/watches", json=data)

    def test_scrape_stores_single_word_location(self):
        with patch("requests.Session.get", side_effect=[response(guest_card(1, "Honda Türkiye A.Ş.")), response(DETAIL)]):
            pipeline.run_scrape(["AI"], ["Istanbul"], limit=1)
        with self.factory() as session:
            job = session.query(Job).one()
            self.assertEqual((job.company, job.location), ("Honda Türkiye A.Ş.", "Maltepe"))

    def test_create_validates_and_keeps_comma_locations(self):
        reply = self.create()
        self.assertEqual(reply.status_code, 201)
        watch = reply.json["watch"]
        self.assertEqual(watch["locations"], ["Istanbul, Turkey", "Kocaeli, Turkey"])
        self.assertEqual(watch["combinations"], 4)
        self.assertEqual(self.create(interval_seconds=60).status_code, 400)
        self.assertEqual(self.create(limit=500).status_code, 400)
        many = self.create(keywords=[f"Unvan {i}" for i in range(20)], locations=["A", "B", "C"])
        self.assertEqual(many.status_code, 400)
        self.assertIn("kombinasyon", many.json["error"])

    def test_dispatch_creates_one_safe_run_and_waits_for_it(self):
        ident = self.create().json["watch"]["id"]
        now = time.time()
        with self.factory() as session:
            run_id = watches.dispatch(session, now, {"paused": False})
            self.assertIsNotNone(run_id)
            options = json.loads(session.get(SearchRun, run_id).options)
            self.assertTrue(options["service_managed"] and options["sort_recent"] and options["stop_when_known"])
            self.assertEqual(options["posted_within"], 86400)
            tasks = session.query(SearchTask).filter_by(run_id=run_id).all()
            self.assertEqual({(t.keyword, t.location, t.limit) for t in tasks}, {
                ("Elektrik stajyeri", "Istanbul, Turkey", 20), ("Power Systems Intern", "Istanbul, Turkey", 20),
                ("Elektrik stajyeri", "Kocaeli, Turkey", 20), ("Power Systems Intern", "Kocaeli, Turkey", 20)})
            watch = session.get(Watch, ident)
            self.assertGreaterEqual(watch.next_due_at, now + 21600)
            watch.next_due_at = 0
            session.commit()
            # Önceki tur bitmeden yenisi açılmaz.
            self.assertIsNone(watches.dispatch(session, now, {"paused": False}))
            session.get(SearchRun, run_id).status = "finished"
            session.commit()
            # Kaynak duraklatılmışsa tur ertelenir.
            self.assertIsNone(watches.dispatch(session, now, {"paused": True}))
            self.assertIsNotNone(watches.dispatch(session, now, {"paused": False}))

    def test_disabled_watch_is_not_dispatched_and_run_now_reenables(self):
        ident = self.create().json["watch"]["id"]
        self.assertEqual(self.client.put(f"/api/watches/{ident}", json={"enabled": False}).status_code, 200)
        with self.factory() as session:
            self.assertIsNone(watches.dispatch(session, time.time(), {"paused": False}))
        self.assertTrue(self.client.post(f"/api/watches/{ident}/run-now").json["watch"]["enabled"])
        self.assertEqual(self.client.delete(f"/api/watches/{ident}").status_code, 200)
        self.assertEqual(self.client.get("/api/watches").json["watches"], [])

    def test_smart_search_filters_recent_and_skips_known_details(self):
        with patch("requests.Session.get", side_effect=[response(card(1) + card(2)), response(DETAIL), response(DETAIL), response("")]):
            pipeline.run_scrape(["AI"], ["Istanbul"])
        # Önbellek süresi dolsa bile bilinen ilanların detayı yeniden indirilmez.
        with patch.object(config, "DETAIL_CACHE_TTL_SECONDS", 0), \
             patch("requests.Session.get", side_effect=[response(card(1) + card(2))]) as get:
            pipeline.run_scrape(["AI"], ["Istanbul"], search_options=dict(posted_within=86400, sort_recent=True, stop_when_known=True))
        self.assertEqual(get.call_count, 1)
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["f_TPR"], params["sortBy"]), ("r86400", "DD"))

    def test_request_interval_gets_random_jitter(self):
        coordinator = Coordinator(interval=10, clock=lambda: 1000.0)
        with patch.object(config, "REQUEST_JITTER", 0.3), patch("jobapp.transport.random.uniform", return_value=0.25):
            coordinator.release(coordinator.acquire())
        with coordinator.transaction() as connection:
            self.assertAlmostEqual(coordinator.row(connection)["next_request_at"], 1012.5)

    def test_startup_repair_fixes_existing_guest_rows_once(self):
        raw = {"external_id": "9", "url": "https://www.linkedin.com/jobs/view/9",
               "card_lines": ["Intern", "Wilo Türkiye", "Tuzla"]}
        with self.factory() as session:
            session.add(Job(source=config.SOURCE_LINKEDIN, external_id="9", title="Intern", company="",
                            location="Wilo Türkiye", raw=json.dumps(raw)))
            session.query(Setting).filter_by(key="repair_guest_card_fields_v1").delete()
            session.commit()
        db._repair_guest_card_fields()
        with self.factory() as session:
            job = session.query(Job).filter_by(external_id="9").one()
            self.assertEqual((job.company, job.location), ("Wilo Türkiye", "Tuzla"))
            job.location = "elle değişti"
            session.commit()
        db._repair_guest_card_fields()
        with self.factory() as session:
            self.assertEqual(session.query(Job).filter_by(external_id="9").one().location, "elle değişti")

    def test_startup_repair_restores_hidden_guest_titles_once(self):
        def raw(i, lines):
            return json.dumps({"external_id": str(i), "url": f"https://www.linkedin.com/jobs/view/{i}", "card_lines": lines})
        with self.factory() as session:
            session.add(Job(source=config.SOURCE_LINKEDIN, external_id="21", title="Applied Scientist", company="",
                            location="", quality_ok=False, raw=raw(21, ["Applied Scientist", "Amazon", "İstanbul, Türkiye (Hibrit)"])))
            session.add(Job(source=config.SOURCE_LINKEDIN, external_id="22", title="", company="",
                            location="", quality_ok=False, raw=raw(22, ["", "Firma", "Ankara"])))
            session.add(Job(source=config.SOURCE_LINKEDIN, external_id="23", title="Promoted", company="",
                            location="", quality_ok=False, raw=json.dumps({"external_id": "x23", "card_lines": ["Promoted"]})))
            session.query(Setting).filter_by(key="repair_guest_noise_titles_v1").delete()
            session.commit()
        db._repair_guest_noise_titles()
        with self.factory() as session:
            job = session.query(Job).filter_by(external_id="21").one()
            self.assertTrue(job.quality_ok)
            self.assertEqual((job.title, job.company, job.location), ("Applied Scientist", "Amazon", "İstanbul, Türkiye"))
            self.assertFalse(session.query(Job).filter_by(external_id="22").one().quality_ok)
            self.assertFalse(session.query(Job).filter_by(external_id="23").one().quality_ok)
            self.assertEqual(session.query(Job).count(), 3)
            self.assertIsNotNone(session.get(Setting, "repair_guest_noise_titles_v1"))
            job.quality_ok = False
            session.commit()
        db._repair_guest_noise_titles()
        with self.factory() as session:
            self.assertFalse(session.query(Job).filter_by(external_id="21").one().quality_ok)


if __name__ == "__main__":
    unittest.main()
