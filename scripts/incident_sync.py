"""Hata kayıtlarını GitHub issue'larıyla eşler (yalnızca standart kütüphane; Actions'ta çalışır).

Hata kaydı durumları: açık → (issue kapandı, kapatan commit canlıda) düzeltme yayında → (24 saat tekrar
yok) çözüldü. Her aşamada hata tekrar görülürse kayıt yeniden açılır ve issue yeniden açılır.

1. Issue'su olmayan açık hata kaydı → `hata-kaydı` etiketli yeni issue (tur başına en fazla 5; fazlası
   tek "taşkın" issue'sunda listelenir, sonraki turlarda normal issue olur).
2. Issue kapandı:
   - `Fixes #N` commit'iyle kapandıysa: commit canlıya çıkana kadar beklenir; çıktıysa kayıt "düzeltme
     yayında" olur. Yayından sonra hata yine görüldüyse issue yeniden açılır ("düzeltme yetmedi").
   - Elle kapatıldıysa (commit yok): tekrar görülmediyse kayıt çözüldü, görüldüyse issue yeniden açılır.
3. Düzeltme yayında + 24 saat tekrar yok → kayıt çözüldü, issue'ya yorum.
4. Sunucuda otomatik çözülen sorunların (koşul kalktı) açık issue'ları yorumla kapatılır.
5. Çözüldü denmiş bir issue GitHub'da elle yeniden açıldıysa kayıt yeniden açık olur.
Hata kayıtları sunucuda silinmez; issue'lar da yalnızca kapatılır.

Ortam: LINKO_URL, LINKO_LOG_KEY (geçişte LINKO_ADMIN_KEY), GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

LABEL = "hata-kaydı"
MARKER = "<!-- linko-incident:{} -->"
FLOOD = "<!-- linko-flood -->"
MAX_NEW_ISSUES = 5
VERIFY_AFTER = timedelta(hours=24)
REOPEN_SWEEP_DAYS = 30
REOPEN_SWEEP_MAX = 50
SECRETS = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [gizlendi]"),
    (re.compile(r"\bgsk_[A-Za-z0-9]{8,}"), "[gizlendi]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[gizlendi]"),
    (re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret|authorization)\b(\s*[=:]\s*)[^\s,;&\"']+"), r"\1\2[gizlendi]"),
)


def redact(text):
    """Sunucu zaten maskeler; issue herkese açık olabilir diye burada ikinci kez uygulanır."""
    for pattern, replacement in SECRETS:
        text = pattern.sub(replacement, text or "")
    return text


def request(method, url, token, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
        "Content-Type": "application/json", "User-Agent": "linko-incident-sync"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{method} {url} → HTTP {error.code}: {error.read()[:300]!r}") from None


def when(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Sync:
    def __init__(self, site, key, repo, token, http=request):
        self.site, self.key, self.repo, self.token, self.http = site.rstrip("/"), key, repo, token, http
        self.api = f"https://api.github.com/repos/{repo}"
        self.live = {}
        self.errors = []

    def linko(self, method, path, body=None):
        return self.http(method, self.site + path, self.key, body)

    def github(self, method, path, body=None):
        return self.http(method, self.api + path, self.token, body)

    def guard(self, label, function, *args):
        """Bir kaydın hatası diğerlerini durdurmaz; tur sonunda başarısız sayılır."""
        try:
            return function(*args)
        except Exception as error:
            self.errors.append(f"{label}: {error}")
            print(f"UYARI {label}: {error}", file=sys.stderr)

    def comment(self, number, text):
        self.github("POST", f"/issues/{number}/comments", {"body": text})

    def set_issue(self, number, state):
        self.github("PATCH", f"/issues/{number}", {"state": state})

    def action(self, incident, **body):
        return self.linko("POST", f"/api/v1/incidents/{incident['id']}", body)

    def body(self, incident):
        sample = redact(incident["sample"])[:3000]
        return "\n".join([
            MARKER.format(incident["id"]),
            f"Canlı sitede otomatik yakalanan hata. **Hata kaydı #{incident['id']}** (`{incident['logger']}`)",
            "",
            f"- İlk görülme: {incident['first_seen']} (sürüm {incident.get('first_version') or 'bilinmiyor'})",
            f"- Son görülme: {incident['last_seen']} (sürüm {incident.get('last_version') or 'bilinmiyor'})",
            f"- Tekrar sayısı: {incident['count']}",
            "",
            "```", sample, "```",
            "",
            "Ayrıntı, iz kaydı ve hata anındaki loglar:",
            "```",
            f"python scripts/linko_logs.py incident {incident['id']}",
            f"python scripts/linko_logs.py incident {incident['id']} --context 10m",
            "```",
            "Düzelten commit'e `Fixes #<bu issue>` yazın. Issue kapanınca commit canlıya çıkana kadar beklenir, "
            "ardından 24 saat tekrar görülmezse kayıt **çözüldü** olur. Hata kaydı silinmez; tekrar görülürse bu issue yeniden açılır.",
        ])

    def ensure_label(self):
        try:
            self.github("POST", "/labels", {"name": LABEL, "color": "d73a4a", "description": "Canlı siteden otomatik hata kaydı"})
        except RuntimeError as error:
            if "HTTP 422" not in str(error):
                raise

    # --- issue kapandı: elle mi, düzeltme commit'iyle mi? -------------------------------------------------
    def closing_commit(self, number):
        events = self.github("GET", f"/issues/{number}/events?per_page=100") or []
        closed = [e for e in events if isinstance(e, dict) and e.get("event") == "closed"]
        return closed[-1].get("commit_id") if closed else None

    def deployed(self, commit):
        """Kapatan commit canlı sürümün atası (veya kendisi) mi?"""
        head = self.live.get("full_sha") or ""
        if not head or head == "bilinmiyor":
            return False
        try:
            result = self.github("GET", f"/compare/{commit}...{head}")
        except RuntimeError:
            return False
        return (result or {}).get("status") in ("ahead", "identical")

    def reopen_issue(self, incident, issue, reason):
        self.set_issue(issue["number"], "open")
        self.comment(issue["number"], reason)
        print(f"Hata kaydı #{incident['id']}: issue #{issue['number']} yeniden açıldı")

    def check_closed(self, incident):
        issue = self.github("GET", f"/issues/{incident['issue_number']}")
        if issue["state"] != "closed":
            return
        closed = when(issue.get("closed_at"))
        seen = when(incident["last_seen"])
        commit = self.closing_commit(issue["number"])
        if commit is None:
            if closed and seen > closed:
                self.reopen_issue(incident, issue, f"🔁 Issue kapatıldıktan sonra hata yine görüldü (son {incident['last_seen']}). Yeniden açıldı.")
                return
            reason = "planlanmadı olarak kapatıldı" if issue.get("state_reason") == "not_planned" else "elle kapatıldı"
            self.action(incident, action="resolve", issue_number=issue["number"],
                        resolution=f"Issue #{issue['number']} {reason} ({issue.get('closed_at')}); doğrulama yok.")
            self.comment(issue["number"], f"✅ Çözüldü. Hata kaydı #{incident['id']} \"çözüldü\" olarak saklanıyor; tekrar görülürse bu issue yeniden açılır.")
            print(f"Hata kaydı #{incident['id']} çözüldü (issue #{issue['number']}, elle kapatıldı)")
            return
        if not self.deployed(commit):
            return  # düzeltme henüz canlıda değil; bu arada görülen tekrarlar beklenendir
        deployed_at = self.live.get("deployed_at")
        deployed = when(deployed_at) or closed
        if deployed and seen > deployed:
            self.reopen_issue(incident, issue, f"🔁 Düzeltme (`{commit[:7]}`) yayınlandıktan sonra hata yine görüldü (son {incident['last_seen']}). "
                                               "Düzeltme yetmedi; yeniden açıldı.")
            return
        self.action(incident, action="fix_deployed", fix_commit=commit, issue_number=issue["number"], deployed_at=deployed_at)
        self.comment(issue["number"], f"🚀 Düzeltme canlıda (`{commit[:7]}`). 24 saat tekrar görülmezse hata kaydı #{incident['id']} çözüldü olarak işaretlenir.")
        print(f"Hata kaydı #{incident['id']}: düzeltme yayında (issue #{issue['number']}, {commit[:7]})")

    def resolve_closed(self):
        listing = self.linko("GET", "/api/v1/incidents?status=open")
        self.live = listing.get("version") or {}
        for incident in listing["items"]:
            if incident["issue_number"] and incident["issue_state"] == "open":
                self.guard(f"hata kaydı #{incident['id']}", self.check_closed, incident)

    def verify_fixes(self):
        now = datetime.now(timezone.utc)
        for incident in self.linko("GET", "/api/v1/incidents?status=fix_deployed")["items"]:
            self.guard(f"hata kaydı #{incident['id']}", self.verify_one, incident, now)

    def verify_one(self, incident, now):
        number = incident["issue_number"]
        if number and self.github("GET", f"/issues/{number}")["state"] == "open":
            self.action(incident, action="reopen")  # düzeltme beklenirken issue elle yeniden açıldı
            print(f"Hata kaydı #{incident['id']} issue #{number} elle açıldığı için yeniden açıldı")
            return
        deployed = when(incident.get("fix_deployed_at"))
        if deployed and now - deployed >= VERIFY_AFTER:
            self.action(incident, action="resolve", issue_number=number,
                        resolution=f"Düzeltme ({(incident.get('fix_commit') or '')[:7]}) yayında; 24 saat tekrar görülmedi.")
            if number:
                self.comment(number, f"✅ Çözüldü: düzeltme yayınlandı ve 24 saat hata tekrar görülmedi. Hata kaydı #{incident['id']} saklanıyor; tekrar görülürse bu issue yeniden açılır.")
            print(f"Hata kaydı #{incident['id']} çözüldü (24 saat temiz)")

    def close_auto_resolved(self):
        """Sunucuda çözülen (koşul kalktı) ama issue'su hâlâ açık olan kayıtların issue'sunu kapatır."""
        for incident in self.linko("GET", "/api/v1/incidents?status=resolved&issue_state=open")["items"]:
            self.guard(f"hata kaydı #{incident['id']}", self.close_one, incident)

    def close_one(self, incident):
        number = incident["issue_number"]
        if self.github("GET", f"/issues/{number}")["state"] == "open":
            self.comment(number, f"✅ Çözüldü: {incident['resolution']} Hata kaydı #{incident['id']} saklanıyor; tekrar görülürse bu issue yeniden açılır.")
            self.github("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": "completed"})
        self.action(incident, action="issue_closed")
        print(f"Hata kaydı #{incident['id']}: issue #{number} kapatıldı")

    def sweep_reopened(self):
        """Çözüldü denmiş ama GitHub'da elle yeniden açılmış issue'lar."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=REOPEN_SWEEP_DAYS)
        items = self.linko("GET", "/api/v1/incidents?status=resolved&issue_state=closed")["items"]
        recent = [i for i in items if i["issue_number"] and (when(i.get("resolved_at")) or cutoff) >= cutoff]
        for incident in recent[:REOPEN_SWEEP_MAX]:
            self.guard(f"hata kaydı #{incident['id']}", self.sweep_one, incident)

    def sweep_one(self, incident):
        if self.github("GET", f"/issues/{incident['issue_number']}")["state"] == "open":
            self.action(incident, action="reopen")
            print(f"Hata kaydı #{incident['id']}: issue #{incident['issue_number']} elle yeniden açıldı")

    # --- yeni issue'lar ---------------------------------------------------------------------------------
    def flood_issue(self, deferred):
        """Tur sınırını aşan kayıtlar tek "taşkın" issue'sunda listelenir; sonraki turlarda normal issue olurlar."""
        text = "\n".join(f"- Hata kaydı #{i['id']} (x{i['count']}): {redact(i['title'])[:150]}" for i in deferred)
        found = [i for i in (self.github("GET", f"/issues?labels={LABEL}&state=open&per_page=100") or [])
                 if isinstance(i, dict) and FLOOD in (i.get("body") or "")]
        if found:
            self.comment(found[0]["number"], "Sırada bekleyenler:\n" + text)
        else:
            self.github("POST", "/issues", {"title": "Hata taşkını: çok sayıda yeni hata kaydı", "labels": [LABEL],
                "body": FLOOD + f"\nBir turda {MAX_NEW_ISSUES}'den fazla yeni hata kaydı geldi; her biri için ayrı issue "
                "sonraki turlarda açılır. Sırada bekleyenler:\n" + text})
        print(f"{len(deferred)} kayıt taşkın issue'suna eklendi")

    def open_issues(self):
        created, deferred = 0, []
        for incident in self.linko("GET", "/api/v1/incidents?status=open&needs_issue=1")["items"]:
            if not incident["issue_number"] and created >= MAX_NEW_ISSUES:
                deferred.append(incident)
                continue
            if incident["issue_number"]:
                number = incident["issue_number"]
                self.set_issue(number, "open")
                self.comment(number, f"🔁 Hata tekrar görüldü (toplam {incident['count']}, son {incident['last_seen']}, sürüm "
                                     f"{incident.get('last_version') or 'bilinmiyor'}). Issue yeniden açıldı.")
            else:
                created += 1
                number = self.github("POST", "/issues", {"title": redact(incident["title"])[:200], "body": self.body(incident),
                                                          "labels": [LABEL]})["number"]
            self.action(incident, action="link", issue_number=number)
            print(f"Hata kaydı #{incident['id']} -> issue #{number}")
        if deferred:
            self.flood_issue(deferred)

    def run(self):
        self.ensure_label()
        self.guard("elle yeniden açılanlar", self.sweep_reopened)
        self.guard("otomatik çözülenler", self.close_auto_resolved)
        self.guard("kapanan issue'lar", self.resolve_closed)
        self.guard("doğrulama", self.verify_fixes)
        self.guard("yeni issue'lar", self.open_issues)
        if self.errors:
            sys.exit(f"{len(self.errors)} adım başarısız oldu.")


def main():
    key = os.environ.get("LINKO_LOG_KEY") or os.environ.get("LINKO_ADMIN_KEY")
    missing = [k for k in ("LINKO_URL", "GITHUB_TOKEN", "GITHUB_REPOSITORY") if not os.environ.get(k)] + ([] if key else ["LINKO_LOG_KEY"])
    if missing:
        sys.exit("Eksik ortam değişkeni: " + ", ".join(missing))
    Sync(os.environ["LINKO_URL"], key, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]).run()


if __name__ == "__main__":
    main()
