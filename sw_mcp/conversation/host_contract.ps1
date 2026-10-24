# Pure contract checks. No scheduler registration, process launch, or CAD calls.
function Resolve-HostPrincipal {
    param([string]$UserId,[string]$DefinitionXml,[string]$ExpectedSid,
          [scriptblock]$Translate={param($name) (New-Object Security.Principal.NTAccount($name)).Translate([Security.Principal.SecurityIdentifier]).Value},
          [string]$ComputerName=$env:COMPUTERNAME)
    $proof=@{status='unverifiable';raw_user_id=$UserId;expected_sid=$ExpectedSid;resolved_sid=$null;source=$null;attempts=@()}
    $account=$UserId
    if($DefinitionXml) {
        try {
            $settings=New-Object Xml.XmlReaderSettings
            $settings.DtdProcessing=[Xml.DtdProcessing]::Prohibit;$settings.XmlResolver=$null;$settings.MaxCharactersInDocument=1048576
            $reader=[Xml.XmlReader]::Create((New-Object IO.StringReader($DefinitionXml)),$settings)
            try {$xml=New-Object Xml.XmlDocument;$xml.XmlResolver=$null;$xml.Load($reader)} finally {$reader.Dispose()}
            $ns=New-Object Xml.XmlNamespaceManager($xml.NameTable);$ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
            $principals=$xml.SelectNodes('/t:Task/t:Principals/t:Principal',$ns)
            $users=$xml.SelectNodes('/t:Task/t:Principals/t:Principal/t:UserId',$ns)
            if($principals.Count -ne 1 -or $users.Count -ne 1){$proof.reason='single_user_principal_required';return $proof}
            $account=[string]$users.Item(0).InnerText;$proof.xml_user_id=$account
            if($account -match '^S-1-') {
                $resolved=(New-Object Security.Principal.SecurityIdentifier($account)).Value
                if($UserId -match '^S-1-' -and (New-Object Security.Principal.SecurityIdentifier($UserId)).Value -ne $resolved) {
                    $proof.reason='definition_principal_disagreement';$proof.status='mismatch';return $proof
                }
                $proof.resolved_sid=$resolved;$proof.source='definition_xml_sid'
                $proof.status=if($resolved -eq $ExpectedSid){'verified'}else{'mismatch'};return $proof
            }
        } catch {$proof.reason='invalid_definition_xml';$proof.attempts+=@{error=$_.Exception.GetType().Name};return $proof}
    }
    if($account -match '^S-1-') {
        try {$proof.resolved_sid=(New-Object Security.Principal.SecurityIdentifier($account)).Value;$proof.source='principal_sid'}
        catch {$proof.reason='invalid_principal_sid';return $proof}
    } else {
        # Qualify isolated local names; never accept a username string as identity proof.
        $names=@($account)
        if($account -and $account -notmatch '[\\@]' -and $ComputerName){$names=@("$ComputerName\$account",$account)}
        $resolved=@()
        foreach($name in $names) {
            try {
                $value=[string](& $Translate $name)
                $canonical=(New-Object Security.Principal.SecurityIdentifier($value)).Value
                $resolved+=@{name=$name;sid=$canonical};$proof.attempts+=@{name=$name;sid=$canonical}
            } catch {$proof.attempts+=@{name=$name;error=$_.Exception.GetType().Name}}
        }
        $unique=@($resolved | ForEach-Object {$_.sid} | Select-Object -Unique)
        if($unique.Count -ne 1){$proof.reason=if($unique.Count){'ambiguous_account_identity'}else{'account_lookup_failed'};return $proof}
        $proof.resolved_sid=$unique[0];$proof.source='account_to_sid_lookup'
    }
    $proof.status=if($proof.resolved_sid -eq $ExpectedSid){'verified'}else{'mismatch'}
    return $proof
}

function Get-HostContract {
    param($Definition,$Spec,[string]$ExpectedSid)
    $d=$Definition
    $principal=Resolve-HostPrincipal -UserId ([string]$d.Principal.UserId) -DefinitionXml ([string]$d.XmlText) -ExpectedSid $ExpectedSid
    $checks=[ordered]@{description=($d.RegistrationInfo.Description -eq $Spec.marker);action_count=($d.Actions.Count -eq 1);
        principal=($principal.status -eq 'verified');interactive_logon=($d.Principal.LogonType -eq 3);least_privilege=($d.Principal.RunLevel -eq 0);
        no_triggers=($d.Triggers.Count -eq 0);unlimited_time=($d.Settings.ExecutionTimeLimit -eq 'PT0S');
        battery_start=(-not $d.Settings.DisallowStartIfOnBatteries);battery_continue=(-not $d.Settings.StopIfGoingOnBatteries);
        ignore_new=($d.Settings.MultipleInstances -eq 2);demand_start=[bool]$d.Settings.AllowDemandStart;enabled=[bool]$d.Settings.Enabled}
    if($d.Actions.Count -eq 1) {
        $checks['python']=($d.Actions.Item(1).Path -ieq $Spec.python);$checks['arguments']=($d.Actions.Item(1).Arguments -ceq $Spec.arguments)
        $checks['working_directory']=($d.Actions.Item(1).WorkingDirectory -ieq $Spec.working_directory)
    }
    $failed=@($checks.Keys | Where-Object {-not $checks[$_]})
    return @{ok=($failed.Count -eq 0);checks=$checks;failed_checks=$failed;principal=$principal}
}
