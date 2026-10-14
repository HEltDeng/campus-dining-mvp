param([int]$Port = 8876)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the project virtual environment.' }
    & $pythonExe -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
$localUrl = "http://127.0.0.1:$Port"
try {
    $health = Invoke-RestMethod "$localUrl/api/health" -TimeoutSec 2
    if ($health.mode -eq 'LOCAL_DEMO') {
        Write-Host "Campus demo is already running: $localUrl"
        exit 0
    }
} catch { }
Write-Host "Campus Dining LOCAL DEMO: $localUrl"
Write-Host 'Demo password: demo12345. No real payments or external delivery services.'
Write-Host 'Keep this window open. Ctrl+C stops this server; the SQLite database is retained.'
& $pythonExe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port --no-access-log
exit $LASTEXITCODE
