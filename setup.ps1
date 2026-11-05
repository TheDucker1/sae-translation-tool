$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if(!(Test-Path -LiteralPath '.venv/Scripts/python.exe')){
 python -m venv .venv
 if($LASTEXITCODE -ne 0){throw 'Python environment setup failed'}
}
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if($LASTEXITCODE -ne 0){throw 'Qt installation failed'}
Write-Host 'Ready. Double-click Launch.cmd, or run ./.venv/Scripts/python.exe run.py'
