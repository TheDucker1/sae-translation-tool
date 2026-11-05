$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if(!(Test-Path -LiteralPath '.venv/Scripts/python.exe')){
 python -m venv .venv
 if($LASTEXITCODE -ne 0){throw 'Python environment setup failed'}
}
& ./.venv/Scripts/python.exe -m pip install -r requirements-mcp.txt
if($LASTEXITCODE -ne 0){throw 'MCP dependency installation failed'}
Write-Host 'Ready. Restart the GUI, load a game/project, then MCP... -> Start MCP -> Copy connection configuration.'
Write-Host 'For an independent standalone stdio session, generate configuration with:'
Write-Host './.venv/Scripts/python.exe run_mcp.py --workspace .local/translation-mcp --print-config'
