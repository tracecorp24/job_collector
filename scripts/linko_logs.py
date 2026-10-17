"""Canlı sitenin loglarını ve hata kayıtlarını yerelden sorgular / indirir.

Ayar: ortam değişkenleri ya da gitignore'daki `.local/linko_cli.env` (KEY=VALUE satırları)
  LINKO_URL        varsayılan https://job.ai-org.online
  LINKO_LOG_KEY    sunucudaki JOBAPP_LOG_KEY (geçişte LINKO_ADMIN_KEY de kabul edilir)

Örnekler:
  python scripts/linko_logs.py logs --since 2h --level warning
  python scripts/linko_logs.py logs --source events --since 30m --q 429
  python scripts/linko_logs.py follow
  python scripts/linko_logs.py download --since 2026-10-17T00:00:00Z --until 2026-10-18T00:00:00Z
  python scripts/linko_logs.py incidents --status all
  python scripts/linko_logs.py incident 3
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / ".local" / "linko_cli.env"


def settings():
    values = {}
    if SETTINGS.exists():
        for line in SETTINGS.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    url = os.environ.get("LINKO_URL") or values.get("LINKO_URL") or "https://job.ai-org.online"
    key = next((v for v in (os.environ.get("LINKO_LOG_KEY"), values.get("LINKO_LOG_KEY"),
                            os.environ.get("LINKO_ADMIN_KEY"), values.get("LINKO_ADMIN_KEY")) if v), None)
    if not key:
        sys.exit(f"LINKO_LOG_KEY bulunamadı. Ortam değişkeni verin veya {SETTINGS} dosyasına yazın.")
    return url.rstrip("/"), key


def call(path, params=None, stream=False):
    url, key = settings()
    response = requests.get(url + path, params={k: v for k, v in (params or {}).items() if v not in (None, "")},
                            headers={"Authorization": "Bearer " + key}, timeout=60, stream=stream)
    if response.status_code != 200:
        try:
            message = response.json().get("error")
        except ValueError:
            message = response.text[:300]
        sys.exit(f"HTTP {response.status_code}: {message}")
    return response


def line(item):
    if "message" in item:
        text = f"{item['ts']} {item['level'].upper():8} {item['logger']}: {item['message']}"
        if item.get("incident_id"):
            text += f"  [hata #{item['incident_id']}]"
        if item.get("traceback"):
            text += "\n" + item["traceback"]
        return text
    return f"{item['ts']} {item['level'].upper():8} {item['kind']} run={(item.get('run_id') or '-')[:8]} {json.dumps(item['data'], ensure_ascii=False)[:400]}"


def filters(args):
    return dict(source=args.source, since=args.since, until=getattr(args, "until", None), level=args.level,
                q=args.q, logger=args.logger, run_id=args.run_id, kind=args.kind)


def cmd_logs(args):
    params = dict(filters(args), limit=args.limit, order="desc")
    items = call("/api/v1/logs", params).json()["items"]
    for item in reversed(items):
        print(line(item))
    if not items:
        print("Kayıt yok.")


def cmd_follow(args):
    params = dict(filters(args), limit=1, order="desc")
    latest = call("/api/v1/logs", params).json()["items"]
    after = latest[0]["id"] if latest else 0
    print(f"Takip ediliyor ({args.source}); çıkmak için Ctrl+C.")
    while True:
        page = call("/api/v1/logs", dict(filters(args), after_id=after, limit=500)).json()
        for item in page["items"]:
            print(line(item), flush=True)
        after = page["next_after_id"]
        if not page["has_more"]:
            time.sleep(args.interval)


def cmd_download(args):
    response = call("/api/v1/logs/export", filters(args), stream=True)
    name = response.headers.get("Content-Disposition", "").split('filename="')[-1].rstrip('"') or "linko-logs.jsonl"
    target = Path(args.output) if args.output else ROOT / ".local" / "logs" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("wb") as file:
        for chunk in response.iter_lines():
            if chunk:
                file.write(chunk + b"\n")
                count += 1
    print(f"{count} kayıt indirildi: {target}")


def cmd_incidents(args):
    items = call("/api/v1/incidents", dict(status=args.status)).json()["items"]
    for i in items:
        issue = f"#{i['issue_number']}" if i["issue_number"] else "issue yok"
        print(f"[{i['id']}] {i['status']:12} {i['kind']:8} x{i['count']:<5} son: {i['last_seen']}  {issue}  {i['title']}")
    if not items:
        print("Hata kaydı yok.")


def cmd_incident(args):
    if args.context:
        data = call(f"/api/v1/incidents/{args.id}/context", dict(window=args.context)).json()
        print(f"Hata kaydı #{args.id} anı: {data['anchor']} (±{data['window']})")
        for item in data["items"]:
            print(f"[{item['source']:6}] {line(item)}")
        if not data["items"]:
            print("Bu aralıkta kayıt yok.")
        return
    data = call(f"/api/v1/incidents/{args.id}").json()
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Linko canlı log ve hata kaydı istemcisi")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, since=None):
        p.add_argument("--source", choices=("app", "events"), default="app", help="app: sunucu logu, events: arama işlem kayıtları")
        p.add_argument("--since", default=since, help="ISO 8601 (UTC varsayılır) veya 30m / 2h / 7d")
        p.add_argument("--level", choices=("debug", "info", "warning", "error", "critical"), help="en az bu seviye")
        p.add_argument("--q", help="metin araması")
        p.add_argument("--logger", help="app için logger öneki (ör. linko.audit)")
        p.add_argument("--run-id", help="events için süreç kimliği")
        p.add_argument("--kind", help="events için olay türü (ör. request_finished)")

    p = sub.add_parser("logs", help="son kayıtları listele")
    common(p, "1h")
    p.add_argument("--until")
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=cmd_logs)
    p = sub.add_parser("follow", help="yeni kayıtları canlı izle")
    common(p)
    p.add_argument("--interval", type=float, default=10.0)
    p.set_defaults(func=cmd_follow)
    p = sub.add_parser("download", help="aralığı JSONL olarak indir (en fazla 31 gün)")
    common(p)
    p.add_argument("--until")
    p.add_argument("-o", "--output", help="hedef dosya (varsayılan .local/logs/)")
    p.set_defaults(func=cmd_download)
    p = sub.add_parser("incidents", help="hata kayıtları")
    p.add_argument("--status", choices=("open", "fix_deployed", "resolved", "all"), default="open")
    p.set_defaults(func=cmd_incidents)
    p = sub.add_parser("incident", help="tek hata kaydının ayrıntısı")
    p.add_argument("id", type=int)
    p.add_argument("--context", metavar="PENCERE", help="hata anının ± penceresindeki loglar ve arama olayları (ör. 10m, 1h; en fazla 6h)")
    p.set_defaults(func=cmd_incident)
    args = parser.parse_args(argv)
    if args.command == "download" and not args.since:
        parser.error("download için --since gerekli.")
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
