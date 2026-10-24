param([Parameter(Mandatory=$true)][string]$Request,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$utf8=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
$launchAttempted=$false;$launchConfirmed=$false;$contract=$null;$failureCode=$null;$created=$false
try {
    $spec=[IO.File]::ReadAllText($Request,$utf8) | ConvertFrom-Json
    if($spec.mode -in @('register','run')) {
        foreach($value in @($PSScriptRoot,$spec.work,$spec.entry)) {
            $path=[IO.Path]::GetFullPath([string]$value)
            if(($path -split '[\\/]') -icontains 'upgrade-backups') {$failureCode='HOST_BACKUP_TREE_REFUSED';throw $failureCode}
            while($path) {
                if(Test-Path -LiteralPath (Join-Path $path '.clashmate-recovery-snapshot.json') -PathType Leaf) {$failureCode='HOST_BACKUP_TREE_REFUSED';throw $failureCode}
                $parent=Split-Path -Parent $path;if($parent -eq $path){break};$path=$parent
            }
        }
    }
    . (Join-Path $PSScriptRoot 'host_contract.ps1')
    if($spec.name -notmatch '^ClashMate-(Conversation|HostTest)-[a-f0-9]{16}$'){throw 'HOST_TASK_NAME_INVALID'}
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $svc=New-Object -ComObject 'Schedule.Service';$svc.Connect()
    $folder=$svc.GetFolder('\')
    $task=$null
    try {$task=$folder.GetTask($spec.name)} catch {
        if($_.Exception.HResult -notin @(-2147024894,-2147024893)){throw}
    }
    function Assert-Contract($t) {
        $script:contract=Get-HostContract -Definition $t.Definition -Spec $spec -ExpectedSid $sid
        if(-not $script:contract.ok) {
            $script:failureCode=if($script:contract.principal.status -eq 'unverifiable' -and $script:contract.failed_checks.Count -eq 1){'HOST_PRINCIPAL_UNVERIFIABLE'}else{'HOST_TASK_COLLISION'}
            throw $script:failureCode
        }
    }
    if($task){Assert-Contract $task}
    if($spec.mode -eq 'register') {
        if(-not $task) {
            $d=$svc.NewTask(0);$d.RegistrationInfo.Description=$spec.marker
            $d.Principal.UserId=$sid;$d.Principal.LogonType=3;$d.Principal.RunLevel=0
            $d.Settings.Enabled=$true;$d.Settings.AllowDemandStart=$true
            $d.Settings.DisallowStartIfOnBatteries=$false;$d.Settings.StopIfGoingOnBatteries=$false
            $d.Settings.ExecutionTimeLimit='PT0S';$d.Settings.MultipleInstances=2
            $a=$d.Actions.Create(0);$a.Path=$spec.python;$a.Arguments=$spec.arguments;$a.WorkingDirectory=$spec.working_directory
            $task=$folder.RegisterTaskDefinition($spec.name,$d,2,$sid,$null,3,$null)
            $created=$true
        }
        # Verify the registered service representation, including normalized principal identity.
        $task=$folder.GetTask($spec.name);Assert-Contract $task
    } elseif($spec.mode -eq 'run') {
        if(-not $task){throw 'HOST_TASK_NOT_REGISTERED'}
        if($spec.generation -notmatch '^[a-f0-9]{32}$'){throw 'HOST_GENERATION_INVALID'}
        $sessionId=[Diagnostics.Process]::GetCurrentProcess().SessionId
        if($sessionId -le 0){throw 'HOST_INTERACTIVE_SESSION_REQUIRED'}
        $launchAttempted=$true;$running=$task.RunEx([string]$spec.generation,4,$sessionId,$null);$launchConfirmed=$true
    } elseif($spec.mode -eq 'unregister') {
        if($task) {
            if($task.GetInstances(0).Count -gt 0 -or [int]$task.State -in @(2,4)){throw 'HOST_TASK_STILL_RUNNING'}
            $folder.DeleteTask($spec.name,0);$task=$null
        }
    } elseif($spec.mode -ne 'query') {throw 'HOST_MODE_INVALID'}
    $value=@{ok=$true;name=$spec.name;mode=$spec.mode;created=$created;registered=($null -ne $task);interactive_user_sid=$sid;no_triggers=$true;run_level='least_privilege';CAD_started=$false;contract=$contract;launch_attempted=$launchAttempted;launch_confirmed=$launchConfirmed}
    if($task){$value.state=[int]$task.State;$value.last_task_result=[int64]$task.LastTaskResult;$value.running_instances=[int]$task.GetInstances(0).Count}
    if($running){$value.instance_guid=[string]$running.InstanceGuid;$value.engine_pid=[int]$running.EnginePID}
    [IO.File]::WriteAllText($Output,($value | ConvertTo-Json -Depth 12),$utf8)
    exit 0
} catch {
    $value=@{ok=$false;code=$failureCode;message=$_.Exception.Message;hresult=$_.Exception.HResult;CAD_started=$false;mode=$spec.mode;contract=$contract;created=$created;launch_attempted=$launchAttempted;launch_confirmed=$launchConfirmed}
    [IO.File]::WriteAllText($Output,($value | ConvertTo-Json -Depth 12),$utf8)
    exit 2
}
