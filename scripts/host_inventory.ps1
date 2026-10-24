param([Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
$utf8=New-Object Text.UTF8Encoding($false)
[Console]::OutputEncoding=$utf8
try {
    $svc=New-Object -ComObject 'Schedule.Service';$svc.Connect()
    $folder=$svc.GetFolder('\');$rows=@()
    foreach($task in $folder.GetTasks(0)) {
        if($task.Name -notmatch '^ClashMate-Conversation-[a-f0-9]{16}$'){continue}
        $d=$task.Definition
        $row=@{name=[string]$task.Name;marker=[string]$d.RegistrationInfo.Description;action_count=[int]$d.Actions.Count;
            state=[int]$task.State;running_instances=[int]$task.GetInstances(0).Count}
        if($d.Actions.Count -eq 1) {
            $a=$d.Actions.Item(1);$row.python=[string]$a.Path;$row.arguments=[string]$a.Arguments;$row.working_directory=[string]$a.WorkingDirectory
        }
        $rows+=$row
    }
    $value=@{ok=$true;scope='current_user_contract_checked_separately_no_mutation';tasks=$rows;CAD_calls=0;processes_terminated=$false}
    [IO.File]::WriteAllText($Output,($value | ConvertTo-Json -Depth 8),$utf8);exit 0
} catch {
    [IO.File]::WriteAllText($Output,(@{ok=$false;message=$_.Exception.Message;hresult=$_.Exception.HResult;CAD_calls=0;processes_terminated=$false} | ConvertTo-Json),$utf8);exit 2
}
