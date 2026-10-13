param([string]$PythonPath = '', [string]$SolidWorksInstallDir = '', [string]$PipIndexUrl = 'https://pypi.org/simple')
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
if ($SolidWorksInstallDir) { $env:SW_INSTALL_DIR = $SolidWorksInstallDir }
$indexUri = $null
if (-not [Uri]::TryCreate($PipIndexUrl, [UriKind]::Absolute, [ref]$indexUri) -or $indexUri.Scheme -ne 'https' -or $indexUri.UserInfo -or $indexUri.Query -or $indexUri.Fragment) { throw 'PipIndexUrl must be an HTTPS index URL without credentials, query or fragment.' }
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Specify an existing Python runtime with -PythonPath.' }
$runtimeCheck = Join-Path $PSScriptRoot 'scripts\validate_runtime.py'
& $PythonPath -I $runtimeCheck --python $PythonPath
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python runtime.' }
$venvPath = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Test-Path -LiteralPath $venvPath) { throw 'Existing .venv is incomplete. Move it aside explicitly before reinstalling; no files were removed.' }
    & $PythonPath -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $PythonPath -I $runtimeCheck --python $PythonPath --venv $venvPath
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment identity mismatch; inspect runtime diagnostics before reinstalling.' }
& $venvPython -m pip --isolated install --index-url $PipIndexUrl -r (Join-Path $PSScriptRoot 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& (Join-Path $PSScriptRoot 'executor\build.ps1')
