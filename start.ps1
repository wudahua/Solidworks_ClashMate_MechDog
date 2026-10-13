param([int]$SolidWorksProcessId = 0, [switch]$Legacy)
$ErrorActionPreference = 'Stop'
if ($SolidWorksProcessId -gt 0) { $env:SW_MCP_PROCESS_ID = [string]$SolidWorksProcessId }
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$executorPath = Join-Path $PSScriptRoot 'executor\bin\SwExecutor.exe'
if ($SolidWorksProcessId -lt 0) { throw 'SolidWorksProcessId must be positive, or omit it to use existing configuration.' }
if (-not (Test-Path -LiteralPath $projectPython -PathType Leaf)) { throw 'Project virtual environment is missing. Run install.ps1.' }
if (-not (Test-Path -LiteralPath $executorPath -PathType Leaf)) { throw 'Executor is missing. Run executor/build.ps1.' }
$entry = if ($Legacy) { 'server.py' } else { 'motion_server.py' }
& $projectPython (Join-Path $PSScriptRoot $entry)
exit $LASTEXITCODE
