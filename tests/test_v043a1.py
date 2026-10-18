import ctypes
import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from scripts.lease_access import open_lease_file,lock_lease_file,lease_diagnostics
from scripts.upgrade import idle_installation,UpgradeFailure
from sw_mcp.bridge import Bridge,CadError
from sw_mcp import job_payload
from sw_mcp.jobs import Jobs
from test_service import temporary_workspace


class FeedbackTests(unittest.TestCase):
    def test_crt_lock_returns_real_win32_33_in_both_consumers(self):
        with temporary_workspace() as directory:
            root=Path(directory);(root/'runs').mkdir();path=root/'runs/executor-owner.lock';path.write_bytes(b'0')
            source='import sys,msvcrt\nf=open(sys.argv[1],"r+b");msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);print("ready",flush=True);sys.stdin.readline();f.close()'
            holder=subprocess.Popen([sys.executable,'-c',source,str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(),'ready')
                for consumer in ('bridge','upgrade'):
                    try:
                        if consumer=='bridge':Bridge(root)._acquire_lease()
                        else:
                            with idle_installation(root):pass
                        self.fail('lock must reject')
                    except (CadError,UpgradeFailure) as error:
                        d=error.diagnostics
                        self.assertEqual(d['winerror'],33);self.assertEqual(d['stage'],'lock_lease')
                        self.assertTrue(d['occupied_proven']);self.assertTrue(d['sharing_conflict_proven'])
                        self.assertTrue(d['byte_lock_conflict_observed']);self.assertIsNone(d['owner_pid'])
                        self.assertEqual(d['native_code_source'],'Win32_GetLastError')
                        self.assertFalse(d['cad_dispatched'])
                        if consumer=='upgrade':self.assertEqual(error.payload()['stage'],'lock_lease')
            finally:holder.communicate('\n',timeout=10)
            with open_lease_file(path) as file:lock_lease_file(file);lock_lease_file(file,unlock=True)
            self.assertEqual(path.read_bytes(),b'0')

    def test_errno_only_is_not_fabricated_as_native_33(self):
        d=lease_diagnostics(Path('example'),PermissionError(13,'access denied'),'lock_lease')
        self.assertIsNone(d['winerror']);self.assertFalse(d['occupied_proven'])
        self.assertFalse(d['byte_lock_conflict_observed'])

    def test_conclusion_dedup_keeps_camelcase_drive_identity_with_large_evidence(self):
        drive={'Study':'R12','ComponentId':'component_'+'a'*24,'EntityId':'entity_'+'b'*24,'Kind':'rotary',
               'Speed':10,'Reverse':False,'Axis':[0,0,-1],'AxisLocal':[0,0,-1],'PointLocal':[.4,0,.02],'padding':'x'*30000}
        value={'requested_drive':drive,'drive_validation':{'status':'pass','direction_verified':False,'requested':10,'unit':'rpm','padding':'x'*30000},
               'registered_native_motor_before_calculate':{'persistent_reference_resolved':False,'identity_fallback_used':True,'padding':'x'*30000},
               **{k:{'padding':'x'*30000} for k in ('artifacts','time_selection_audit','sampling_api_batch','sampling_performance','solve_performance','review_items')}}
        job={'job_id':'a'*32,'status':'succeeded','result':value}
        with temporary_workspace() as directory:
            root=Path(directory);s=job_payload.bound(root,job);e=s['evidence']
            self.assertNotIn('value',e['drive_validation']);self.assertNotIn('value',e['native_motor_snapshot'])
            self.assertEqual(e['requested_drive']['value']['ComponentId'],drive['ComponentId'])
            self.assertEqual(e['requested_drive']['value']['PointLocal'],drive['PointLocal'])
            self.assertFalse(e['drive_validation']['conclusion']['direction_verified'])
            self.assertLessEqual(job_payload.wire_size(s),16000)
            self.assertGreater(s['summary_omitted_prefix_counts']['/result'],0)
            query=e['requested_drive']['read']['arguments']
            page=job_payload.read(root,query['job_id'],query['response_artifact_id'],0,2000,query['response_json_pointer']+'/EntityId')
            self.assertEqual(json.loads(page['text']),drive['EntityId'])

    def test_failure_chain_reads_diagnostics_stage(self):
        self.assertEqual(job_payload.failure_chain({'error':{'code':'BUSY','diagnostics':{'stage':'lock_lease'}}})[0]['stage'],'lock_lease')

    def test_python_cli_utf8_even_with_ascii_parent_ioencoding(self):
        with temporary_workspace() as directory:
            root=Path(directory);(root/'executor').mkdir();(root/'motion_server.py').write_text('x')
            r=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/upgrade.py'),'--package',str(root/'missing.zip'),'--target',str(root),'--python',sys.executable],env={**os.environ,'PYTHONIOENCODING':'ascii'},capture_output=True,timeout=15)
            p=json.loads(r.stdout.decode('utf-8'))
            self.assertEqual(p['error']['code'],'UPGRADE_SIDECAR_MISSING');self.assertIn('缺少',p['error']['message'])
            self.assertIsNone(p['safe_to_start_mcp']);self.assertTrue(p['managed_files_consistent'])
            self.assertEqual(p['receipt_schema_version'],2);self.assertEqual(r.returncode,1)

    def test_failure_has_hashed_top_three_timing_without_CAD_dispatch(self):
        class FailedBridge:
            cad_operation_state='idle'
            def request(self,operation,**params):
                folder=root/'runs'/params['run_id'];folder.mkdir(parents=True)
                (folder/'solve-performance.json').write_text(json.dumps({'schema_version':1,'scope':'RunUserStudy','execution_completed':False,'total_elapsed_ms':10,'phase_totals_ms':{'a':1,'b':4,'c':2,'d':3}}))
                raise CadError('SOLVER_FAILED','failed','restored',{})
        with temporary_workspace() as directory:
            root=Path(directory);jobs=Jobs(FailedBridge(),root)
            job=jobs.submit('run_user_study',{})
            jobs._pool.shutdown(wait=True)
            result=jobs.get(job['job_id']);d=result['error']['diagnostics']
            self.assertEqual(d['solve_performance']['slowest_phases_ms'],{'b':4,'d':3,'c':2})
            self.assertEqual(d['solve_performance']['phase_count'],4)
            self.assertEqual(d['artifacts']['solve_performance_sha256'],hashlib.sha256((root/'runs'/job['job_id']/'solve-performance.json').read_bytes()).hexdigest())


if __name__=='__main__':unittest.main()
