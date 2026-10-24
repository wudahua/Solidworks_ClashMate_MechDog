import asyncio
import copy
import ctypes
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.lease_access import open_lease_file
from scripts.upgrade import UpgradeFailure, upgrade
from sw_mcp import job_payload
from sw_mcp.bridge import Bridge, CadError
from test_service import temporary_workspace
import test_alpha5 as fixtures


class LeaseTests(unittest.TestCase):
    def test_real_windows_share_denial_and_byte_lock_are_distinct_from_access_denial(self):
        self.assertEqual(os.name,'nt')
        with temporary_workspace() as directory:
            root=Path(directory); (root/'runs').mkdir(); lock=root/'runs/executor-owner.lock';lock.write_bytes(b'0')
            helper=root/'holder.py'
            helper.write_text('import sys\nfrom scripts.lease_access import open_lease_file\nimport ctypes\nk=ctypes.WinDLL("kernel32",use_last_error=True)\nk.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_void_p]\nk.CreateFileW.restype=ctypes.c_void_p\nk.CloseHandle.argtypes=[ctypes.c_void_p]\nh=k.CreateFileW(sys.argv[1],0xC0000000,1,None,3,0x80,None)\nassert h!=ctypes.c_void_p(-1).value\nprint("ready",flush=True)\nsys.stdin.readline()\nk.CloseHandle(h)\n',encoding='utf-8')
            env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1])}
            holder=subprocess.Popen([sys.executable,str(helper),str(lock)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(),'ready')
                (root/'runs/probe.tmp').write_bytes(b'directory is writable')
                bridge=Bridge(root)
                with self.assertRaises(CadError) as caught:bridge._acquire_lease()
                self.assertEqual(caught.exception.code,'MCP_OWNER_ALREADY_RUNNING')
                self.assertTrue(caught.exception.diagnostics['sharing_conflict_proven'])
                self.assertEqual(caught.exception.diagnostics['winerror'],32)
                self.assertFalse(caught.exception.diagnostics['cad_dispatched'])
                from scripts.upgrade import idle_installation
                with self.assertRaises(UpgradeFailure) as caught:
                    with idle_installation(root):pass
                self.assertEqual(caught.exception.code,'UPGRADE_LEASE_BUSY')
            finally:
                holder.communicate('\n',timeout=15)
                self.assertEqual(holder.returncode,0)
            first=Bridge(root); second=Bridge(root)
            try:
                first._acquire_lease()
                with self.assertRaises(CadError) as caught:second._acquire_lease()
                self.assertEqual(caught.exception.code,'MCP_OWNER_ALREADY_RUNNING')
            finally:first.close();second.close()
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.SetFileAttributesW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint]
            self.assertTrue(kernel.SetFileAttributesW(str(lock),1))
            try:
                with self.assertRaises(CadError) as caught:Bridge(root)._acquire_lease()
                self.assertEqual(caught.exception.code,'MCP_LEASE_UNAVAILABLE')
                self.assertEqual(caught.exception.diagnostics['winerror'],5)
                self.assertFalse(caught.exception.diagnostics['sharing_conflict_proven'])
            finally:self.assertTrue(kernel.SetFileAttributesW(str(lock),0x80))
            # Closing the holder is sufficient; no lock deletion or state reset.
            final=Bridge(root);final._acquire_lease();final.close()
            self.assertEqual(lock.read_bytes(),b'0')


class UpgradeEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ReleaseUpgradeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_missing_sidecar_prewrite_and_runtime_mismatch_have_codes(self):
        f=self.fixture
        with self.assertRaises(UpgradeFailure) as caught:upgrade(f.package,f.target,sys.executable,install=False)
        value=caught.exception.payload()
        self.assertEqual(value['error']['code'],'UPGRADE_SIDECAR_MISSING')
        self.assertEqual(value['stage'],'validating_package');self.assertFalse(value['target_mutation_started'])
        self.assertFalse(value['backup_created']);self.assertIsNone(value['rollback_verified'])
        f.write_zip()
        with patch('scripts.upgrade.preflight',side_effect=ValueError('PYTHON_RUNTIME_MISMATCH: use base runtime')):
            with self.assertRaises(UpgradeFailure) as caught:upgrade(f.package,f.target,sys.executable)
        self.assertEqual(caught.exception.payload()['error']['code'],'PYTHON_RUNTIME_MISMATCH')

    def test_rollback_verified_and_incomplete_are_programmatically_distinct(self):
        from scripts.upgrade import write_restored_file
        f=self.fixture;f.write_zip();real_copy=write_restored_file
        def blocked_copy(destination,data):
            if Path(destination).name=='motion_server.py':
                raise PermissionError('controlled rollback file denial')
            return real_copy(destination,data)
        for incomplete in (False,True):
            with patch('scripts.upgrade.idle_installation',return_value=nullcontext()), patch('scripts.upgrade.verify',side_effect=RuntimeError('controlled post-copy failure')), patch('scripts.upgrade.write_restored_file',side_effect=blocked_copy if incomplete else real_copy):
                with self.assertRaises(UpgradeFailure) as caught:upgrade(f.package,f.target,sys.executable,install=False)
            value=caught.exception.payload();expected='incomplete' if incomplete else 'verified'
            self.assertEqual(value['rollback_status'],expected)
            self.assertEqual(value['rollback_verified'],not incomplete)
            self.assertTrue(value['backup_created']);self.assertTrue(value['target_mutation_started'])
            self.assertTrue(value['rollback_attempted']);self.assertFalse(value['committed'])
            self.assertFalse(value['safe_to_start_mcp'])
            self.assertEqual(value['managed_files_consistent'],not incomplete)
            self.assertEqual(json.loads(Path(value['receipt_path']).read_text(encoding='utf-8'))['stage'],value['stage'])
            self.assertEqual(value['error']['code'],'UPGRADE_FAILED_ROLLBACK_INCOMPLETE' if incomplete else 'UPGRADE_FAILED_ROLLBACK_VERIFIED')

    def test_cli_prints_structured_failure_not_bare_exception_string(self):
        import scripts.upgrade as module
        f=self.fixture;output=io.StringIO()
        with patch.object(sys,'argv',['upgrade.py','--package',str(f.package),'--target',str(f.target),'--python',sys.executable]),redirect_stdout(output):
            code=module.main()
        value=json.loads(output.getvalue());self.assertEqual(code,1)
        self.assertIsInstance(value['error'],dict);self.assertEqual(value['error']['code'],'UPGRADE_SIDECAR_MISSING')
        self.assertFalse(value['processes_stopped']);self.assertFalse(value['error']['next_action']['automatic_retry'])

    def test_dry_run_complete_is_typed_and_creates_no_backup(self):
        f=self.fixture;f.write_zip()
        with patch('scripts.upgrade.idle_installation',return_value=nullcontext()):value=upgrade(f.package,f.target,sys.executable,dry_run=True,install=False)
        self.assertEqual(value['schema_version'],2);self.assertEqual(value['stage'],'dry_run_complete')
        self.assertFalse(value['target_mutation_started']);self.assertFalse(value['backup_created'])
        self.assertFalse((f.target/'upgrade-backups').exists())


class EvidenceTests(unittest.TestCase):
    def test_large_validation_and_success_motor_alias_keep_conclusions_and_downgrade(self):
        validation={'status':'pass','kind':'rotary','requested':10,'observed_signed':10.000000001,'unit':'rpm',
                    'magnitude_tolerance':.05,'direction_verified':False,'component_id':'component-real','detail':'x'*20000}
        motor={'status':'observed','persistent_reference_resolved':False,'identity_fallback_used':True,
               'persistent_reference_error':1,'inventory_complete':False,'identity_source':'exact_feature_name_and_native_id','detail':'x'*20000}
        job={'job_id':'b'*32,'status':'succeeded','result':{'drive_validation':validation,'registered_native_motor_before_calculate':motor,
             'drive_validation_status':'pass','result_validity':'verified','padding':{str(i):'x'*2000 for i in range(30)}}}
        with temporary_workspace() as directory:
            root=Path(directory);value=job_payload.bound(root,job)
            self.assertEqual(value['evidence']['drive_validation']['conclusion']['status'],'pass')
            self.assertFalse(value['evidence']['drive_validation']['conclusion']['direction_verified'])
            self.assertTrue(value['evidence']['native_motor_snapshot']['conclusion']['identity_fallback_used'])
            self.assertFalse(value['evidence']['native_motor_snapshot']['conclusion']['persistent_reference_resolved'])
            self.assertEqual(value['evidence']['native_motor_snapshot']['path'],'/result/registered_native_motor_before_calculate')
            self.assertEqual(value['response_wire_bytes'],job_payload.wire_size(value))
            self.assertLessEqual(value['response_wire_bytes'],16000)
            args=value['evidence']['result_identity']['read']['arguments']
            page=job_payload.read(root,args['job_id'],args['response_artifact_id'],0,2000,args['response_json_pointer']+'/drive_validation_status')
            self.assertEqual(json.loads(page['text']),'pass')

    def test_history_usage_distinguishes_verified_summary_from_diagnostic_read(self):
        from sw_mcp.artifacts import Artifacts
        value=Artifacts.history_usage('c'*32)
        self.assertEqual(value['schema_version'],1)
        self.assertEqual(value['default_verified_summary']['tool'],'get_motion_summary')
        self.assertTrue(value['default_verified_summary']['requires_verified_complete_sampling_and_restoration'])
        self.assertEqual(value['quarantine_artifact_query']['tool'],'get_run_artifacts')
        self.assertFalse(value['quarantine_artifact_query']['requires_verified_result'])


if __name__=='__main__':unittest.main()
