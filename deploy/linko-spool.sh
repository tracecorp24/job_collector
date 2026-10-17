#!/usr/bin/env bash
# VPS'te /usr/local/bin/linko-spool olarak kurulur (deploy/install-ops.sh).
# Süreç dışı bir olayı (deploy geri alma, yedek hatası, servis çökmesi) uygulamanın okuyacağı
# olay klasörüne bırakır; uygulama başlayınca/çalışırken `kind=external` hata kaydı olarak içeri alır.
# Kullanım: linko-spool <kaynak> <seviye: error|critical> <sabit başlık> [ileti]
# Başlık aynı olayın tekrarlarını tek kayıtta toplar; değişken ayrıntılar iletiye yazılır.
set -euo pipefail
[ $# -ge 3 ] || { echo "Kullanım: linko-spool <kaynak> <seviye> <başlık> [ileti]" >&2; exit 2; }
SPOOL=${LINKO_SPOOL:-/var/lib/linko/spool}
OWNER=${LINKO_OWNER:-linko}
GROUP=${LINKO_GROUP:-$OWNER}
install -d -o "$OWNER" -g "$GROUP" "$SPOOL"
python3 - "$SPOOL" "$@" <<'PY'
import json, os, sys, time
spool, source, level, title = sys.argv[1:5]
message = sys.argv[5] if len(sys.argv) > 5 else ""
line = {"source": source, "level": level, "title": title, "message": message[-4000:], "at": time.time()}
path = os.path.join(spool, "external-%s.jsonl" % time.strftime("%Y%m%d", time.gmtime()))
with open(path, "a", encoding="utf-8") as file:
    file.write(json.dumps(line, ensure_ascii=False) + chr(10))
PY
chown "$OWNER:$GROUP" "$SPOOL"/external-*.jsonl 2>/dev/null || true
