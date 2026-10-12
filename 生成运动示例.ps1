param([int]$SolidWorksProcessId = 0, [string]$PartTemplate = '', [string]$AssemblyTemplate = '')
$ErrorActionPreference = 'Stop'
if ($SolidWorksProcessId -gt 0) { $env:SW_MCP_PROCESS_ID = [string]$SolidWorksProcessId }
if ($PartTemplate) { $env:SW_MCP_PART_TEMPLATE = $PartTemplate }
if ($AssemblyTemplate) { $env:SW_MCP_ASSEMBLY_TEMPLATE = $AssemblyTemplate }
& (Join-Path $PSScriptRoot 'executor\bin\SwExecutor.exe') build-motion-examples
exit $LASTEXITCODE
