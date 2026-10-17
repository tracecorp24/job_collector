#!/usr/bin/env bash
# VPS'te /usr/local/bin/linko-backup olarak kurulur; linko-backup.timer günde bir çalıştırır.
# Veritabanının sıkıştırılmış kopyasını ayrı, private bir GitHub reposuna gönderir.
# Repo geçmişi her seferinde tek commit'e indirilir; son 7 günün kopyası tutulur.
set -euo pipefail
exec 9>/run/linko-backup.lock
flock -n 9 || { echo "Başka bir yedekleme sürüyor."; exit 1; }

# Sonuç servis panelinde görünsün diye durum dosyasına yazılır.
status() { printf '{"ok":%s,"at":%s,"message":"%s","size":"%s"}
' "$1" "$(date +%s)" "$2" "${3:-}" > "$STATUS.tmp" && chown linko:linko "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"; }
alert() { /usr/local/bin/linko-spool backup error "Sunucu dışı yedek başarısız" "$1" || true; }
trap 'status false "Yedekleme başarısız (satır $LINENO); journalctl -u linko-backup"; alert "Yedekleme başarısız (satır $LINENO); journalctl -u linko-backup"' ERR

DB=/var/lib/linko/jobs.db
STATUS=/var/lib/linko/backup_status.json
WORK=/var/lib/linko-offsite
REMOTE=git@github-backup:tracecorp24/job_collector-backups.git
KEEP=7

[ -d "$WORK/.git" ] || git clone -q "$REMOTE" "$WORK" 2>/dev/null || { mkdir -p "$WORK"; git -C "$WORK" init -q -b main; git -C "$WORK" remote add origin "$REMOTE"; }
cd "$WORK"
git config user.name "linko-vps"
git config user.email "linko-vps@users.noreply.github.com"

STAMP=$(date -u +%Y%m%d)
TMP=$(mktemp /tmp/linko-backup.XXXXXX.db)
trap 'rm -f "$TMP"' EXIT
sqlite3 -cmd ".timeout 30000" "$DB" ".backup '$TMP'"
sqlite3 "$TMP" "PRAGMA integrity_check;" | grep -qx ok || { echo "Bütünlük kontrolü başarısız, yedek gönderilmedi." >&2; status false "Bütünlük kontrolü başarısız, yedek gönderilmedi"; alert "Bütünlük kontrolü başarısız, yedek gönderilmedi"; exit 1; }
gzip -9 -c "$TMP" > "jobs-$STAMP.db.gz"
ls -1 jobs-*.db.gz | sort | head -n -"$KEEP" | xargs -r rm -f

cat > README.md <<EOF
# Linko veritabanı yedekleri

Son güncelleme: $(date -u '+%Y-%m-%d %H:%M UTC')

Her gün VPS'ten otomatik gönderilir, son $KEEP gün tutulur.
Geri yükleme: \`gunzip -c jobs-YYYYMMDD.db.gz > jobs.db\`
EOF

git checkout -q --orphan snapshot
git add -A
git commit -q -m "Yedek $STAMP"
git branch -q -D main 2>/dev/null || true
git branch -q -m main
git push -q -f origin main
SIZE=$(du -h "jobs-$STAMP.db.gz" | cut -f1)
status true "jobs-$STAMP.db.gz GitHub'a gönderildi" "$SIZE"
echo "Yedek gönderildi: jobs-$STAMP.db.gz ($SIZE)"
