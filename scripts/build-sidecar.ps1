# Build the PyInstaller sidecar on Windows (native PowerShell variant of
# scripts/build-sidecar.sh — same venv, same spec, same output layout).
# PREPARED BUT NOT YET VALIDATED ON WINDOWS: run on a real Windows machine
# or the GitHub Actions windows job before trusting the output.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Sidecar = Join-Path $Root "desktop\sidecar"
$Python = if ($env:PYTHON) { $env:PYTHON } else { "py -3.12" }

Set-Location $Sidecar

if (-not (Test-Path "venv")) {
    Invoke-Expression "$Python -m venv venv"
}
& "venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "venv\Scripts\python.exe" -m pip install --quiet -r requirements-core.txt "pyinstaller>=6.0"

# Sanity: the backend must import with the core dependency set before freezing.
$tmp = Join-Path $env:TEMP ("smartdocs-probe-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
Push-Location $Root
$env:SMARTDOCS_DATA_DIR = $tmp
& "$Sidecar\venv\Scripts\python.exe" -c "import app; print('import app: OK')"
Pop-Location
Remove-Item -Recurse -Force $tmp

& "venv\Scripts\pyinstaller.exe" --clean --noconfirm smartdocs-sidecar.spec

Write-Host "sidecar built: $Sidecar\dist\smartdocs-sidecar\smartdocs-sidecar.exe"
