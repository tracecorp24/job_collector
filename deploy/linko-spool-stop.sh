#!/usr/bin/env bash
# linko.service ExecStopPost: servis beklenmedik şekilde durduysa olay kaydı bırakır.
# Normal durdurma/yeniden başlatmada (SERVICE_RESULT=success) bir şey yapmaz.
# Kullanım: linko-spool-stop <SERVICE_RESULT> <EXIT_CODE> <EXIT_STATUS>
[ "${1:-success}" = "success" ] && exit 0
exec /usr/local/bin/linko-spool systemd error "linko.service beklenmedik şekilde durdu" \
    "sonuç=$1 çıkış kodu=${2:-?} durum=${3:-?}
$(journalctl -u linko -n 30 --no-pager 2>&1)"
