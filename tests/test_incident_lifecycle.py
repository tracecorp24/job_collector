"""Hata kaydı yaşam döngüsü: gerçek sunucu API'si ile sahte GitHub arasında uçtan uca (incident_sync)."""
import json
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import test_light
from jobapp import config, logstore
from jobapp.models import Incident, SearchEvent

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import incident_sync  # noqa: E402

ADMIN = {"Authorization": "Bearer admin-anahtari-123"}
FIX = "f" * 40
LIVE = "1" * 40


def iso(moment=None):
    return (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class FakeGitHub:
    """İhtiyaç duyulan GitHub uçlarının bellek içi taklidi."""

    def __init__(self):
        self.issues, self.comments, self.deployed = {}, [], set()

    def close(self, number, commit=None, reason="completed"):
        self.issues[number].update(state="closed", closed_at=iso(), state_reason=reason, commit=commit)

    def reopen(self, number):
        self.issues[number].update(state="open", closed_at=None, commit=None)

    def handle(self, method, path, body):
        if path == "/labels":
            return {}
        if path.startswith("/issues?"):
            return [dict(i, body=i["body"]) for i in self.issues.values() if i["state"] == "open"]
        if path == "/issues" and method == "POST":
            number = len(self.issues) + 1
            self.issues[number] = dict(number=number, state="open", closed_at=None, body=body["body"], title=body["title"], commit=None)
            return {"number": number}
        parts = path.split("/")
        if parts[1] == "issues":
            number = int(parts[2])
            issue = self.issues[number]
            if len(parts) == 3 and method == "GET":
                return {k: issue.get(k) for k in ("number", "state", "closed_at", "state_reason")}
            if len(parts) == 3 and method == "PATCH":
                if body["state"] == "closed":
                    self.close(number)
                else:
                    self.reopen(number)
                return {}
            if parts[3] == "comments":
                self.comments.append((number, body["body"]))
                return {}
            if parts[3].startswith("events"):
                return [{"event": "closed", "commit_id": issue.get("commit")}] if issue["state"] == "closed" else []
        if parts[1] == "compare":
            base = parts[2].split("...")[0]
            return {"status": "ahead" if base in self.deployed else "behind"}
        raise AssertionError(f"beklenmeyen GitHub çağrısı: {method} {path}")


class LifecycleTests(unittest.TestCase):
    setUp_light = test_light.FullLightTests.setUp

    def setUp(self):
        self.setUp_light()
        self.version = Path(self.tmp.name) / "version.json"
        for item in (patch.object(config, "ADMIN_KEY", "admin-anahtari-123"), patch.object(config, "VERSION_PATH", str(self.version))):
            item.start()
            self.addCleanup(item.stop)
        self.deploy("1" * 7)
        self.gh = FakeGitHub()

    def deploy(self, short, at=None):
        self.version.write_text(json.dumps({"sha": short, "full_sha": short * 6 + "0" * 12 if len(short) == 7 else short,
                                            "deployed_at": at or time.time()}), encoding="utf-8")
        self.live_full = json.loads(self.version.read_text(encoding="utf-8"))["full_sha"]

    def http(self, method, url, token, body=None):
        if url.startswith("https://site"):
            reply = self.client.open(url[len("https://site"):], method=method, json=body, headers=ADMIN)
            if reply.status_code >= 400:
                raise RuntimeError(f"{method} {url} -> {reply.status_code} {reply.get_data(as_text=True)[:200]}")
            return reply.json
        return self.gh.handle(method, url.split("/repos/o/r")[1], body)

    def sync(self):
        incident_sync.Sync("https://site", "k", "o/r", "t", self.http).run()

    def incident(self):
        with self.factory() as session:
            return session.query(Incident).order_by(Incident.id).first()

    def fail(self, message="Görev 1 başarısız"):
        logstore.store("error", "linko.test", message)

    def events(self):
        return [h["event"] for h in json.loads(self.incident().history)]

    def comments_with(self, text):
        return [c for c in self.gh.comments if text in c[1]]

    def ship(self, commit=FIX):
        """Düzeltme commit'i hatadan SONRA canlıya çıkar."""
        self.gh.deployed.add(commit)
        time.sleep(0.01)
        self.deploy("2" * 7)

    def open_issue(self):
        self.fail()
        self.sync()
        return self.incident().issue_number

    def age_fix(self, hours):
        with self.factory() as session:
            session.query(Incident).one().fix_deployed_at = datetime.utcnow() - timedelta(hours=hours)
            session.commit()

    def test_new_incident_opens_labelled_issue_with_marker(self):
        self.fail("Patladı run=abcdef1234 token=hunter2hunter2")
        self.sync()
        issue = self.gh.issues[1]
        self.assertIn("<!-- linko-incident:1 -->", issue["body"])
        self.assertEqual(self.incident().issue_state, "open")
        self.sync()
        self.assertEqual(len(self.gh.issues), 1)  # ikinci tur yinelenen issue açmaz

    def test_issue_body_masks_secrets_even_if_stored_unmasked(self):
        self.fail()
        with self.factory() as session:
            session.query(Incident).one().sample = "istek Bearer abcdefghijkl1234 api_key=hunter22hunter22 gsk_abcdefgh12345678"
            session.commit()
        self.sync()
        for secret in ("abcdefghijkl1234", "hunter22hunter22", "gsk_abcdefgh12345678"):
            self.assertNotIn(secret, self.gh.issues[1]["body"])

    def test_flood_is_capped_per_run_and_drains_over_following_runs(self):
        for n in range(7):
            logstore.store("error", f"linko.kaynak{n}", f"Hata {n}")
        self.sync()
        normal = [i for i in self.gh.issues.values() if incident_sync.FLOOD not in i["body"]]
        flood = [i for i in self.gh.issues.values() if incident_sync.FLOOD in i["body"]]
        self.assertEqual((len(normal), len(flood)), (incident_sync.MAX_NEW_ISSUES, 1))
        self.assertIn("#6", flood[0]["body"])
        self.assertIn("#7", flood[0]["body"])
        self.sync()                                   # sıradakiler sonraki turda normal issue olur
        self.assertEqual(len([i for i in self.gh.issues.values() if incident_sync.FLOOD not in i["body"]]), 7)
        with self.factory() as session:
            self.assertEqual(session.query(Incident).filter(Incident.issue_number.is_(None)).count(), 0)

    def test_full_cycle_waits_for_deploy_then_24_hours_then_resolves(self):
        number = self.open_issue()
        self.assertEqual((number, self.incident().status), (1, "open"))
        self.assertIn("linko_logs.py incident 1 --context 10m", self.gh.issues[1]["body"])
        self.gh.close(number, commit=FIX)            # "Fixes #1" commit'iyle kapandı
        self.fail("Görev 2 başarısız")               # düzeltme yayına çıkmadan görülen tekrar beklenendir
        self.sync()
        self.assertEqual((self.incident().status, self.gh.issues[1]["state"]), ("open", "closed"))
        self.assertEqual(self.comments_with("yeniden açıldı"), [])
        self.ship()                                  # deploy bitti
        self.sync()
        incident = self.incident()
        self.assertEqual((incident.status, incident.fix_commit, incident.issue_state), ("fix_deployed", FIX, "closed"))
        self.assertEqual(len(self.comments_with("Düzeltme canlıda")), 1)
        self.sync()
        self.assertEqual(self.incident().status, "fix_deployed")  # 24 saat dolmadı
        self.age_fix(25)
        self.sync()
        incident = self.incident()
        self.assertEqual((incident.status, incident.issue_state), ("resolved", "closed"))
        self.assertEqual(self.events(), ["opened", "issue_linked", "fix_deployed", "resolved"])
        self.assertEqual(len(self.comments_with("24 saat hata tekrar görülmedi")), 1)
        self.assertEqual(self.gh.issues[1]["state"], "closed")  # kapalı kalır, kayıt silinmez

    def test_recurrence_after_fix_deployed_reopens_incident_and_issue(self):
        number = self.open_issue()
        self.gh.close(number, commit=FIX)
        self.ship()
        self.sync()
        self.assertEqual(self.incident().status, "fix_deployed")
        time.sleep(0.01)
        self.fail("Görev 3 başarısız")               # düzeltme yetmedi
        incident = self.incident()
        self.assertEqual((incident.status, incident.reopen_count), ("open", 1))
        self.assertIn("düzeltme yetmedi", [h.get("reason", "") for h in json.loads(incident.history)][-1].lower())
        self.sync()
        self.assertEqual(self.gh.issues[1]["state"], "open")
        self.assertEqual(self.incident().issue_state, "open")
        self.assertEqual(len(self.comments_with("Hata tekrar görüldü")), 1)

    def test_error_after_deploy_but_before_sync_reopens_instead_of_marking_fixed(self):
        number = self.open_issue()
        self.gh.close(number, commit=FIX)
        self.gh.deployed.add(FIX)
        self.deploy("2" * 7, at=time.time() - 3600)  # düzeltme 1 saat önce yayına çıktı
        self.fail("Görev 4 başarısız")                # yayından sonra tekrar görüldü
        self.sync()
        self.assertEqual((self.gh.issues[1]["state"], self.incident().status), ("open", "open"))
        self.assertEqual(len(self.comments_with("Düzeltme yetmedi")), 1)

    def test_manual_close_resolves_without_verification_and_manual_reopen_reopens(self):
        number = self.open_issue()
        self.gh.close(number)                         # commit yok: elle kapatıldı
        self.sync()
        incident = self.incident()
        self.assertEqual(incident.status, "resolved")
        self.assertIn("doğrulama yok", incident.resolution)
        self.gh.reopen(number)                        # issue elle yeniden açıldı
        self.sync()
        incident = self.incident()
        self.assertEqual((incident.status, incident.issue_state, incident.reopen_count), ("open", "open", 1))
        self.assertIn("issue_reopened", self.events())

    def test_manual_close_then_error_reopens_issue(self):
        number = self.open_issue()
        time.sleep(0.01)
        self.gh.close(number)
        time.sleep(0.01)
        self.fail("Görev 9 başarısız")
        self.sync()
        self.assertEqual(self.gh.issues[1]["state"], "open")
        self.assertEqual(self.incident().status, "open")

    def test_issue_reopened_while_fix_is_observed(self):
        number = self.open_issue()
        self.gh.close(number, commit=FIX)
        self.ship()
        self.sync()
        self.assertEqual(self.incident().status, "fix_deployed")
        self.gh.reopen(number)
        self.sync()
        self.assertEqual((self.incident().status, self.incident().issue_state), ("open", "open"))

    def test_auto_resolved_problem_closes_its_issue(self):
        with self.factory() as session:
            ident = logstore.raise_problem(session, "backup_stale", "Sunucu dışı yedek eskidi", "40 saat")
        self.sync()
        self.assertEqual(self.incident().issue_number, 1)
        with self.factory() as session:
            logstore.clear_problem(session, "backup_stale", "Koşul 30 dakikadır sağlanmıyor; otomatik çözülür.")
        self.sync()
        self.assertEqual(self.gh.issues[1]["state"], "closed")
        self.assertEqual(len(self.comments_with("Koşul 30 dakikadır")), 1)
        self.assertEqual((self.incident().status, self.incident().issue_state), ("resolved", "closed"))
        with self.factory() as session:
            logstore.raise_problem(session, "backup_stale", "Sunucu dışı yedek eskidi", "tekrar")
        self.sync()
        self.assertEqual((self.gh.issues[1]["state"], self.incident().status), ("open", "open"))

    def test_one_failing_incident_does_not_block_others(self):
        self.fail("Birinci hata")
        logstore.store("error", "linko.other", "İkinci hata")
        self.sync()
        calls = {"n": 0}
        original = self.gh.handle

        def flaky(method, path, body):
            if method == "GET" and path == "/issues/1":
                calls["n"] += 1
                raise RuntimeError("GitHub geçici hata")
            return original(method, path, body)
        self.gh.handle = flaky
        self.gh.close(2)
        with self.assertRaises(SystemExit):
            self.sync()
        self.assertTrue(calls["n"] >= 1)
        with self.factory() as session:
            self.assertEqual(session.query(Incident).filter_by(logger="linko.other").one().status, "resolved")

    def test_context_endpoint_returns_surrounding_logs_and_events(self):
        now = datetime.utcnow()
        logstore.store("info", "linko", "hatadan önce", created_at=now - timedelta(minutes=5))
        logstore.store("info", "linko", "çok eski", created_at=now - timedelta(hours=3))
        self.fail()
        with self.factory() as session:
            session.add(SearchEvent(run_id="r1", kind="request_finished", level="warning", data=json.dumps({"status": 429}),
                                    created_at=now + timedelta(minutes=1)))
            session.commit()
        ident = self.incident().id
        reply = self.client.get(f"/api/v1/incidents/{ident}/context?window=10m", headers=ADMIN)
        self.assertEqual(reply.status_code, 200, reply.json)
        items = reply.json["items"]
        self.assertEqual([i["source"] for i in items], ["app", "app", "events"])
        self.assertEqual(items[0]["message"], "hatadan önce")
        self.assertEqual(items[2]["data"], {"status": 429})
        self.assertNotIn("çok eski", [i.get("message") for i in items])
        self.assertEqual(self.client.get(f"/api/v1/incidents/{ident}/context?window=7h", headers=ADMIN).status_code, 400)
        self.assertEqual(self.client.get(f"/api/v1/incidents/{ident}/context?window=abc", headers=ADMIN).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/incidents/999/context", headers=ADMIN).status_code, 404)

    def test_list_filters_and_action_validation(self):
        number = self.open_issue()
        self.assertEqual(self.client.get("/api/v1/incidents?issue_state=open", headers=ADMIN).json["items"][0]["issue_number"], number)
        self.assertEqual(self.client.get("/api/v1/incidents?issue_state=closed", headers=ADMIN).json["items"], [])
        self.assertEqual(self.client.get("/api/v1/incidents?status=fix_deployed", headers=ADMIN).json["items"], [])
        self.assertEqual(self.client.get("/api/v1/incidents?issue_state=x", headers=ADMIN).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/incidents?status=x", headers=ADMIN).status_code, 400)
        listing = self.client.get("/api/v1/incidents", headers=ADMIN).json
        self.assertEqual(listing["version"]["sha"], "1111111")
        bad = self.client.post(f"/api/v1/incidents/{self.incident().id}", headers=ADMIN,
                               json={"action": "fix_deployed", "fix_commit": FIX, "deployed_at": "dün"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.post(f"/api/v1/incidents/{self.incident().id}", headers=ADMIN, json={"action": "sil"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
