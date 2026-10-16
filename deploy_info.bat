@echo off
chcp 65001 >nul
title Linko Scrapper Light — Sunucu Bilgileri

echo.
echo ============================================================
echo   Linko Scrapper Light — Sunucu Deploy Rehberi
echo ============================================================
echo.
echo  Bu sistem sunucuya deploy edilebilir.
echo  AI veya API GEREKTIRMEZ — tamamen offline calisir!
echo.
echo  [1] Sunucuya dosyaları kopyalayın (SCP veya Git):
echo      scp -r "linko scrapper light/" user@ip:/opt/linko/
echo      VEYA: git clone https://... /opt/linko
echo.
echo  [2] Sunucuda kurulum scriptini çalıştırın:
echo      cd /opt/linko
echo      chmod +x setup_server.sh
echo      sudo ./setup_server.sh
echo.
echo  [3] Servisi başlatın:
echo      sudo systemctl start linko-scrapper
echo      sudo systemctl status linko-scrapper
echo.
echo  [4] Tarayıcınızdan erişin:
echo      http://SUNUCU_IP:8016
echo.
echo  NOT: Güvenlik için portu kısıtlayın:
echo      ufw allow from KENDI_IP to any port 8016
echo.
echo ============================================================
pause
