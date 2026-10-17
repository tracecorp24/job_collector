"""Hata kayıtlarını GitHub issue'larıyla eşler (yalnızca standart kütüphane; Actions'ta çalışır).

1. Issue'su olmayan açık hata kaydı → `hata-kaydı` etiketli yeni issue (tur başına en fazla 5; fazlası
   tek "taşkın" issue'sunda listelenir, sonraki turlarda normal issue olur).
2. Çözüldükten sonra tekrar görülen kayıt → kapalı issue yeniden açılır, yorum eklenir.
3. Issue kapatıldıysa ve hata kapanıştan sonra görülmediyse → kayıt "çözüldü" olur, issue'ya yorum düşülür.
   Kapanıştan sonra tekrar görüldüyse issue yeniden açılır.
Hata kayıtları sunucuda silinmez; issue'lar da yalnızca kapatılır.

Ortam: LINKO_URL, LINKO_ADMIN_KEY, GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

LABEL = "hata-kaydı"
MARKER = "<!-- linko-incident:{} -->"
FLOOD = "<!-- linko-flood -->"
MAX_NEW_ISSUES = 5
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
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


class Sync:
    def __init__(self, site, key, repo, token, http=request):
        self.site, self.key, self.repo, self.token, self.http = site.rstrip("/"), key, repo, token, http
        self.api = f"https://api.github.com/repos/{repo}"

    def linko(self, method, path, body=None):
        return self.http(method, self.site + path, self.key, body)

    def github(self, method, path, body=None):
        return self.http(method, self.api + path, self.token, body)

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
            "Ayrıntı ve iz kaydı:",
            "```",
            f"python scripts/linko_logs.py incident {incident['id']}",
            f"python scripts/linko_logs.py logs --since 7d --q \"{redact(incident['title'])[:40]}\"",
            "```",
            "Düzelten commit'e `Fixes #<bu issue>` yazın; issue kapanınca kayıt **çözüldü** olarak işaretlenir. "
            "Hata kaydı silinmez; tekrar görülürse bu issue yeniden açılır.",
        ])

    def ensure_label(self):
        try:
            self.github("POST", "/labels", {"name": LABEL, "color": "d73a4a", "description": "Canlı siteden otomatik hata kaydı"})
        except RuntimeError as error:
            if "HTTP 422" not in str(error):
                raise

    def flood_issue(self, deferred):
        """Tur sınırını aşan kayıtlar tek "taşkın" issue'sunda listelenir; sonraki turlarda normal issue olurlar."""
        text = "\n".join(f"- Hata kaydı #{i['id']} (x{i['count']}): {redact(i['title'])[:150]}" for i in deferred)
        found = [i for i in (self.github("GET", f"/issues?labels={LABEL}&state=open&per_page=100") or [])
                 if isinstance(i, dict) and FLOOD in (i.get("body") or "")]
        if found:
            self.github("POST", f"/issues/{found[0]['number']}/comments", {"body": "Sırada bekleyenler:\n" + text})
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
                self.github("PATCH", f"/issues/{number}", {"state": "open"})
                self.github("POST", f"/issues/{number}/comments", {"body":
                    f"🔁 Hata tekrar görüldü (toplam {incident['count']}, son {incident['last_seen']}). Issue yeniden açıldı."})
            else:
                created += 1
                number = self.github("POST", "/issues", {"title": redact(incident["title"])[:200], "body": self.body(incident),
                                                          "labels": [LABEL]})["number"]
            self.linko("POST", f"/api/v1/incidents/{incident['id']}", {"action": "link", "issue_number": number})
            print(f"Hata kaydı #{incident['id']} -> issue #{number}")
        if deferred:
            self.flood_issue(deferred)

    def resolve_closed(self):
        for incident in self.linko("GET", "/api/v1/incidents?status=open")["items"]:
            if not incident["issue_number"] or incident["issue_state"] != "open":
                continue
            issue = self.github("GET", f"/issues/{incident['issue_number']}")
            if issue["state"] != "closed":
                continue
            closed = when(issue.get("closed_at"))
            if closed and when(incident["last_seen"]) > closed:
                self.github("PATCH", f"/issues/{issue['number']}", {"state": "open"})
                self.github("POST", f"/issues/{issue['number']}/comments", {"body":
                    f"🔁 Issue kapatıldıktan sonra hata yine görüldü (son {incident['last_seen']}). Yeniden açıldı."})
                continue
            reason = "planlanmadı olarak kapatıldı" if issue.get("state_reason") == "not_planned" else "kapatıldı"
            self.linko("POST", f"/api/v1/incidents/{incident['id']}", {"action": "resolve", "issue_number": issue["number"],
                       "resolution": f"Issue #{issue['number']} {reason} ({issue.get('closed_at')})."})
            self.github("POST", f"/issues/{issue['number']}/comments", {"body":
                f"✅ Çözüldü. Hata kaydı #{incident['id']} sistemde \"çözüldü\" olarak saklanıyor; tekrar görülürse bu issue yeniden açılır."})
            print(f"Hata kaydı #{incident['id']} çözüldü (issue #{issue['number']})")

    def run(self):
        self.ensure_label()
        self.resolve_closed()
        self.open_issues()


def main():
    missing = [k for k in ("LINKO_URL", "LINKO_ADMIN_KEY", "GITHUB_TOKEN", "GITHUB_REPOSITORY") if not os.environ.get(k)]
    if missing:
        sys.exit("Eksik ortam değişkeni: " + ", ".join(missing))
    Sync(os.environ["LINKO_URL"], os.environ["LINKO_ADMIN_KEY"], os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]).run()


if __name__ == "__main__":
    main()
