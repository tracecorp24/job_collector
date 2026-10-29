#!/usr/bin/env bash
# Doğrulanmış VACUUM INTO kopyası; başarısızlıkta önceki kod + DB'ye dönüş.
set -euo pipefail
exec 9>/run/linko-deploy.lock
flock -n 9 || { echo "Başka bir deploy sürüyor."; exit 1; }
APP=/opt/linko
DATA=/var/lib/linko
SAFETY=/usr/local/lib/linko-deploy-safety.py
SMOKE=/usr/local/lib/linko-deploy-smoke.py
BACKUPS=$DATA/backups
mkdir -p "$BACKUPS"
cd "$APP"
PREV=$(git rev-parse HEAD)
git fetch -q origin main
NEXT=$(git rev-parse origin/main)
STAMP=$(date -u +%Y%m%dT%H%M%S)
SNAPSHOT="$BACKUPS/jobs-$STAMP-$PREV.db"
python3 "$SAFETY" snapshot --database "$DATA/jobs.db" --destination "$SNAPSHOT" --sha "$PREV"
chown linko:linko "$SNAPSHOT" "$SNAPSHOT.json"
write_version() {
    python3 - "$DATA" "$(git rev-parse HEAD)" <<'PY'
import json, os, sys, time
data, sha = sys.argv[1:]
info = {'sha': sha[:7], 'full_sha': sha, 'deployed_at': time.time()}
temporary = os.path.join(data, 'version.json.tmp')
with open(temporary, 'w', encoding='utf-8') as output:
    json.dump(info, output)
os.replace(temporary, os.path.join(data, 'version.json'))
with open(os.path.join(data, 'deploy_history.jsonl'), 'a', encoding='utf-8') as output:
    output.write(json.dumps(info) + '\n')
PY
    chown linko:linko "$DATA/version.json" "$DATA/deploy_history.jsonl"
}
rollback() {
    trap - ERR
    set +e
    echo "Deploy başarısız; önceki SHA ve DB geri yükleniyor: $PREV" >&2
    systemctl stop linko
    git reset -q --hard "$PREV"
    if ! python3 "$SAFETY" restore --backup "$SNAPSHOT" --database "$DATA/jobs.db"; then
        echo "DB geri yüklenemedi; servis kapalı bırakıldı. Yedek: $SNAPSHOT" >&2
        exit 1
    fi
    chown linko:linko "$DATA/jobs.db"
    .venv/bin/python -m pip install -q -r requirements.txt
    write_version
    systemctl start linko
    /usr/local/bin/linko-spool deploy error "Deploy geri alındı" "Önceki kod ve DB geri yüklendi: $PREV" || true
    exit 1
}
trap rollback ERR
systemctl stop linko
git reset -q --hard "$NEXT"
.venv/bin/python -m pip install -q -r requirements.txt
write_version
systemctl start linko
healthy=0
deadline=$((SECONDS + 30))
while (( SECONDS < deadline )); do
    if curl -fsS --max-time 2 http://127.0.0.1:8016/healthz >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 1
done
(( healthy == 1 ))
python3 "$SMOKE" --sha "$NEXT"
trap - ERR
bash "$APP/deploy/install-ops.sh"
echo "Deploy tamam: $NEXT; doğrulanmış geri alma kopyası: $SNAPSHOT"
