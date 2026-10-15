param([string]$PythonPath = '', [string]$SolidWorksInstallDir = '', [string]$PipIndexUrl = 'https://pypi.org/simple')
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'install.ps1') @PSBoundParameters
