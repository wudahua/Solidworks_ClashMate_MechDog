param([Parameter(Mandatory=$true)][string]$SourcePackage, [Parameter(Mandatory=$true)][string]$TargetDir, [string]$PythonPath = '', [string]$SolidWorksInstallDir = '', [switch]$DryRun, [switch]$AsciiJson)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$pythonStarted = $false
$pythonPid = $null
$stage = 'resolve_python'
function Format-ResultJson([string]$value) {
    if (-not $AsciiJson) { return $value }
    return [regex]::Replace($value, '[^\x00-\x7F]', [System.Text.RegularExpressions.MatchEvaluator]{ param($match) '\u{0:x4}' -f [int][char]$match.Value })
}
try {
if (-not $PythonPath) { $PythonPath = (Get-Command python -ErrorAction Stop).Source }
$arguments = @((Join-Path $PSScriptRoot 'scripts\upgrade.py'), '--package', $SourcePackage, '--target', $TargetDir, '--python', $PythonPath)
if ($SolidWorksInstallDir) { $arguments += @('--solidworks-install-dir', $SolidWorksInstallDir) }
if ($DryRun) { $arguments += '--dry-run' }
if ($AsciiJson) { $arguments += '--ascii-json' }
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
# Leave the raw inherited environment untouched: CLR's case-insensitive getter
# throws when a host supplies both HTTPS_PROXY and https_proxy. Configure Python
# streams inside the child, after normal sitecustomize/host policy startup. The
# bootstrap is ASCII and restores script argv/path semantics before run_path.
$bootstrap = 'import os,sys,runpy;os.environ["PYTHONIOENCODING"]="utf-8";sys.stdout.reconfigure(encoding="utf-8");sys.stderr.reconfigure(encoding="utf-8");p=sys.argv.pop(1);sys.argv[0]=p;sys.path[0]=os.path.dirname(os.path.abspath(p));runpy.run_path(p,run_name="__main__")'
$start.Arguments = ((@('-c', $bootstrap) + $arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' ')
$stage = 'start_python'
$process = [System.Diagnostics.Process]::Start($start)
$pythonStarted = $true
$pythonPid = $process.Id
$stage = 'capture_upgrade_output'
$stdoutTask = $process.StandardOutput.ReadToEndAsync()
$stderrTask = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
$stdoutText = $stdoutTask.GetAwaiter().GetResult()
$stderrText = $stderrTask.GetAwaiter().GetResult()
$resultCode = $process.ExitCode
$process.Dispose()
if ($stdoutText) { Write-Output (Format-ResultJson $stdoutText.TrimEnd()) }
if ($stderrText) { [Console]::Error.Write($stderrText) }
exit $resultCode
} catch {
    $code = 'UPGRADE_WRAPPER_START_FAILED'
    if ($pythonStarted) { $code = 'UPGRADE_WRAPPER_OUTPUT_FAILED' }
    $instruction = 'Check PythonPath or use the equivalent scripts/upgrade.py entry. If Python started, inspect its receipt before any retry.'
    $failure = @{ok=$false; schema_version=2; code=$code; stage=$stage; python_started=$pythonStarted; target_mutation_started=$null; backup_created=$null; receipt_path=$null; committed=$null; rollback_status='unknown'; rollback_verified=$null; safe_to_start_mcp=$false; processes_stopped=$false; automatic_retry=$false; error=@{code=$code; message=$_.Exception.Message; stage=$stage; diagnostics=@{python_pid=$null}; next_action=@{automatic_retry=$false; instruction=$instruction}}}
    $failure.upgrade_result_schema_version = 1
    $failure.dry_run = [bool]$DryRun
    $failure.target_directory = $TargetDir
    $failure.receipt_schema_version = 2
    $failure.failure_stage = $stage
    $failure.installation_state = 'unknown'
    $failure.managed_files_consistent = $null
    $failure.receipt_stage_persisted = $null
    $failure.receipt_write_error = $null
    $failure.recovery_journal_unchanged = $null
    $failure.rollback_attempted = $null
    $failure.mcp_start_admission = 'not_evaluated_use_normal_lease_recovery_and_COM_handshake'
    if ($pythonStarted) { $failure.error.diagnostics.python_pid = $pythonPid }
    else { $failure.target_mutation_started=$false; $failure.backup_created=$false; $failure.committed=$false; $failure.rollback_status='not_required'; $failure.rollback_attempted=$false; $failure.installation_state='unchanged'; $failure.managed_files_consistent=$true; $failure.safe_to_start_mcp=$null }
    Write-Output (Format-ResultJson ($failure | ConvertTo-Json -Depth 8 -Compress))
    exit 1
}
