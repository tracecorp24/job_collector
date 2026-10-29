"""Diğer siteleri ve Basic Auth hesabını koruyarak Linko proxy yollarını günceller."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

try:
    from .smoke import environment
except ImportError:
    from smoke import environment

BEGIN = "# BEGIN LINKO MANAGED PROXY"
END = "# END LINKO MANAGED PROXY"


def render(source, sse=False):
    events = ""
    if sse:
        events = '''
    @linko_events path /events
    handle @linko_events {
        reverse_proxy 127.0.0.1:8018 {
            header_up Authorization "Bearer {$JOBAPP_ADMIN_KEY}"
            header_up X-Real-IP {remote_host}
            flush_interval -1
        }
    }
'''
    managed = BEGIN + '''
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
''' + events + '''
    @linko_api path /api/v1/*
    handle @linko_api {
        reverse_proxy 127.0.0.1:8016 {
            header_up X-Real-IP {remote_host}
            flush_interval -1
        }
    }
    handle {
        reverse_proxy 127.0.0.1:8016 {
            header_up Authorization "Bearer {$JOBAPP_ADMIN_KEY}"
            header_up X-Real-IP {remote_host}
            flush_interval -1
        }
    }
    ''' + END
    if BEGIN in source:
        result, count = re.subn(re.escape(BEGIN) + r".*?" + re.escape(END), lambda match: managed, source, flags=re.S)
    else:
        result, count = re.subn(r"reverse_proxy 127\.0\.0\.1:8016\s*\{[^{}]*\}", lambda match: managed, source)
    if count != 1:
        raise ValueError("Tek bir Linko proxy bloğu bulunmalı; yapılandırma değiştirilmedi.")
    return result


def install(path, env_file, sse=False):
    path = Path(path).resolve(strict=True)
    source = path.read_text(encoding="utf-8")
    values = environment(env_file)
    if not values.get("JOBAPP_ADMIN_KEY"):
        raise ValueError("Mevcut yönetim anahtarı ortamda bulunamadı; yapılandırma değiştirilmedi.")
    updated = render(source, sse)
    if updated == source:
        print("Caddy proxy kuralları zaten güncel.")
        return
    environment_values = dict(os.environ, **values)
    descriptor, name = tempfile.mkstemp(prefix="linko-caddy-", dir=path.parent)
    os.close(descriptor)
    candidate = Path(name)
    backup = path.with_name(path.name + ".before-linko-" + str(time.time_ns()))
    dropin = Path("/etc/systemd/system/caddy.service.d/linko-upstream.conf")
    previous_dropin = dropin.read_bytes() if dropin.exists() else None
    try:
        candidate.write_text(updated, encoding="utf-8")
        stat = path.stat()
        os.chmod(candidate, stat.st_mode & 0o777)
        os.chown(candidate, stat.st_uid, stat.st_gid)
        validation = subprocess.run(["caddy", "validate", "--config", str(candidate), "--adapter", "caddyfile"],
                                    env=environment_values, capture_output=True)
        if validation.returncode:
            raise ValueError("Caddy doğrulaması başarısız; çalışan yapılandırma korundu.")
        shutil.copy2(path, backup)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text("[Service]\nEnvironmentFile=/etc/linko.env\n", encoding="utf-8")
        os.replace(candidate, path)
        try:
            subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True)
            subprocess.run(["caddy", "reload", "--config", str(path), "--adapter", "caddyfile"],
                           env=environment_values, check=True, capture_output=True)
        except subprocess.CalledProcessError:
            shutil.copy2(backup, path)
            if previous_dropin is not None:
                dropin.write_bytes(previous_dropin)
            else:
                dropin.unlink(missing_ok=True)
            subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
            subprocess.run(["caddy", "reload", "--config", str(path), "--adapter", "caddyfile"],
                           env=environment_values, capture_output=True)
            raise ValueError("Caddy yüklenemedi; önceki yapılandırmaya dönüldü.") from None
        print("Caddy güncellendi; Basic Auth hesabı ve diğer site blokları korundu.")
    finally:
        candidate.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/caddy/Caddyfile")
    parser.add_argument("--env-file", default="/etc/linko.env")
    parser.add_argument("--sse", action="store_true")
    args = parser.parse_args()
    install(args.config, args.env_file, args.sse)
