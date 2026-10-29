"""Canlı uçlara yalnızca salt okunur dağıtım kontrolleri gönderir."""
import argparse
import json
from pathlib import Path
import shlex
import urllib.error
import urllib.request


def environment(path):
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip().removeprefix("export ")
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        parts = shlex.split(value, comments=True)
        values[name.strip()] = " ".join(parts)
    return values


def probe(base_url, values, expected_sha=None, strict=True):
    if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Dağıtım probu yalnızca loopback adresinde çalışır.")
    def get(path, key=None):
        request = urllib.request.Request(base_url.rstrip("/") + path)
        if key:
            request.add_header("Authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read(1024 * 1024)
        except urllib.error.HTTPError as response:
            response.close()
            return response.code, b""
    status, body = get("/healthz")
    if status != 200:
        raise ValueError("Sağlık probu başarısız.")
    health = json.loads(body)
    if expected_sha and health.get("version") != expected_sha[:7]:
        raise ValueError("Canlı sürüm beklenen SHA ile eşleşmiyor.")
    if get("/")[0] != 200:
        raise ValueError("Ana sayfa probu başarısız.")
    if strict and get("/api/facets")[0] != 401:
        raise ValueError("Anahtarsız yönetim isteği reddedilmedi.")
    key = values.get("JOBAPP_API_KEY") or values.get("JOBAPP_ADMIN_KEY")
    if not key or get("/api/v1/jobs?limit=1", key)[0] != 200:
        raise ValueError("Anahtarlı veri API'si probu başarısız.")
    return {"health": "ok", "version": health.get("version"), "api": "ok", "fail_closed": strict}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8016")
    parser.add_argument("--env-file", default="/etc/linko.env")
    parser.add_argument("--sha")
    parser.add_argument("--legacy-auth", action="store_true")
    args = parser.parse_args()
    print(json.dumps(probe(args.base_url, environment(args.env_file), args.sha, not args.legacy_auth)))


if __name__ == "__main__":
    main()
