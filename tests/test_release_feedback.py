"""Exact-byte diagnostics, root-name compatibility and upgrade rollback regression."""
import concurrent.futures
import hashlib
import json
import subprocess
import sys
import unittest
import uuid
import zipfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_release import ReleaseSourceMismatch, validate_manifest, source_mismatch
from scripts.upgrade import package_files, upgrade
from sw_mcp.bridge import Bridge, CadError
from transport_cleanup import remove_test_root
from test_alpha5 import contents

class ReleaseFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.base=ROOT/'runs/release-feedback';self.root=self.base/uuid.uuid4().hex[:8];self.root.mkdir(parents=True)
        self.addCleanup(remove_test_root,self.root,self.base)
        self.target=self.root/'target';self.target.mkdir();(self.target/'executor/bin').mkdir(parents=True)
        (self.target/'motion_server.py').write_bytes(b'old source');(self.target/'executor/bin/SwExecutor.exe').write_bytes(b'old binary')
        for d in ('.venv','runs','experiments'):
            (self.target/d).mkdir();(self.target/d/'keep.txt').write_bytes(b'keep')
        self.journal=self.target/'runs/executor-state.json';self.journal.write_bytes(b'{"status":"unknown","executor_pid":2147480000}')
        self.package=self.root/'source.zip'
    def files(self):
        files=contents();files['LICENSE']=b'first line\nsecond line\n'
        m=json.loads(files['发布清单.json']);m['files'].append({'path':'LICENSE','bytes':len(files['LICENSE']),'sha256':hashlib.sha256(files['LICENSE']).hexdigest()})
        files['发布清单.json']=json.dumps(m,ensure_ascii=False).encode();return files
    def write_zip(self,files=None,root='Solidworks_ClashMate_MechDog'):
        files=self.files() if files is None else files
        with zipfile.ZipFile(self.package,'w') as z:
            for n,b in files.items():z.writestr(root+'/'+n,b)
        self.package.with_suffix('.zip.sha256').write_text(hashlib.sha256(self.package.read_bytes()).hexdigest()+'  source.zip\n',encoding='utf-8')
        return files
    def test_crlf_is_diagnosed_but_still_rejected_without_modification(self):
        files=self.files();m=json.loads(files['发布清单.json']);files['LICENSE']=files['LICENSE'].replace(b'\n',b'\r\n');before=dict(files)
        with self.assertRaises(ReleaseSourceMismatch) as caught:validate_manifest(m,files.__getitem__)
        e=caught.exception;self.assertEqual(e.code,'LINE_ENDING_MISMATCH');self.assertIn('upgrade.ps1',str(e));self.assertEqual(e.mismatches[0]['diagnostic_conversion'],'CRLF_to_LF');self.assertFalse(e.mismatches[0]['exact_bytes_verified']);self.assertEqual(files,before)
    def test_inverse_line_ending_conversion_is_diagnostic_only(self):
        expected=b'a\r\nb\r\n';record={'bytes':len(expected),'sha256':hashlib.sha256(expected).hexdigest()}
        result=source_mismatch('LICENSE',b'a\nb\n',record);self.assertEqual(result['diagnostic_conversion'],'LF_to_CRLF');self.assertEqual(result['code'],'LINE_ENDING_MISMATCH')
    def test_whitespace_bom_and_text_edits_are_not_line_ending_equivalence(self):
        original=b'a\nb\n';record={'bytes':len(original),'sha256':hashlib.sha256(original).hexdigest()}
        for actual in (b'a \r\nb\r\n',b'\xef\xbb\xbfa\nb\n',b'a\r\nchanged\r\n',b'\xff\r\n'):
            self.assertEqual(source_mismatch('LICENSE',actual,record)['code'],'RELEASE_SOURCE_MISMATCH')
    def test_cli_emits_structured_failure_and_nonzero_exit(self):
        files=self.files();files['LICENSE']=files['LICENSE'].replace(b'\n',b'\r\n');fixture=self.root/'fixture'
        for n,b in files.items():p=fixture/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
        p=subprocess.run([sys.executable,str(ROOT/'scripts/verify_release.py'),'--root',str(fixture)],capture_output=True,timeout=15)
        self.assertEqual(p.returncode,1);data=json.loads(p.stdout);self.assertFalse(data['all_passed']);self.assertEqual(data['code'],'LINE_ENDING_MISMATCH');self.assertEqual(data['mismatch_count'],1);self.assertFalse(p.stderr)
    def test_mixed_edits_keep_distinct_diagnostics(self):
        files=self.files();m=json.loads(files['发布清单.json']);files['LICENSE']=files['LICENSE'].replace(b'\n',b'\r\n');files['tests/new_case.py']+=b'# local edit\n'
        with self.assertRaises(ReleaseSourceMismatch) as caught:validate_manifest(m,files.__getitem__)
        self.assertEqual(caught.exception.code,'RELEASE_SOURCE_MISMATCH');self.assertEqual({x['code'] for x in caught.exception.mismatches},{'LINE_ENDING_MISMATCH','RELEASE_SOURCE_MISMATCH'})
    def test_old_and_new_archive_roots_are_accepted(self):
        for name in ('SolidWorksMotionMCP','Solidworks_ClashMate_MechDog'):
            self.write_zip(root=name);m,_,_=package_files(self.package);self.assertEqual(m['version'],'0.4.1-alpha.5')
    def test_mixed_roots_are_rejected_before_upgrade(self):
        self.write_zip()
        with zipfile.ZipFile(self.package,'a') as z:z.writestr('SolidWorksMotionMCP/extra.py',b'bad')
        self.package.with_suffix('.zip.sha256').write_text(hashlib.sha256(self.package.read_bytes()).hexdigest()+'  source.zip',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Mixed ZIP roots'):package_files(self.package)
    def test_filename_mismatch_is_actionable_and_remains_strict(self):
        self.write_zip();self.package.with_suffix('.zip.sha256').write_text(hashlib.sha256(self.package.read_bytes()).hexdigest()+'  official-source.zip',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'expected official-source.zip; actual source.zip.*Rename'):package_files(self.package)
    def test_install_success_is_not_committed_if_final_bytes_drift(self):
        self.write_zip();before=self.journal.read_bytes()
        def installer(*a,**k):
            p=self.target/'LICENSE';p.write_bytes(p.read_bytes().replace(b'\n',b'\r\n'))
            return subprocess.CompletedProcess(a,0)
        with patch('scripts.upgrade.preflight',return_value={'solidworks_install_dir':'test-sw'}),patch('scripts.upgrade.idle_installation',return_value=nullcontext()),patch('scripts.upgrade.subprocess.run',side_effect=installer):
            with self.assertRaisesRegex(RuntimeError,'rollback recorded'):upgrade(self.package,self.target,sys.executable)
        self.assertEqual((self.target/'motion_server.py').read_bytes(),b'old source');self.assertEqual((self.target/'executor/bin/SwExecutor.exe').read_bytes(),b'old binary');self.assertEqual(self.journal.read_bytes(),before)
        receipt=json.loads(next((self.target/'upgrade-backups').glob('*/receipt.json')).read_text(encoding='utf-8'));self.assertFalse(receipt['committed']);self.assertTrue(receipt['rollback_verified']);self.assertIn('LINE_ENDING_MISMATCH',receipt['error'])
    def test_official_byte_replacement_backs_up_crlf_and_preserves_state(self):
        files=self.write_zip();crlf=files['LICENSE'].replace(b'\n',b'\r\n');(self.target/'LICENSE').write_bytes(crlf);before=self.journal.read_bytes()
        with patch('scripts.upgrade.idle_installation',return_value=nullcontext()):result=upgrade(self.package,self.target,sys.executable,install=False)
        self.assertTrue(result['source_integrity_verified']);self.assertEqual((self.target/'LICENSE').read_bytes(),files['LICENSE']);self.assertEqual((Path(result['backup_directory'])/'LICENSE').read_bytes(),crlf);self.assertEqual(self.journal.read_bytes(),before)
        for d in ('.venv','runs','experiments'):self.assertEqual((self.target/d/'keep.txt').read_bytes(),b'keep')
    def test_reconciliation_wrong_pid_reports_action_without_journal_change(self):
        model='user_'+'a'*32;cp='b'*32;folder=self.target/'experiments/user_assemblies'/('a'*32);(folder/'checkpoints'/cp).mkdir(parents=True)
        (folder/'model.json').write_text(json.dumps({'Id':model}));(folder/'checkpoints'/cp/'checkpoint.json').write_text(json.dumps({'model_id':model}));before=self.journal.read_bytes();bridge=Bridge(self.target)
        bridge._startup.set_result({'ready':True,'protocol_version':1,'process_id':22,'executor_id':'test','executor_pid':33})
        with patch.object(bridge,'_start'),patch.object(bridge,'_acquire_lease'),patch.object(bridge,'_pid_alive',return_value=False),patch.object(bridge,'request') as request:
            with self.assertRaises(CadError) as caught:bridge.reconcile_missing_identity(model_id=model,checkpoint_id=cp,solidworks_pid=23,journal_sha256=hashlib.sha256(before).hexdigest(),operation_ended_confirmed=True)
        self.assertEqual(caught.exception.code,'RECOVERY_SESSION_MISMATCH');self.assertEqual(caught.exception.diagnostics['required_param'],'solidworks_pid');self.assertEqual(caught.exception.diagnostics['connected_solidworks_pid'],22);request.assert_not_called();self.assertEqual(self.journal.read_bytes(),before)

if __name__=='__main__':unittest.main()
