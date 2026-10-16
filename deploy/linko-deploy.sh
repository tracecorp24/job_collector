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

cd "$APP"
PREV=$(git rev-parse HEAD)
git fetch -q origin main
git reset -q --hard origin/main
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
git reset -q --hard "$PREV"
.venv/bin/pip install -q -r requirements.txt
systemctl restart linko
exit 1
