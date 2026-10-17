#!/usr/bin/env bash
# Sunucuda root olarak çalıştırılır: depodaki işletim betiklerini ve servis tanımını kurar.
# Bu dosyalar /usr/local/bin ve /etc/systemd altında KOPYA olarak durur; deploy onları güncellemez.
# Kullanım:  ssh root@38.45.81.29 'bash /opt/linko/deploy/install-ops.sh'
# Servisi yeniden başlatmaz; bir sonraki deploy yeni servis tanımını uygular.
set -euo pipefail
SRC=/opt/linko/deploy
for name in linko-deploy linko-backup linko-spool linko-spool-stop; do
    bash -n "$SRC/$name.sh"
    install -m 755 -o root -g root "$SRC/$name.sh" "/usr/local/bin/$name"
done
install -m 644 -o root -g root "$SRC/linko.service" /etc/systemd/system/linko.service
install -d -o linko -g linko /var/lib/linko/spool
systemctl daemon-reload
echo "Kuruldu: linko-deploy, linko-backup, linko-spool, linko-spool-stop, linko.service"
