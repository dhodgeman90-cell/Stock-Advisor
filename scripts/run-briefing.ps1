# Runs the Stock Advisor daily briefing and logs all output.
# Invoked by the scheduled task 'StockAdvisorDailyBriefing'. Safe to run by hand.
$ErrorActionPreference = "Continue"

$root   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("briefing-{0:yyyy-MM-dd}.log" -f (Get-Date))

"==== briefing run: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====" |
    Tee-Object -FilePath $logFile -Append

if (-not (Test-Path $python)) {
    "ERROR: venv python not found at $python" | Tee-Object -FilePath $logFile -Append
    exit 1
}

Push-Location $root
try {
    & $python -m src.main 2>&1 | Tee-Object -FilePath $logFile -Append
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

"==== exit code: $code ====" | Tee-Object -FilePath $logFile -Append
exit $code
