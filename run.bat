@echo off
title Linko Scrapper Light

cd /d "%~dp0"

echo ========================================================
echo   Linko Scrapper Light
echo   Hesapsiz LinkedIn Tarayici
echo ========================================================
echo.

python --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Python bulunamadi! python.org/downloads adresinden kurun.
    pause
    exit /b 1
)

set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" goto :setup_venv

"%VENV_PYTHON%" -c "import flask" >nul 2>nul
if %ERRORLEVEL% NEQ 0 goto :setup_venv
goto :start

:setup_venv
echo [BILGI] Sanal ortam kuruluyor, lutfen bekleyin...
if exist "%~dp0.venv" rd /s /q "%~dp0.venv"
python -m venv "%~dp0.venv"
if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Sanal ortam olusturulamadi!
    pause
    exit /b 1
)
"%VENV_PYTHON%" -m pip install -r "%~dp0requirements.txt" --quiet
if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Paketler yuklenemedi!
    pause
    exit /b 1
)
echo [TAMAM] Kurulum tamamlandi.

:start
echo.
echo ========================================================
echo   Aciliyor: http://127.0.0.1:8016
echo   Uygulama zaten aciksa mevcut sunucu kullanilir.
echo ========================================================
echo.

"%VENV_PYTHON%" "%~dp0run.py"
set "APP_EXIT=%ERRORLEVEL%"
if "%APP_EXIT%"=="0" exit /b 0
echo.
echo [HATA] Uygulama baslatilamadi. Hata kodu: %APP_EXIT%
pause
exit /b %APP_EXIT%
