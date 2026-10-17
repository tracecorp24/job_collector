#!/usr/bin/env bash
# VPS'te /usr/local/bin/linko-deploy olarak kurulur. GitHub Actions'ın anahtarı
# authorized_keys içinde command= ile yalnızca bu scripte bağlıdır.
set -euo pipefail
exec 9>/run/linko-deploy.lock
flock -n 9 || { echo "Başka bir deploy sürüyor."; exit 1; }

APP=/opt/linko
DATA=/var/lib/linko
BACKUPS=$DATA/backups

mkdir -p "$BACKUPS"
sqlite3 "$DATA/jobs.db" ".backup '$BACKUPS/jobs-$(date +%Y%m%d-%H%M%S).db'"
ls -1t "$BACKUPS"/jobs-*.db | tail -n +11 | xargs -r rm -f
chown -R linko:linko "$BACKUPS"

# Hangi sürümün canlıda olduğu uygulamaya ve hata kayıtlarına bu dosyadan yansır (linko kullanıcısı git'i okuyamaz).
write_version() {
    python3 - "$DATA" "$(git rev-parse HEAD)" "$(git log -1 --format=%s)" <<'PY'
import json, os, sys, time
data, sha, subject = sys.argv[1:4]
info = {"sha": sha[:7], "full_sha": sha, "subject": subject, "deployed_at": time.time()}
tmp = os.path.join(data, "version.json.tmp")
with open(tmp, "w", encoding="utf-8") as file:
    json.dump(info, file, ensure_ascii=False)
os.replace(tmp, os.path.join(data, "version.json"))
with open(os.path.join(data, "deploy_history.jsonl"), "a", encoding="utf-8") as file:
    file.write(json.dumps(info, ensure_ascii=False) + chr(10))
PY
    chown linko:linko "$DATA/version.json" "$DATA/deploy_history.jsonl"
}

cd "$APP"
PREV=$(git rev-parse HEAD)
git fetch -q origin main
git reset -q --hard origin/main
write_version
.venv/bin/pip install -q -r requirements.txt
systemctl restart linko

for _ in $(seq 1 12); do
    sleep 5
    if curl -fsS http://127.0.0.1:8016/healthz >/dev/null 2>&1; then
        echo "Deploy tamam: $(git log -1 --format='%h %s')"
        exit 0
    fi
done

echo "Sağlık kontrolü başarısız, $PREV sürümüne geri dönülüyor." >&2
journalctl -u linko -n 30 --no-pager >&2 || true
# Geri alma uygulamaya hata kaydı olarak ulaşsın (başlık sabit: tekrarlar tek kayıtta sayılır).
/usr/local/bin/linko-spool deploy error "Deploy geri alındı"     "Başarısız sürüm: $(git rev-parse --short HEAD), geri dönülen: ${PREV:0:7}
$(journalctl -u linko -n 30 --no-pager 2>&1)" || true
git reset -q --hard "$PREV"
write_version
.venv/bin/pip install -q -r requirements.txt
systemctl restart linko
exit 1
