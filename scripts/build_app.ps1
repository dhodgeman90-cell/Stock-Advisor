# Build the one-folder app and gate it on the hygiene verifier.
# Run from the repo root with the venv active:  .\scripts\build_app.ps1
$ErrorActionPreference = "Stop"

Write-Host "Cleaning previous build..."
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }

Write-Host "Running PyInstaller..."
pyinstaller StockAdvisor.spec --clean --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Write-Host "Verifying build hygiene..."
python scripts/verify_build.py dist/StockAdvisor
if ($LASTEXITCODE -ne 0) { throw "BUILD HYGIENE FAILED - see problems above. Build rejected." }

Write-Host "Build OK -> dist\StockAdvisor\StockAdvisor.exe"
