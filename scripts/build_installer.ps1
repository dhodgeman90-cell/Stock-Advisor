# Compile the Inno Setup installer. Requires the one-folder build (run build_app.ps1 first)
# and Inno Setup 6 (ISCC.exe). Run from the repo root:  .\scripts\build_installer.ps1
$ErrorActionPreference = "Stop"

if (-not (Test-Path dist\StockAdvisor\StockAdvisor.exe)) {
    throw "No build found. Run .\scripts\build_app.ps1 first."
}

# Read __version__ from src/__init__.py (single source of truth).
$version = (python -c "import src; print(src.__version__)").Trim()
if (-not $version) { throw "Could not read src.__version__" }

# Locate ISCC.exe. Check PATH first, then the common per-machine and per-user
# (winget defaults to per-user) install locations.
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if ($iscc) {
    $isccPath = $iscc.Source
} else {
    $guesses = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $isccPath = $guesses | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $isccPath) {
        throw "ISCC.exe not found. Install Inno Setup 6 (winget install JRSoftware.InnoSetup)."
    }
}

Write-Host "Compiling installer for v$version..."
& $isccPath "/DAppVersion=$version" installer\StockAdvisor.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (exit $LASTEXITCODE)" }

Write-Host "Installer -> installer\Output\StockAdvisor-Setup-$version.exe"
