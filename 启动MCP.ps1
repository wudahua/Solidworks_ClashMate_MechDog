param([int]$SolidWorksProcessId = 0, [switch]$Legacy)
$ErrorActionPreference = 'Stop'
if ($SolidWorksProcessId -gt 0) { $env:SW_MCP_PROCESS_ID = [string]$SolidWorksProcessId }
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$executorPath = Join-Path $PSScriptRoot 'executor\bin\SwExecutor.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Project virtual environment is missing. Run 初始化环境.ps1.' }
if (-not (Test-Path -LiteralPath $executorPath)) { throw 'Executor is missing. Run executor/build.ps1.' }
$entry = if ($Legacy) { 'server.py' } else { 'motion_server.py' }
& $projectPython (Join-Path $PSScriptRoot $entry)
exit $LASTEXITCODE
