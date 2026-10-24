param([Parameter(Mandatory=$true)][string]$Request,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$utf8=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
try {
    $spec=[IO.File]::ReadAllText($Request,$utf8) | ConvertFrom-Json
    if($spec.name -notmatch '^ClashMate-(Conversation|HostTest)-[a-f0-9]{16}$'){throw 'HOST_TASK_NAME_INVALID'}
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $svc=New-Object -ComObject 'Schedule.Service';$svc.Connect()
    $folder=$svc.GetFolder('\')
    $task=$null
    try {$task=$folder.GetTask($spec.name)} catch {
        if($_.Exception.HResult -notin @(-2147024894,-2147024893)){throw}
    }
    function Test-Contract($t) {
        $d=$t.Definition
        $principalSid=[string]$d.Principal.UserId
        if($principalSid -notmatch '^S-1-') {
            try {$principalSid=(New-Object Security.Principal.NTAccount($principalSid)).Translate([Security.Principal.SecurityIdentifier]).Value} catch {return $false}
        }
        return ($d.RegistrationInfo.Description -eq $spec.marker -and $d.Actions.Count -eq 1 -and
            $d.Actions.Item(1).Path -ieq $spec.python -and $d.Actions.Item(1).Arguments -ceq $spec.arguments -and
            $d.Actions.Item(1).WorkingDirectory -ieq $spec.working_directory -and
            $principalSid -eq $sid -and $d.Principal.LogonType -eq 3 -and $d.Principal.RunLevel -eq 0 -and
            $d.Triggers.Count -eq 0 -and $d.Settings.ExecutionTimeLimit -eq 'PT0S' -and
            -not $d.Settings.DisallowStartIfOnBatteries -and -not $d.Settings.StopIfGoingOnBatteries -and
            $d.Settings.MultipleInstances -eq 2 -and $d.Settings.AllowDemandStart)
    }
    if($task -and -not (Test-Contract $task)){throw 'HOST_TASK_COLLISION'}
    $created=$false
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
    } elseif($spec.mode -eq 'run') {
        if(-not $task){throw 'HOST_TASK_NOT_REGISTERED'}
        if($spec.generation -notmatch '^[a-f0-9]{32}$'){throw 'HOST_GENERATION_INVALID'}
        $sessionId=[Diagnostics.Process]::GetCurrentProcess().SessionId
        if($sessionId -le 0){throw 'HOST_INTERACTIVE_SESSION_REQUIRED'}
        $running=$task.RunEx([string]$spec.generation,4,$sessionId,$null)
    } elseif($spec.mode -eq 'unregister') {
        if($task) {
            if($task.GetInstances(0).Count -gt 0){throw 'HOST_TASK_STILL_RUNNING'}
            $folder.DeleteTask($spec.name,0);$task=$null
        }
    } elseif($spec.mode -ne 'query') {throw 'HOST_MODE_INVALID'}
    $value=@{ok=$true;name=$spec.name;mode=$spec.mode;created=$created;registered=($null -ne $task);interactive_user_sid=$sid;no_triggers=$true;run_level='least_privilege';CAD_started=$false}
    if($task){$value.state=[int]$task.State;$value.last_task_result=[int64]$task.LastTaskResult;$value.running_instances=[int]$task.GetInstances(0).Count}
    if($running){$value.instance_guid=[string]$running.InstanceGuid;$value.engine_pid=[int]$running.EnginePID}
    [IO.File]::WriteAllText($Output,($value | ConvertTo-Json -Depth 8),$utf8)
    exit 0
} catch {
    $value=@{ok=$false;message=$_.Exception.Message;hresult=$_.Exception.HResult;CAD_started=$false}
    [IO.File]::WriteAllText($Output,($value | ConvertTo-Json -Depth 8),$utf8)
    exit 2
}
