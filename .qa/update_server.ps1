$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskBase = 'http://127.0.0.1:8016'
$previous = Invoke-RestMethod -Uri ($taskBase + '/api/scrape/status') -TimeoutSec 10
$resumeId = if ($previous.running -and $previous.run) { $previous.run.id } else { $null }
if ($previous.running -and -not $resumeId) { throw 'Active operation has no persistent run ID; update stopped.' }
if ($resumeId) {
    Invoke-RestMethod -Method Post -Uri ($taskBase + '/api/runs/' + $resumeId + '/pause') -TimeoutSec 10 | Out-Null
    $quiet = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $status = Invoke-RestMethod -Uri ($taskBase + '/api/scrape/status') -TimeoutSec 5
        if (-not $status.running) { $quiet = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $quiet) { throw 'Worker did not pause; no process stopped.' }
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupPath = Join-Path $taskRoot ('.qa\before_transport_' + $stamp + '.db')
& $taskPython -B -c 'import sqlite3,sys; from jobapp import config; source=sqlite3.connect(config.DB_PATH); target=sqlite3.connect(sys.argv[1]); source.backup(target); target.close(); source.close()' $backupPath
if ($LASTEXITCODE -ne 0) { throw 'Backup failed; update stopped.' }
$taskEntry = Join-Path $taskRoot 'run.py'
$taskPattern = '(?i)(?:^|\s)"?(?:' + [regex]::Escape($taskEntry) + '|run\.py)"?\s*$'
$processes = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($taskPython) -and $_.CommandLine -match $taskPattern
})
if ($processes.Count -eq 0) { throw 'No matching workspace server process found.' }
$listener = Get-NetTCPConnection -LocalPort 8016 -State Listen -ErrorAction Stop
if ($listener.OwningProcess -notin $processes.ProcessId) { throw 'Listener does not match verified workspace process; no process stopped.' }
foreach ($process in $processes) { Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2
$env:JOBAPP_OPEN_BROWSER = '0'
Start-Process -FilePath $taskPython -ArgumentList @('-B','run.py') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot ('.qa\server_' + $stamp + '.out.log')) -RedirectStandardError (Join-Path $taskRoot ('.qa\server_' + $stamp + '.err.log'))
$ready = $false
for ($attempt = 0; $attempt -lt 25; $attempt++) {
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri $taskBase -TimeoutSec 3
        if ($page.Content.Contains('20261016.6')) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw 'New server was not confirmed ready. Persisted run remains paused.' }
$state = Invoke-RestMethod -Uri ($taskBase + '/api/source/status') -TimeoutSec 5
if ($resumeId -and -not $state.paused) {
    Invoke-RestMethod -Method Post -Uri ($taskBase + '/api/runs/' + $resumeId + '/resume') -TimeoutSec 10 | Out-Null
}
$result = Invoke-RestMethod -Uri ($taskBase + '/api/scrape/status') -TimeoutSec 10
[pscustomobject]@{ backup=$backupPath; resumed_run=$resumeId; running=$result.running; source_state=$result.source_state; run=$result.run } | ConvertTo-Json -Depth 7
