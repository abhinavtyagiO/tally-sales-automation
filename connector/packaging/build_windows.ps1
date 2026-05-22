$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..\..")

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\pyinstaller.exe connector\packaging\AccountPilotHelper.spec --distpath connector\dist --workpath connector\build --clean

Write-Host "Built connector\dist\AccountPilotHelper.exe"
