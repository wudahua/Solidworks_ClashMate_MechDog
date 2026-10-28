"""Host file-policy compatibility and interrupted rollback; no CAD or network.

The injected sitecustomize is a controlled fixture, not the WorkBuddy shim.
All denials remain in force: the upgrader must not select a bypass API.
"""
import json
import os
import subprocess
import sys
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import patch

from scripts import upgrade as updater
import test_alpha5 as fixtures

ROOT=Path(__file__).resolve().parents[1]


class UpgradeHostRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ReleaseUpgradeTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture;self.f.write_zip()
        self.before=(self.f.target/'runs/executor-state.json').read_bytes()

    def installation(self,installer):
        stack=ExitStack()
        stack.enter_context(patch('scripts.upgrade.preflight',return_value={'solidworks_install_dir':'test-sw'}))
        stack.enter_context(patch('scripts.upgrade.audit_backup_hosts',return_value={'status':'pass','retired_host_tasks':[]}))
        stack.enter_context(patch('scripts.upgrade.idle_installation',return_value=nullcontext()))
        stack.enter_context(patch('scripts.upgrade.subprocess.run',side_effect=installer))
        return stack

    def original_files_restored(self):
        self.assertEqual((self.f.target/'motion_server.py').read_bytes(),b'old source')
        self.assertEqual((self.f.target/'executor/bin/SwExecutor.exe').read_bytes(),b'old binary')
        self.assertEqual((self.f.target/'runs/executor-state.json').read_bytes(),self.before)
        for directory in ('.venv','runs','experiments'):
            self.assertEqual((self.f.target/directory/'keep.txt').read_bytes(),b'USER_DATA_KEEP')

    def test_native_api_with_benign_sitecustomize_and_pythonpath_is_not_rejected(self):
        with patch.dict(sys.modules,{'sitecustomize':object()}),patch.dict(os.environ,{'PYTHONPATH':'benign-location'}):
            with patch('scripts.upgrade.idle_installation',return_value=nullcontext()):
                result=updater.upgrade(self.f.package,self.f.target,sys.executable,install=False)
            self.assertTrue(result['committed'])
            self.assertTrue(result['python_runtime']['sitecustomize_loaded'])
            self.assertTrue(result['python_runtime']['pythonpath_present'])
            self.assertFalse(result['python_runtime']['host_guards_bypassed'])
            self.assertEqual(os.environ['PYTHONPATH'],'benign-location')

    def test_external_unlink_wrapper_refused_before_preflight_lease_backup_and_source_write(self):
        def denied(*a,**k):raise SystemExit(1)
        with patch.object(Path,'unlink',denied),patch('scripts.upgrade.preflight') as preflight,patch('scripts.upgrade.idle_installation') as lease:
            with self.assertRaises(updater.UpgradeFailure) as caught:
                updater.upgrade(self.f.package,self.f.target,sys.executable)
            self.assertIs(Path.unlink,denied)
            preflight.assert_not_called();lease.assert_not_called()
        value=caught.exception.payload()
        self.assertEqual(value['code'],'UPGRADE_FILE_API_CHECK_FAILED')
        self.assertEqual(value['stage'],'checking_python_file_api')
        self.assertFalse(value['target_mutation_started']);self.assertFalse(value['backup_created'])
        self.assertFalse(value['error']['next_action']['automatic_retry'])
        self.assertEqual(value['python_runtime']['file_api_admission'],'guarded_probe_failed')
        self.assertTrue(Path(value['file_api_checks'][0]['probe_path']).is_file())
        self.assertFalse((self.f.target/'upgrade-backups').exists())
        self.original_files_restored()

    def test_spoofed_module_name_does_not_prove_native_function(self):
        def denied(*a,**k):raise SystemExit(1)
        denied.__module__='pathlib'
        with patch.object(Path,'unlink',denied):
            self.assertFalse(updater.file_api_observation()['standard_path_unlink_observed'])

    def test_functional_host_wrapper_is_kept_and_upgrade_can_commit(self):
        original=Path.unlink;calls=[]
        def host_policy(path,*a,**k):
            self.assertIn('upgrade-api-checks',path.parts)
            calls.append(path)
            return original(path,*a,**k)
        with patch.object(Path,'unlink',host_policy),patch('scripts.upgrade.idle_installation',return_value=nullcontext()):
            result=updater.upgrade(self.f.package,self.f.target,sys.executable,install=False)
            self.assertIs(Path.unlink,host_policy)
        self.assertTrue(result['committed'])
        self.assertEqual(result['python_runtime']['file_api_admission'],'guarded_probe_passed')
        self.assertEqual(len(calls),2)
        self.assertTrue(all(not path.exists() for path in calls))
        self.assertTrue(all(json.loads(Path(c['record_path']).read_text('utf-8'))['status']=='pass' for c in result['file_api_checks']))
        self.assertEqual((self.f.target/'runs/executor-state.json').read_bytes(),self.before)

    def test_silent_noop_wrapper_fails_owned_probe_before_source_mutation(self):
        def no_op(*a,**k):return None
        with patch.object(Path,'unlink',no_op):
            with self.assertRaises(updater.UpgradeFailure) as caught:
                updater.upgrade(self.f.package,self.f.target,sys.executable,install=False)
        self.assertEqual(caught.exception.code,'UPGRADE_FILE_API_CHECK_FAILED')
        check=caught.exception.state['file_api_checks'][0]
        self.assertEqual(check['failure']['type'],'RuntimeError')
        self.assertTrue(Path(check['probe_path']).is_file())
        self.assertFalse((self.f.target/'upgrade-backups').exists())
        self.original_files_restored()

    def test_api_change_during_preflight_refused_again_under_lease(self):
        def denied(*a,**k):raise SystemExit(1)
        def preflight(*a,**k):
            Path.unlink=denied
            return {'solidworks_install_dir':'test-sw'}
        with patch.object(Path,'unlink',Path.unlink),patch('scripts.upgrade.preflight',side_effect=preflight),patch('scripts.upgrade.audit_backup_hosts',return_value={'status':'pass','retired_host_tasks':[]}),patch('scripts.upgrade.idle_installation',return_value=nullcontext()):
            with self.assertRaises(updater.UpgradeFailure) as caught:
                updater.upgrade(self.f.package,self.f.target,sys.executable)
        self.assertEqual(caught.exception.code,'UPGRADE_FILE_API_CHECK_FAILED')
        self.assertEqual(caught.exception.state['stage'],'checking_python_file_api_under_lease')
        self.assertFalse((self.f.target/'upgrade-backups').exists())
        self.original_files_restored()

    def test_systemexit_from_installer_restores_bytes_and_preserves_original_exit_code(self):
        def interrupted(*a,**k):
            (self.f.target/'executor/bin/SwExecutor.exe').write_bytes(b'partial binary')
            raise SystemExit(17)
        with self.installation(interrupted):
            with self.assertRaises(updater.UpgradeFailure) as caught:
                updater.upgrade(self.f.package,self.f.target,sys.executable)
        value=caught.exception.payload()
        self.assertEqual(value['code'],'UPGRADE_FAILED_ROLLBACK_VERIFIED')
        self.assertEqual(value['error']['diagnostics']['original_failure'],{'type':'SystemExit','message':'17','exit_code':17})
        self.assertTrue(value['rollback_verified']);self.assertFalse(value['committed'])
        self.assertFalse((self.f.target/'tests/new_case.py').exists())
        self.original_files_restored()

    def test_mid_transaction_delete_denial_kept_in_force_while_other_originals_restore(self):
        original=Path.unlink
        for denial in (SystemExit(1),KeyboardInterrupt(),PermissionError('host policy denied')):
            with self.subTest(type=type(denial).__name__):
                denied_calls=[]
                def guarded(path,*a,**k):
                    if path==self.f.target/'tests/new_case.py':
                        denied_calls.append(str(path));raise denial
                    return original(path,*a,**k)
                def installer(*a,**k):
                    (self.f.target/'executor/bin/SwExecutor.exe').write_bytes(b'partial binary')
                    Path.unlink=guarded
                    raise RuntimeError('controlled compile failure')
                with patch.object(Path,'unlink',original),self.installation(installer):
                    with self.assertRaises(updater.UpgradeFailure) as caught:
                        updater.upgrade(self.f.package,self.f.target,sys.executable)
                    self.assertIs(Path.unlink,guarded)
                value=caught.exception.payload()
                self.assertEqual(value['code'],'UPGRADE_FAILED_ROLLBACK_INCOMPLETE')
                self.assertFalse(value['rollback_verified']);self.assertEqual(value['installation_state'],'mixed_or_unknown')
                self.assertEqual(len(denied_calls),1)  # No retry or alternate delete API.
                self.assertTrue((self.f.target/'tests/new_case.py').is_file())
                self.assertFalse((self.f.target/'executor/UserMotion.cs').exists())
                failures=value['error']['diagnostics']['rollback_failures']
                self.assertTrue(any(x['path']=='tests/new_case.py' and x['type']==type(denial).__name__ for x in failures))
                receipt=json.loads(Path(value['receipt_path']).read_text('utf-8'))
                self.assertEqual(receipt['rollback_failures'],failures)
                self.original_files_restored()
                # Fixture resets via the same now-unwrapped API, outside the
                # transaction. The product never removes the denied file.
                (self.f.target/'tests/new_case.py').unlink()

    def test_restore_denial_does_not_skip_rest_of_backup(self):
        real_restore=updater.write_restored_file
        def restore(path,data):
            if path.name=='motion_server.py':raise SystemExit('restore denied')
            real_restore(path,data)
        def installer(*a,**k):
            (self.f.target/'executor/bin/SwExecutor.exe').write_bytes(b'partial binary')
            raise RuntimeError('controlled compiler failure')
        with self.installation(installer),patch('scripts.upgrade.write_restored_file',side_effect=restore):
            with self.assertRaises(updater.UpgradeFailure) as caught:
                updater.upgrade(self.f.package,self.f.target,sys.executable)
        self.assertEqual(caught.exception.code,'UPGRADE_FAILED_ROLLBACK_INCOMPLETE')
        self.assertEqual((self.f.target/'executor/bin/SwExecutor.exe').read_bytes(),b'old binary')
        self.assertFalse((self.f.target/'tests/new_case.py').exists())
        self.assertTrue(any(x['operation']=='restore_original' and x['type']=='SystemExit' for x in caught.exception.state['rollback_failures']))

    def test_recovery_receipt_denial_preserves_last_receipt_and_byte_verdict(self):
        write_text=Path.write_text
        def guarded(path,data,*a,**k):
            if path.name=='receipt.tmp' and 'failed_rollback_verified' in data:
                raise SystemExit('receipt denied')
            return write_text(path,data,*a,**k)
        with patch('scripts.upgrade.idle_installation',return_value=nullcontext()),patch('scripts.upgrade.verify',side_effect=RuntimeError('controlled verify failure')),patch.object(Path,'write_text',guarded):
            with self.assertRaises(updater.UpgradeFailure) as caught:
                updater.upgrade(self.f.package,self.f.target,sys.executable,install=False)
        value=caught.exception.payload()
        self.assertEqual(value['code'],'UPGRADE_RECOVERY_RECEIPT_FAILED')
        self.assertTrue(value['rollback_verified'])  # Bytes restored, receipt not.
        self.assertEqual(value['receipt_stage_persisted'],'copying_sources')
        self.assertEqual(value['receipt_write_error'],'receipt denied')
        self.assertEqual(value['error']['diagnostics']['receipt_failure']['type'],'SystemExit')
        previous=json.loads(Path(value['receipt_path']).read_text('utf-8'))
        self.assertEqual(previous['stage'],'copying_sources')
        self.original_files_restored()

    def test_systemexit_during_source_copy_is_rolled_back(self):
        original=Path.write_bytes
        def interrupted(path,data):
            if path==self.f.target/'executor/UserMotion.cs':raise SystemExit('copy interrupted')
            return original(path,data)
        with patch('scripts.upgrade.idle_installation',return_value=nullcontext()),patch.object(Path,'write_bytes',interrupted):
            with self.assertRaises(updater.UpgradeFailure) as caught:
                updater.upgrade(self.f.package,self.f.target,sys.executable,install=False)
        self.assertEqual(caught.exception.code,'UPGRADE_FAILED_ROLLBACK_VERIFIED')
        self.original_files_restored()

    def subprocess_case(self,powershell=False):
        shim=self.f.root/'shim';shim.mkdir()
        marker=self.f.root/'guard-called.txt'
        (shim/'sitecustomize.py').write_text('import pathlib\ndef _safe_path_unlink(self,*a,**k):\n    pathlib.Path('+repr(str(marker))+').write_text("called")\n    raise SystemExit(1)\npathlib.Path.unlink=_safe_path_unlink\n',encoding='utf-8')
        env=dict(os.environ)
        env['PYTHONPATH']=str(shim)+os.pathsep+env.get('PYTHONPATH','')
        command=[sys.executable,str(ROOT/'scripts/upgrade.py'),'--package',str(self.f.package),'--target',str(self.f.target),'--python',sys.executable,'--dry-run']
        if powershell:
            command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'upgrade.ps1'),'-SourcePackage',str(self.f.package),'-TargetDir',str(self.f.target),'-PythonPath',sys.executable,'-DryRun']
        result=subprocess.run(command,env=env,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        value=json.loads(result.stdout.decode('utf-8-sig'))
        self.assertEqual(value['code'],'UPGRADE_FILE_API_CHECK_FAILED')
        self.assertTrue(value['python_runtime']['sitecustomize_loaded'])
        self.assertTrue(value['python_runtime']['pythonpath_present'])
        self.assertFalse(value['python_runtime']['python_environment_modified'])
        self.assertFalse(value['target_mutation_started']);self.assertFalse(value['backup_created'])
        self.assertTrue(marker.exists());self.assertFalse((self.f.target/'upgrade-backups').exists())
        self.assertEqual(value['file_api_checks'][0]['failure']['type'],'SystemExit')
        self.assertTrue(Path(value['file_api_checks'][0]['probe_path']).is_file())
        self.original_files_restored()

    def test_actual_python_child_keeps_injected_policy_and_returns_structured_prewrite_refusal(self):
        self.subprocess_case()

    def test_uncatchable_child_exit_preserves_pending_receipt_and_backup_without_false_rollback(self):
        program='''import os,sys
from contextlib import nullcontext
from unittest.mock import patch
from scripts.upgrade import upgrade
def exit_now(*a,**k):os._exit(73)
with patch('scripts.upgrade.idle_installation',return_value=nullcontext()),patch('scripts.upgrade.verify',side_effect=exit_now):
    upgrade(sys.argv[1],sys.argv[2],sys.executable,install=False)
'''
        result=subprocess.run([sys.executable,'-c',program,str(self.f.package),str(self.f.target)],cwd=ROOT,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,73,result.stdout+result.stderr)
        receipt=json.loads(next((self.f.target/'upgrade-backups').glob('*/receipt.json')).read_text('utf-8'))
        self.assertEqual(receipt['stage'],'copying_sources')
        self.assertFalse(receipt['committed']);self.assertFalse(receipt['rollback_attempted'])
        self.assertIsNone(receipt['rollback_verified'])
        self.assertEqual(updater.read_backup(receipt)['motion_server.py'],b'old source')
        self.assertNotEqual((self.f.target/'motion_server.py').read_bytes(),b'old source')
        self.assertEqual((self.f.target/'runs/executor-state.json').read_bytes(),self.before)

    @unittest.skipUnless(os.name=='nt','PowerShell wrapper requires Windows')
    def test_actual_powershell_wrapper_inherits_policy_and_preserves_json_diagnostics(self):
        self.subprocess_case(powershell=True)


if __name__=='__main__':unittest.main()
