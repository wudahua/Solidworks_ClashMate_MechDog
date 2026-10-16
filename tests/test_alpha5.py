"""Release integrity and source upgrades preserve state; explicit probes never run by default."""
import asyncio
import hashlib
import json
import sys
import subprocess
import unittest
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_release import verify, validate_manifest
from scripts.upgrade import package_files, upgrade
from sw_mcp.bridge import Bridge
from transport_cleanup import remove_test_root

def contents(version='0.4.1-alpha.5'):
    files={'motion_server.py':f'version="{version}"\n'.encode(),'executor/UserMotion.cs':f'version="{version}"\n'.encode(),'scripts/build_release.py':f'VERSION = "{version}"\n'.encode(),'install.ps1':b'# test installer never runs CAD\n','tests/new_case.py':b'# source\n'}
    manifest={'version':version,'files':[{'path':p,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for p,b in files.items()]}
    files['发布清单.json']=json.dumps(manifest,ensure_ascii=False).encode();return files

class ReleaseUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.base=ROOT/'runs/alpha5-python';self.root=self.base/uuid.uuid4().hex[:8];self.root.mkdir(parents=True);self.addCleanup(remove_test_root,self.root,self.base)
        self.target=self.root/'old';self.target.mkdir();self.package=self.root/'source.zip'
        for directory in ('.venv','runs','experiments'):
            p=self.target/directory;p.mkdir();(p/'keep.txt').write_bytes(b'USER_DATA_KEEP')
        (self.target/'runs/executor-state.json').write_text('{"status":"unknown","request_id":"keep-unknown"}')
        (self.target/'motion_server.py').write_bytes(b'old source');(self.target/'executor/bin').mkdir(parents=True);(self.target/'executor/bin/SwExecutor.exe').write_bytes(b'old binary')
    def write_zip(self,files=None):
        with zipfile.ZipFile(self.package,'w') as z:
            for n,b in (files or contents()).items():z.writestr('SolidWorksMotionMCP/'+n,b)
        digest=hashlib.sha256(self.package.read_bytes()).hexdigest();self.package.with_suffix('.zip.sha256').write_text(digest+'  source.zip\n');return files or contents()
    def test_manifest_detects_version_drift_even_with_consistent_hashes(self):
        files=contents();m=json.loads(files['发布清单.json']);m['version']='0.4.1-alpha.4'
        with self.assertRaisesRegex(ValueError,'version mismatch'):validate_manifest(m,files.__getitem__)
    def test_zip_rejects_modified_source(self):
        files=contents();files['executor/UserMotion.cs']=b'tampered';self.write_zip(files)
        with self.assertRaisesRegex(ValueError,'source mismatch'):package_files(self.package)
    def test_zip_rejects_unknown_runtime_and_traversal(self):
        for name in ('runs/executor-state.json','../outside.py'):
            files=contents();files[name]=b'bad';self.write_zip(files)
            with self.assertRaises(ValueError):package_files(self.package)
        self.assertFalse((self.root/'outside.py').exists())
    def test_zip_rejects_missing_module_and_wrong_sha_sidecar(self):
        files=contents();del files['tests/new_case.py'];self.write_zip(files)
        with self.assertRaises(KeyError):package_files(self.package)
        self.write_zip();self.package.with_suffix('.zip.sha256').write_text('0'*64+'  source.zip')
        with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):package_files(self.package)
    def test_verified_upgrade_preserves_data_and_unknown_journal(self):
        files=self.write_zip();journal=(self.target/'runs/executor-state.json').read_bytes()
        with patch('scripts.upgrade.idle_installation',return_value=nullcontext()):result=upgrade(self.package,self.target,sys.executable,install=False)
        self.assertTrue(result['committed']);self.assertTrue(result['recovery_journal_unchanged']);self.assertEqual((self.target/'runs/executor-state.json').read_bytes(),journal)
        for d in ('.venv','runs','experiments'):self.assertEqual((self.target/d/'keep.txt').read_bytes(),b'USER_DATA_KEEP')
        self.assertEqual((Path(result['backup_directory'])/'motion_server.py').read_bytes(),b'old source');self.assertEqual((self.target/'motion_server.py').read_bytes(),files['motion_server.py']);self.assertTrue(verify(self.target)['all_passed'])
    def test_failed_compile_restores_old_source_and_binary(self):
        self.write_zip()
        def failing(*a,**kw):
            (self.target/'executor/bin/SwExecutor.exe').write_bytes(b'failed new binary')
            (self.target/'executor/bin/build-manifest.json').write_bytes(b'new manifest')
            raise RuntimeError('controlled compiler failure')
        with patch('scripts.upgrade.preflight',return_value={'solidworks_install_dir':'test-sw'}),patch('scripts.upgrade.idle_installation',return_value=nullcontext()),patch('scripts.upgrade.subprocess.run',side_effect=failing):
            with self.assertRaisesRegex(RuntimeError,'rollback recorded'):upgrade(self.package,self.target,sys.executable)
        self.assertEqual((self.target/'motion_server.py').read_bytes(),b'old source');self.assertEqual((self.target/'executor/bin/SwExecutor.exe').read_bytes(),b'old binary');self.assertFalse((self.target/'executor/bin/build-manifest.json').exists());self.assertFalse((self.target/'tests/new_case.py').exists())
    def test_dry_run_does_not_change_sources(self):
        self.write_zip();
        with patch('scripts.upgrade.preflight',return_value={'solidworks_install_dir':'test-sw'}),patch('scripts.upgrade.idle_installation',return_value=nullcontext()):result=upgrade(self.package,self.target,sys.executable,dry_run=True);
        self.assertTrue(result['dry_run']);self.assertEqual((self.target/'motion_server.py').read_bytes(),b'old source');self.assertFalse((self.target/'upgrade-backups').exists())
    def test_running_installation_is_rejected_before_copy(self):
        self.write_zip()
        with patch('scripts.upgrade.idle_installation',side_effect=RuntimeError('MCP still running')):
            with self.assertRaisesRegex(RuntimeError,'MCP still running'):upgrade(self.package,self.target,sys.executable,install=False)
        self.assertEqual((self.target/'motion_server.py').read_bytes(),b'old source')
    def test_old_journal_has_current_compatibility_field_without_disk_write(self):
        path=self.target/'runs/executor-state.json';path.write_text('{"schema_version":2,"status":"idle","dispatch_state":"dispatching"}');before=path.read_bytes();state=Bridge(self.target).recovery_state()
        self.assertEqual(state['dispatch_state'],'completed');self.assertEqual(state['observed_dispatch_state'],'dispatching');self.assertFalse(state['dispatch_field_consistent']);self.assertEqual(state['journal_schema_version'],2);self.assertEqual(path.read_bytes(),before)

class ProbePublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_preflight_does_not_enqueue_or_calculate(self):
        import motion_server
        async def fake(*a,**k):return k
        with patch.object(motion_server,'call',side_effect=fake),patch.object(motion_server,'enqueue') as job:
            await motion_server.preflight_motion('user_'+'a'*32);job.assert_not_called()
    async def test_explicit_probe_enqueues_bounded_copy_operation(self):
        import motion_server
        with patch.object(motion_server,'enqueue',return_value={'job_id':'test'}) as job:
            await motion_server.preflight_motion('user_'+'a'*32,'Study',True,.1,30)
        self.assertEqual(job.call_args.args[0],'probe_motion_compatibility');self.assertEqual(job.call_args.args[1]['duration_s'],.1)
    async def test_unsupported_probe_budget_never_queues(self):
        import motion_server
        with patch.object(motion_server,'enqueue') as job:
            with self.assertRaises(Exception):await motion_server.preflight_motion('user_'+'a'*32,'Study',True,6,30)
            job.assert_not_called()

class ProbeRecoveryTests(unittest.TestCase):
    def test_unknown_probe_binds_recovery_to_probe_and_preserves_original_identity(self):
        from transport_cleanup import drain_bridge
        base=ROOT/'runs/alpha5-protocol';root=base/uuid.uuid4().hex[:8];root.mkdir(parents=True)
        original='user_'+'a'*32;run='b'*32;probe='user_'+run
        helper=root/'helper.py';helper.write_text('''import json,sys
print(json.dumps({'protocol_version':1,'ready':True,'process_id':22,'revision':'34.0.0'}),flush=True)
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({'id':r['id'],'ok':False,'error':{'code':'COMPATIBILITY_PROBE_RECOVERY_REQUIRED','message':'controlled','restoration_status':'unknown','diagnostics':{'details':{'affected_model_id':'user_'+r['params']['run_id']}}}}),flush=True)
''',encoding='utf-8')
        exe=root/'executor/bin/SwExecutor.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'test fake executable')
        bridge=Bridge(root,timeout=5);real=subprocess.Popen
        def start(*a,**kw):return real([sys.executable,str(helper)],**kw)
        try:
            with patch('sw_mcp.bridge.subprocess.Popen',side_effect=start):
                with self.assertRaises(Exception):bridge.request('probe_motion_compatibility',model_id=original,run_id=run,study='Study',duration_s=1,output_fps=30)
            state=bridge.recovery_state();self.assertEqual(state['status'],'unknown');self.assertEqual(state['model_id'],probe);self.assertEqual(state['params']['model_id'],original)
            with self.assertRaises(Exception) as error:bridge.request('restore_model_checkpoint',model_id=original,checkpoint_id='c'*32)
            self.assertEqual(error.exception.code,'RECOVERY_MODEL_MISMATCH')
        finally:drain_bridge(bridge);remove_test_root(root,base)

if __name__=='__main__':unittest.main()
