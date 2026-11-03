# Builds Prismatic as a folder (dist\Prismatic\Prismatic.exe + its files) and zips it
# into dist\Prismatic-<version>-windows.zip. No Python needed to run the result.
#
# A folder build is used instead of a single self-extracting .exe on purpose: the
# single-file format unpacks itself to a temp folder at launch, which antivirus
# heuristics often mistake for a malware "dropper".
#
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
# Set $env:PRISMATIC_VENV to put the build environment elsewhere (e.g. a
# shorter path if pip hits Windows' 260-character path limit), and
# $env:PRISMATIC_PYTHON to build with a specific Python (the GitHub build does).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Run($exe) {
    & $exe @args
    if ($LASTEXITCODE -ne 0) { throw "Failed: $exe $args" }
}

$venv = if ($env:PRISMATIC_VENV) { $env:PRISMATIC_VENV } else { ".venv" }
$py = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $py)) {
    if ($env:PRISMATIC_PYTHON) { Run $env:PRISMATIC_PYTHON -m venv $venv } else { Run py -3 -m venv $venv }
}
Run $py -m ensurepip --upgrade
Run $py -m pip install --quiet -r requirements.txt -r requirements-build.txt

$work = Join-Path $venv "pyi-build"
New-Item -ItemType Directory -Force $work | Out-Null
Run $py tools\make_icon.py
$versionFile = Join-Path $work "version_info.txt"
$version = (& $py tools\make_version_info.py $versionFile) -replace '^version ', ''
$icon = (Resolve-Path assets\prismatic.ico).Path
$ui = (Resolve-Path ui).Path

Run $py -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name Prismatic `
    --icon $icon `
    --version-file (Resolve-Path $versionFile).Path `
    --add-data "$icon;assets" `
    --add-data "$ui;ui" `
    --collect-submodules winrt `
    --hidden-import winrt.windows.foundation.collections `
    --hidden-import winrt.windows.foundation.numerics `
    --workpath $work --specpath $work `
    prismatic.pyw

$zip = "dist\Prismatic-$version-windows.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\Prismatic -DestinationPath $zip
Write-Host "Built $(Resolve-Path dist\Prismatic\Prismatic.exe)"
Write-Host "Zipped $(Resolve-Path $zip)"
