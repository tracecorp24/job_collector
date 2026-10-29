#!/usr/bin/env bash
# Sunucuda root olarak çalıştırılır: depodaki işletim betiklerini ve servis tanımını kurar.
# Bu dosyalar /usr/local/bin ve /etc/systemd altında KOPYA olarak durur. İlk kurulumda elle çalıştırılır;
# sonrasında linko-deploy, depodaki sürümler değişince başarılı deploy'un sonunda bu betiği kendisi çağırır.
# Kullanım:  ssh root@38.45.81.29 'bash /opt/linko/deploy/install-ops.sh'
# Servisi yeniden başlatmaz; bir sonraki deploy yeni servis tanımını uygular.
set -euo pipefail
SRC=/opt/linko/deploy
install -d -m 755 /usr/local/lib
# Geçici dosyaya yazıp yeniden adlandırır: o an çalışan linko-deploy kendi dosyası değişirken bozulmaz.
put() { install -m "$1" -o root -g root "$2" "$3.new" && mv -f "$3.new" "$3"; }
for name in linko-deploy linko-backup linko-spool linko-spool-stop; do
    bash -n "$SRC/$name.sh"
    put 755 "$SRC/$name.sh" "/usr/local/bin/$name"
done
put 644 "$SRC/safety.py" /usr/local/lib/linko-deploy-safety.py
put 644 "$SRC/smoke.py" /usr/local/lib/linko-deploy-smoke.py
put 644 "$SRC/linko.service" /etc/systemd/system/linko.service
put 644 "$SRC/linko-worker.service" /etc/systemd/system/linko-worker.service
install -d -o linko -g linko /var/lib/linko/spool
systemctl daemon-reload
cd /opt/linko
.venv/bin/python -m deploy.caddy_proxy --sse
echo "Kuruldu: linko-deploy, linko-backup, linko-spool, linko-spool-stop, linko.service, linko-worker.service"
