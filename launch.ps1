$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$lightPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $lightPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ gerekli. Ortam oluşturulamadı." }
}
& $lightPython -c "import requests, bs4, flask, sqlalchemy"
if ($LASTEXITCODE -ne 0) {
    & $lightPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Bağımlılıklar kurulamadı." }
}
& $lightPython run.py
exit $LASTEXITCODE
