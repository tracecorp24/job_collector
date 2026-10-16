#!/usr/bin/env bash
# =============================================================================
#  Linko Scrapper Light — Linux/VPS Server Setup Script
#  Desteklenen: Ubuntu 20.04+, Debian 11+, CentOS 8+, Rocky Linux 8+
#  Gereksinim: Python 3.10+ (sistem düzeyinde)
#  AI/API: ZORUNLU DEĞİL — sistem tamamen offline çalışır (rules backend)
# =============================================================================
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$INSTALL_DIR/.venv"
ENV_FILE="$INSTALL_DIR/.env"
SERVICE_NAME="linko-scrapper"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_DIR="$INSTALL_DIR/logs"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1" >&2; exit 1; }

echo ""
echo "============================================================"
echo "  Linko Scrapper Light — Sunucu Kurulum Scripti"
echo "  Dizin: $INSTALL_DIR"
echo "============================================================"
echo ""

# --- 1. Python versiyonu kontrol ---
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(sys.version_info >= (3,10))")
        if [ "$ver" = "True" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done
[ -z "$PYTHON" ] && err "Python 3.10+ bulunamadı. 'apt install python3.11' veya benzeri komutla kurun."
log "Python bulundu: $PYTHON ($($PYTHON --version))"

# --- 2. pip kontrolü ---
$PYTHON -m pip --version &>/dev/null || err "pip bulunamadı. 'apt install python3-pip' ile kurun."

# --- 3. Sanal ortam ---
if [ ! -d "$VENV_DIR" ]; then
    log "Sanal ortam oluşturuluyor (.venv)..."
    $PYTHON -m venv "$VENV_DIR"
else
    warn "Mevcut .venv kullanılıyor."
fi

VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

log "Bağımlılıklar kuruluyor (requirements.txt)..."
$VENV_PIP install --upgrade pip --quiet
$VENV_PIP install -r "$INSTALL_DIR/requirements.txt" --quiet
log "Bağımlılıklar kuruldu."

# --- 4. Log klasörü ---
mkdir -p "$LOG_DIR"

# --- 5. .env dosyası ---
if [ ! -f "$ENV_FILE" ]; then
    log ".env dosyası oluşturuluyor..."
    cat > "$ENV_FILE" <<EOF
# Linko Scrapper Light — Sunucu Ortam Değişkenleri
# Düzenleyip kaydedin, ardından: systemctl restart ${SERVICE_NAME}

# Ağ ayarları
JOBAPP_HOST=0.0.0.0
JOBAPP_PORT=8016

# Tarayıcı: sunucuda 0 olmalı
JOBAPP_OPEN_BROWSER=0

# Tarama davranışı
JOBAPP_REQUEST_INTERVAL=6.0
JOBAPP_MAX_RETRIES=10
JOBAPP_RETRY_BASE_COOLDOWN=60.0

# Sınıflandırma (AI GEREKTIRMEZ — rules yeterli)
# Seçenekler: rules | claude | local
# "rules" = tamamen offline, API yok, sıfır bağımlılık
JOBAPP_CLASSIFY_BACKEND=rules

# İsteğe bağlı: Claude API (sadece classify_backend=claude ise)
# ANTHROPIC_API_KEY=sk-ant-...

# İsteğe bağlı: Ollama (sadece classify_backend=local ise)
# JOBAPP_OLLAMA_HOST=http://localhost:11434
EOF
    log ".env dosyası oluşturuldu: $ENV_FILE"
else
    warn ".env zaten mevcut, değiştirilmedi."
fi

# --- 6. systemd servis dosyası (opsiyonel, root gerektirir) ---
if [ "$(id -u)" -eq 0 ]; then
    CURRENT_USER="${SUDO_USER:-root}"
    log "systemd servis dosyası oluşturuluyor..."
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Linko Scrapper Light — Hesapsiz LinkedIn Tarayici
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/gunicorn \\
    --bind 0.0.0.0:8016 \\
    --workers 1 \\
    --threads 4 \\
    --timeout 300 \\
    --access-logfile ${LOG_DIR}/access.log \\
    --error-logfile ${LOG_DIR}/error.log \\
    "jobapp.server:create_app()"
Restart=on-failure
RestartSec=5
StandardOutput=append:${LOG_DIR}/stdout.log
StandardError=append:${LOG_DIR}/stderr.log

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" 2>/dev/null || true
    log "systemd servisi kuruldu: $SERVICE_NAME"
    echo ""
    echo "  Servisi başlatmak için:"
    echo "    systemctl start $SERVICE_NAME"
    echo "  Durum:"
    echo "    systemctl status $SERVICE_NAME"
    echo "  Loglar:"
    echo "    tail -f $LOG_DIR/stderr.log"
else
    warn "root değilsiniz, systemd servisi kurulmadı."
    warn "Manuel başlatma için: ./start_server.sh"
fi

# --- 7. start_server.sh yardımcısı ---
cat > "$INSTALL_DIR/start_server.sh" <<EOF
#!/usr/bin/env bash
# Linko Scrapper Light — Manuel başlatma (systemd olmadan)
set -a; source "\$(dirname "\$0")/.env"; set +a
cd "\$(dirname "\$0")"
mkdir -p logs
echo "Sunucu başlatılıyor... http://\${JOBAPP_HOST:-0.0.0.0}:\${JOBAPP_PORT:-8016}"
exec .venv/bin/gunicorn \\
    --bind "\${JOBAPP_HOST:-0.0.0.0}:\${JOBAPP_PORT:-8016}" \\
    --workers 1 \\
    --threads 4 \\
    --timeout 300 \\
    --access-logfile logs/access.log \\
    --error-logfile logs/error.log \\
    "jobapp.server:create_app()"
EOF
chmod +x "$INSTALL_DIR/start_server.sh"
log "start_server.sh oluşturuldu."

echo ""
echo "============================================================"
echo "  Kurulum tamamlandı!"
echo ""
echo "  BAŞLATMAK İÇİN (root ile kurulduysa):"
echo "    systemctl start $SERVICE_NAME"
echo ""
echo "  VEYA (root olmadan):"
echo "    ./start_server.sh"
echo ""
echo "  Erişim: http://SUNUCU_IP:8016"
echo ""
echo "  ⚠️  Güvenlik: Güvenlik duvarı ile portu kısıtlayın:"
echo "    ufw allow from KENDI_IP_ADRESIN to any port 8016"
echo "============================================================"
echo ""
