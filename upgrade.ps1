param([Parameter(Mandatory=$true)][string]$SourcePackage, [Parameter(Mandatory=$true)][string]$TargetDir, [string]$PythonPath = '', [string]$SolidWorksInstallDir = '', [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$pythonStarted = $false
$pythonPid = $null
$stage = 'resolve_python'
try {
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
$stage = 'start_python'
    try {
        [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'Process')
        $process = [System.Diagnostics.Process]::Start($start)
        $pythonStarted = $true
        $pythonPid = $process.Id
    } finally {
        [Environment]::SetEnvironmentVariable('PYTHONIOENCODING', $previousEncoding, 'Process')
    }
$stage = 'capture_upgrade_output'
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
} catch {
    $code = 'UPGRADE_WRAPPER_START_FAILED'
    if ($pythonStarted) { $code = 'UPGRADE_WRAPPER_OUTPUT_FAILED' }
    $instruction = 'Check PythonPath or use the equivalent scripts/upgrade.py entry. If Python started, inspect its receipt before any retry.'
    $failure = @{ok=$false; schema_version=2; code=$code; stage=$stage; python_started=$pythonStarted; target_mutation_started=$null; backup_created=$null; receipt_path=$null; committed=$null; rollback_status='unknown'; rollback_verified=$null; safe_to_start_mcp=$false; processes_stopped=$false; automatic_retry=$false; error=@{code=$code; message=$_.Exception.Message; stage=$stage; diagnostics=@{python_pid=$null}; next_action=@{automatic_retry=$false; instruction=$instruction}}}
    $failure.upgrade_result_schema_version = 1
    if ($pythonStarted) { $failure.error.diagnostics.python_pid = $pythonPid }
    else { $failure.target_mutation_started=$false; $failure.backup_created=$false; $failure.committed=$false; $failure.rollback_status='not_required' }
    Write-Output ($failure | ConvertTo-Json -Depth 8 -Compress)
    exit 1
}
