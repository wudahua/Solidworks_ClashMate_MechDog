param([string]$PythonPath = '', [string]$SolidWorksInstallDir = '')
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
if ($SolidWorksInstallDir) { $env:SW_INSTALL_DIR = $SolidWorksInstallDir }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Specify an existing Python runtime with -PythonPath.' }
& $PythonPath -c "import sys,struct; assert sys.version_info >= (3,11) and struct.calcsize('P') == 8, '64-bit Python 3.11+ required'"
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python runtime.' }
$venvPath = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonPath -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $venvPython -m pip --isolated install --index-url https://pypi.org/simple -r (Join-Path $PSScriptRoot 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& (Join-Path $PSScriptRoot 'executor\build.ps1')
