"""Snapshot admission, safe retirement and byte-verified archived rollback."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock,patch
import uuid

from sw_mcp.conversation import core,host_scheduler
from sw_mcp.conversation.installation_scope import require_live_installation,SNAPSHOT_MARKER
from sw_mcp.conversation.owner_transport import OwnerClient
from scripts import host_maintenance as maintenance
from scripts import upgrade as upgrader
import test_alpha5 as upgrade_fixtures
from contextlib import nullcontext

ROOT=Path(__file__).resolve().parents[1]


def folder():
    path=ROOT/'runs/host-retirement-tests'/uuid.uuid4().hex[:8];path.mkdir(parents=True);return path


class AdmissionTests(unittest.TestCase):
    def test_backup_segments_and_marker_are_refused_but_similar_names_are_not(self):
        base=folder()
        for path in (base/'upgrade-backups/x',base/'UPGRADE-BACKUPS/x'):
            with self.assertRaises(core.StopBatch) as error:require_live_installation(path)
            self.assertEqual(error.exception.code,'HOST_BACKUP_TREE_REFUSED')
            self.assertIs(error.exception.diagnostics['launch_attempted'],False)
        require_live_installation(base/'upgrade-backups-comparison')
        (base/SNAPSHOT_MARKER).write_text('{}')
        with self.assertRaises(core.StopBatch):require_live_installation(base/'renamed-child')

    def test_owner_refuses_before_mkdir_and_scheduler_before_native_control(self):
        base=folder();work=base/'upgrade-backups'/'work'
        with patch('sw_mcp.conversation.host_scheduler.subprocess.run') as run:
            with self.assertRaises(core.StopBatch):OwnerClient(ROOT,work,base/'runtime')
            with self.assertRaises(core.StopBatch):host_scheduler.spec_for(work)
            with self.assertRaises(core.StopBatch):host_scheduler.control({'work':str(work),'entry':str(ROOT/'sw_mcp/conversation/owner_entry.py')},'register')
            run.assert_not_called()
        self.assertFalse(work.exists())

    def test_direct_owner_loop_checks_snapshot_before_locks_or_engine(self):
        from sw_mcp.conversation.conversation_owner import serve
        engine=Mock()
        with self.assertRaises(core.StopBatch):serve(folder()/'upgrade-backups/work','a'*32,engine_factory=engine)
        engine.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows native entry guard')
    def test_direct_powershell_registration_is_also_refused_before_RunEx(self):
        base=folder();request=base/'request.json';output=base/'result.json'
        core.write(request,{'mode':'register','name':'ClashMate-Conversation-'+'f'*16,
            'work':str(base/'upgrade-backups/work'),'entry':str(ROOT/'sw_mcp/conversation/owner_entry.py')})
        run=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'sw_mcp/conversation/host_scheduler.ps1'),
            '-Request',str(request),'-Output',str(output)],capture_output=True,timeout=25)
        self.assertNotEqual(run.returncode,0);result=core.read(output)
        self.assertEqual(result['code'],'HOST_BACKUP_TREE_REFUSED');self.assertFalse(result['launch_attempted']);self.assertFalse(result['created'])


class RetirementTests(unittest.TestCase):
    def test_other_installations_and_similar_prefix_paths_are_untouched(self):
        base=folder();install=base/'install';install.mkdir()
        rows=[{'name':'ClashMate-Conversation-'+'a'*16,'arguments':str(base/'other/upgrade-backups/x')},
              {'name':'ClashMate-Conversation-'+'b'*16,'arguments':str(install/'upgrade-backups-other/x')}]
        with patch.object(maintenance,'retire_one') as retire:
            result=maintenance.audit_backup_hosts(install,base/'proof',True,rows)
        self.assertEqual(result['status'],'pass');retire.assert_not_called()

    def test_dry_run_never_sends_shutdown_or_unregisters(self):
        with patch.object(maintenance,'control',return_value={'registered':True,'running_instances':1,'state':4}),patch.object(maintenance,'existing_request') as request:
            value=maintenance.retire_one({'name':'fixture','work':str(folder())},ROOT,False)
        self.assertEqual(value['status'],'would_inspect_running_host');request.assert_not_called()

    def test_active_or_unfinished_owner_is_retained_without_shutdown(self):
        for status in ({'owner_pid':123,'active_task':'busy','prior_unfinished':[]},{'owner_pid':123,'active_task':None,'prior_unfinished':['record']}):
            with (patch.object(maintenance,'control',return_value={'registered':True,'running_instances':1,'state':4}) as control,
                 patch.object(maintenance,'existing_info',return_value={'identity':{'pid':123}}),
                 patch.object(maintenance,'existing_request',return_value=status) as request):
                value=maintenance.retire_one({'name':'fixture','work':str(folder())},ROOT,True)
            self.assertEqual(value['status'],'retained');self.assertEqual(request.call_args.args[-1],'status')
            self.assertEqual(control.call_count,1)

    def test_unknown_original_request_does_not_unregister_or_retry(self):
        with (patch.object(maintenance,'control',return_value={'registered':True,'running_instances':1,'state':4}) as control,
             patch.object(maintenance,'existing_info',return_value={'identity':{'pid':123}}),
             patch.object(maintenance,'existing_request',side_effect=ValueError('outcome unconfirmed')) as request):
            with self.assertRaisesRegex(ValueError,'unconfirmed'):maintenance.retire_one({'name':'fixture','work':str(folder())},ROOT,True)
        self.assertEqual(control.call_count,1);self.assertEqual(request.call_count,1)

    def test_finished_registration_removed_with_contract_checks_and_final_query(self):
        values=[{'registered':True,'running_instances':0,'state':3},{'registered':False},{'registered':False}]
        with patch.object(maintenance,'control',side_effect=values) as control:
            result=maintenance.retire_one({'name':'fixture','work':str(folder())},ROOT,True)
        self.assertEqual(result['status'],'retired');self.assertEqual([c.args[1] for c in control.call_args_list],['query','unregister','query'])
        self.assertFalse(result['cooperative_shutdown_requested'])

    def test_existing_request_allows_only_observation_and_idle_shutdown(self):
        with self.assertRaisesRegex(ValueError,'Only status'):maintenance.existing_request(folder(),{},'prepare')

    def test_unconfirmed_shutdown_reuses_original_request_and_blocks_other_actions(self):
        work=folder();info={'generation':'a'*32,'secret':'b'*64,'identity':{'pid':1,'created':'fixture'}}
        with patch.object(maintenance,'same_process',return_value={'status':'same'}):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'outcome unconfirmed'):maintenance.existing_request(work,info,'shutdown_idle',timeout=0)
            with self.assertRaisesRegex(ValueError,'Prior maintenance'):maintenance.existing_request(work,info,'status',timeout=0)
        requests=list((work/'ipc'/info['generation']/'requests').glob('*.json'));self.assertEqual(len(requests),1)
        marker=core.read(work/'host-maintenance-requests'/(info['generation']+'-shutdown_idle.json'))
        self.assertEqual(marker['request_id'],requests[0].stem);self.assertNotIn('secret',marker)

    @unittest.skipUnless(os.name=='nt','Windows Scheduler')
    def test_real_registered_legacy_backup_task_is_retired_without_running_it(self):
        base=folder();install=base/'install';work=install/'upgrade-backups'/uuid.uuid4().hex/'runs/dialogue'
        entry=work.parents[1]/'sw_mcp/conversation/owner_entry.py';entry.parent.mkdir(parents=True)
        entry.write_text('raise RuntimeError("fixture must never run")\n',encoding='utf8')
        # Construct the old identity manually; new spec_for rightly rejects it.
        python=Path(sys.executable).with_name('pythonw.exe').resolve()
        token=__import__('hashlib').sha256((str(work.resolve()).casefold()+'|'+str(entry.resolve()).casefold()).encode()).hexdigest()[:16]
        spec={'name':'ClashMate-Conversation-'+token,'marker':'ClashMate interactive demand-only host v1 '+token,'python':str(python),
            'work':str(work.resolve()),'entry':str(entry.resolve()),'working_directory':str(entry.parent.resolve()),
            'arguments':subprocess.list2cmdline(['-X','utf8',str(entry.resolve()),'--work',str(work.resolve()),'--generation','$(Arg0)'])}
        # Construct a legacy definition with Windows API in this isolated fixture.
        # Product register/run guards must not be bypassed. No RunEx is called.
        request=base/'register.json';output=base/'registered.json';core.write(request,{**spec,'mode':'register'})
        registrar=base/'legacy-definition.ps1'
        registrar.write_text(r'''param($Request,$Output)
$ErrorActionPreference='Stop';$u=New-Object Text.UTF8Encoding($false);$s=[IO.File]::ReadAllText($Request,$u)|ConvertFrom-Json
$v=New-Object -ComObject 'Schedule.Service';$v.Connect();$f=$v.GetFolder('\');$d=$v.NewTask(0)
$id=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$d.RegistrationInfo.Description=$s.marker;$d.Principal.UserId=$id;$d.Principal.LogonType=3;$d.Principal.RunLevel=0
$d.Settings.Enabled=$true;$d.Settings.AllowDemandStart=$true;$d.Settings.ExecutionTimeLimit='PT0S';$d.Settings.MultipleInstances=2
$d.Settings.DisallowStartIfOnBatteries=$false;$d.Settings.StopIfGoingOnBatteries=$false
$a=$d.Actions.Create(0);$a.Path=$s.python;$a.Arguments=$s.arguments;$a.WorkingDirectory=$s.working_directory
$null=$f.RegisterTaskDefinition($s.name,$d,2,$id,$null,3,$null)
[IO.File]::WriteAllText($Output,'{"ok":true}',$u)
''',encoding='utf8',newline='\n')
        run=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(registrar),
            '-Request',str(request),'-Output',str(output)],capture_output=True,timeout=25)
        self.assertEqual(run.returncode,0,run.stderr.decode(errors='replace'))
        try:
            value=maintenance.audit_backup_hosts(install,base/'proof',True)
            self.assertEqual(value['status'],'pass',value);self.assertEqual(len(value['retired_host_tasks']),1)
            self.assertFalse(host_scheduler.control(spec,'query')['registered'])
        finally:
            state=host_scheduler.control(spec,'query')
            if state['registered'] and not state.get('running_instances'):host_scheduler.control(spec,'unregister')


class ArchiveTests(unittest.TestCase):
    def fixture(self):
        f=upgrade_fixtures.ReleaseUpgradeTests();f.setUp();self.addCleanup(f.doCleanups);f.write_zip();return f

    def test_snapshot_has_no_executable_source_tree_and_preserves_original_bytes(self):
        f=self.fixture()
        with patch.object(upgrader,'idle_installation',return_value=nullcontext()):result=upgrader.upgrade(f.package,f.target,sys.executable,install=False)
        backup=Path(result['backup_directory']);self.assertEqual(upgrader.read_backup(result)['motion_server.py'],b'old source')
        self.assertFalse((backup/'motion_server.py').exists());self.assertFalse(list(backup.rglob('*.py')))
        self.assertTrue((backup/SNAPSHOT_MARKER).is_file());self.assertEqual(result['backup_format'],'managed-source-zip-v1')
        with self.assertRaises(core.StopBatch):require_live_installation(backup)

    def test_archive_corruption_is_never_treated_as_verified_rollback(self):
        f=self.fixture()
        with patch.object(upgrader,'idle_installation',return_value=nullcontext()):result=upgrader.upgrade(f.package,f.target,sys.executable,install=False)
        Path(result['backup_archive']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'):upgrader.read_backup(result)

    def test_host_unknown_blocks_upgrade_before_managed_mutation(self):
        f=self.fixture();before=(f.target/'motion_server.py').read_bytes()
        with patch.object(upgrader,'preflight',return_value={'solidworks_install_dir':'fixture'}),patch.object(upgrader,'audit_backup_hosts',return_value={'status':'review_required','retired_host_tasks':[],'retained_hosts':[{'reason':'unknown'}]}):
            with self.assertRaises(upgrader.UpgradeFailure) as error:upgrader.upgrade(f.package,f.target,sys.executable)
        self.assertEqual(error.exception.code,'UPGRADE_BACKUP_HOSTS_REQUIRE_REVIEW')
        self.assertEqual((f.target/'motion_server.py').read_bytes(),before);self.assertFalse(error.exception.state['target_mutation_started'])

    def test_postcommit_cleanup_uncertainty_is_reported_separately_without_false_rollback(self):
        f=self.fixture()
        with (patch.object(upgrader,'preflight',return_value={'solidworks_install_dir':'fixture'}),patch.object(upgrader,'idle_installation',return_value=nullcontext()),
             patch.object(upgrader,'audit_backup_hosts',side_effect=[{'status':'pass','retired_host_tasks':[]},ValueError('inventory changed')]),patch.object(upgrader.subprocess,'run')):
            result=upgrader.upgrade(f.package,f.target,sys.executable)
        self.assertTrue(result['committed']);self.assertEqual(result['host_cleanup_status'],'review_required');self.assertFalse(result['rollback_attempted'])


if __name__=='__main__':unittest.main(verbosity=2)
