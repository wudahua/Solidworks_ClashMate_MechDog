param([int]$SolidWorksProcessId = 0, [switch]$Legacy)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start.ps1') @PSBoundParameters
exit $LASTEXITCODE
