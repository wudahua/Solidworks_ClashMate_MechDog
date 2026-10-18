param([Parameter(Mandatory=$true)][string]$SourcePackage, [Parameter(Mandatory=$true)][string]$TargetDir, [string]$PythonPath = '', [string]$SolidWorksInstallDir = '', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
$arguments = @((Join-Path $PSScriptRoot 'scripts\upgrade.py'), '--package', $SourcePackage, '--target', $TargetDir, '--python', $PythonPath)
if ($SolidWorksInstallDir) { $arguments += @('--solidworks-install-dir', $SolidWorksInstallDir) }
if ($DryRun) { $arguments += '--dry-run' }
# Launch independently of PowerShell's native stderr-to-ErrorRecord conversion.
# In Windows PowerShell 5.1, a caller's 2>&1 | Out-String must not turn a
# harmless child stderr line into a terminating error inside this script.
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $PythonPath
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
$start.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
function Quote-NativeArgument([string]$value) {
    return '"' + [regex]::Replace([regex]::Replace($value, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}
$start.Arguments = (($arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' ')
# PS5.1 may return null on the first EnvironmentVariables getter. Inherit a
# process-scoped value instead, restoring the caller immediately after Start.
$previousEncoding = [Environment]::GetEnvironmentVariable('PYTHONIOENCODING', 'Process')
$pythonStarted = $false
try {
    try {
        [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
        $process = [System.Diagnostics.Process]::Start($start)
        $pythonStarted = $true
    } finally {
        [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', $previousEncoding, 'Process')
    }
} catch {
    # Python has not started: no backup/receipt is claimed to exist. Do not
    # relabel an error from a running Python upgrade as a pre-start failure.
    $failure = @{ok=$false; code='UPGRADE_WRAPPER_START_FAILED'; stage='start_python'; python_started=$pythonStarted; target_mutation_started=$null; backup_created=$null; message=$_.Exception.Message; next_action='Check PythonPath, or run python scripts/upgrade.py --package PACKAGE --target TARGET --python PYTHON --dry-run from the new package. If Python started, inspect its receipt before any retry.'}
    if (-not $pythonStarted) { $failure.target_mutation_started = $false; $failure.backup_created = $false }
    Write-Output ($failure | ConvertTo-Json -Compress)
    exit 1
}
$stdoutTask = $process.StandardOutput.ReadToEndAsync()
$stderrTask = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
$stdoutText = $stdoutTask.GetAwaiter().GetResult()
$stderrText = $stderrTask.GetAwaiter().GetResult()
$resultCode = $process.ExitCode
$process.Dispose()
if ($stdoutText) { Write-Output $stdoutText.TrimEnd() }
if ($stderrText) { [Console]::Error.Write($stderrText) }
exit $resultCode
