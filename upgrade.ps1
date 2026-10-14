param([Parameter(Mandatory=$true)][string]$SourcePackage, [Parameter(Mandatory=$true)][string]$TargetDir, [string]$PythonPath = '', [string]$SolidWorksInstallDir = '', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
$arguments = @((Join-Path $PSScriptRoot 'scripts\upgrade.py'), '--package', $SourcePackage, '--target', $TargetDir, '--python', $PythonPath)
if ($SolidWorksInstallDir) { $arguments += @('--solidworks-install-dir', $SolidWorksInstallDir) }
if ($DryRun) { $arguments += '--dry-run' }
& $PythonPath @arguments
exit $LASTEXITCODE
