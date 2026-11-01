# Builds dist\Prismatic.exe (a single file, no Python needed to run it).
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
# Set $env:PRISMATIC_VENV to put the build environment elsewhere (e.g. a
# shorter path if pip hits Windows' 260-character path limit).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Run($exe) {
    & $exe @args
    if ($LASTEXITCODE -ne 0) { throw "Failed: $exe $args" }
}

$venv = if ($env:PRISMATIC_VENV) { $env:PRISMATIC_VENV } else { ".venv" }
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    Run py -3 -m venv $venv
}
Run $py -m ensurepip --upgrade
Run $py -m pip install --quiet -r requirements.txt -r requirements-build.txt

Run $py tools\make_icon.py
$icon = (Resolve-Path assets\prismatic.ico).Path
$ui = (Resolve-Path ui).Path

Run $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name Prismatic `
    --icon $icon `
    --add-data "$icon;assets" `
    --add-data "$ui;ui" `
    --collect-submodules winrt `
    --hidden-import winrt.windows.foundation.collections `
    --hidden-import winrt.windows.foundation.numerics `
    --workpath (Join-Path $venv "pyi-build") --specpath (Join-Path $venv "pyi-build") `
    prismatic.pyw

Write-Host "Built $(Resolve-Path dist\Prismatic.exe)"
