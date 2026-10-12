"""Regression checks for real feedback failure boundaries; no CAD connection."""
import hashlib
import json
import csv
import sys
import tempfile
import shutil
import uuid
import unittest
from concurrent.futures import Future
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge,CadError
from sw_mcp.artifacts import Artifacts,ArtifactError
from sw_mcp.jobs import Jobs

class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'runs/rt'
        base.mkdir(parents=True,exist_ok=True)
        self.base=base.resolve()
        self.root=base/uuid.uuid4().hex[:8]
        self.root.mkdir()
        self.bridges=[]

    def tearDown(self):
        for bridge in self.bridges:bridge.close()
        self.root.resolve().relative_to(self.base)
        if self.root.is_symlink():raise RuntimeError("Unexpected test workspace link")
        shutil.rmtree(self.root)

    def bridge(self, hello=None):
        bridge=Bridge(self.root)
        self.bridges.append(bridge)
        if hello is not None:
            bridge._process=SimpleNamespace(pid=900001,poll=lambda:None,stdin=StringIO())
            bridge._startup.set_result(hello)
        return bridge

    def test_failed_handshake_is_rejected_on_every_retry_without_journal(self):
        bridge=self.bridge({'ready':False,'protocol_version':1,'error':{'code':'EXECUTOR_ALREADY_RUNNING','message':'busy'}})
        for _ in range(2):
            with self.assertRaises(CadError) as error:bridge.request('check_interference')
            self.assertEqual(error.exception.code,'EXECUTOR_ALREADY_RUNNING')
            self.assertFalse(bridge._journal_path.exists())
            self.assertEqual(bridge._process.stdin.getvalue(),'')

    def test_invalid_identity_never_dispatches(self):
        for pid in (None,False,0,-1,'22'):
            with self.assertRaises(CadError) as error:Bridge._validate_hello({'ready':True,'protocol_version':1,'process_id':pid})
            self.assertEqual(error.exception.code,'COM_IDENTITY_MISSING')

    def test_second_owner_cannot_overwrite_first_journal(self):
        first=self.bridge();first._acquire_lease();first._journal({'status':'unknown','request_id':'preserve'})
        before=first._journal_path.read_bytes();second=self.bridge()
        with self.assertRaises(CadError) as error:second.request('get_environment')
        self.assertEqual(error.exception.code,'MCP_OWNER_ALREADY_RUNNING')
        self.assertEqual(before,first._journal_path.read_bytes())

    def test_missing_pid_does_not_authorize_replacement(self):
        bridge=self.bridge({'ready':True,'protocol_version':1,'process_id':22})
        bridge._journal({'status':'unknown','executor_pid':12,'solidworks_pid':None})
        with patch.object(bridge,'_pid_alive',return_value=False):
            for allow in (False,True):
                with self.assertRaises(CadError) as error:bridge.request('restore_model_checkpoint',model_id='user_'+'a'*32,checkpoint_id='b'*32,allow_replacement_session=allow)
                self.assertEqual(error.exception.code,'RECOVERY_IDENTITY_MISSING')
        self.assertTrue(Bridge._pid_alive(None))

    def test_manual_reconciliation_requires_confirmation_and_unchanged_journal(self):
        bridge=self.bridge();bridge._journal({'status':'unknown','executor_pid':12,'solidworks_pid':None})
        params=dict(model_id='user_'+'a'*32,checkpoint_id='b'*32,solidworks_pid=22,journal_sha256='0'*64)
        with self.assertRaises(CadError) as error:bridge.reconcile_missing_identity(**params,operation_ended_confirmed=False)
        self.assertEqual(error.exception.code,'MANUAL_RECONCILIATION_REQUIRED')
        with self.assertRaises(CadError) as error:bridge.reconcile_missing_identity(**params,operation_ended_confirmed=True)
        self.assertEqual(error.exception.code,'RECOVERY_JOURNAL_CHANGED')
        self.assertTrue(bridge.recovery_state()['recovery_required'])

    def test_manual_reconciliation_archives_then_keeps_unknown_until_restore(self):
        identifier='user_'+'a'*32;checkpoint_id='b'*32
        folder=self.root/'experiments/user_assemblies'/identifier[5:]
        cp=folder/'checkpoints'/checkpoint_id;cp.mkdir(parents=True)
        (folder/'model.json').write_text(json.dumps({'Id':identifier}),encoding='utf-8')
        (cp/'checkpoint.json').write_text(json.dumps({'model_id':identifier}),encoding='utf-8')
        bridge=self.bridge({'ready':True,'protocol_version':1,'process_id':22})
        bridge._journal({'status':'unknown','executor_pid':12,'solidworks_pid':None,'model_id':identifier})
        raw=bridge._journal_path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        def failed_restore(*args,**kwargs):
            state=bridge.recovery_state()
            self.assertTrue(state['recovery_required']);self.assertEqual(state['status'],'unknown')
            self.assertEqual(state['solidworks_pid'],22)
            self.assertEqual((self.root/'runs/recovery-audit'/(digest+'.json')).read_bytes(),raw)
            raise CadError('BAD_CHECKPOINT','failure')
        with patch.object(bridge,'_pid_alive',return_value=False),patch.object(bridge,'request',side_effect=failed_restore):
            with self.assertRaises(CadError):bridge.reconcile_missing_identity(model_id=identifier,checkpoint_id=checkpoint_id,solidworks_pid=22,journal_sha256=digest,operation_ended_confirmed=True)
        self.assertTrue(bridge.recovery_state()['recovery_required'])

    def test_manual_reconciliation_refuses_live_owner_and_wrong_model(self):
        identifier='user_'+'a'*32
        bridge=self.bridge();bridge._journal({'status':'unknown','executor_pid':12,'solidworks_pid':None,'model_id':identifier})
        digest=hashlib.sha256(bridge._journal_path.read_bytes()).hexdigest()
        params=dict(model_id='user_'+'b'*32,checkpoint_id='c'*32,solidworks_pid=22,journal_sha256=digest,operation_ended_confirmed=True)
        with patch.object(bridge,'_pid_alive',return_value=True):
            with self.assertRaises(CadError) as error:bridge.reconcile_missing_identity(**params)
            self.assertEqual(error.exception.code,'PREVIOUS_EXECUTOR_ALIVE')
        with patch.object(bridge,'_pid_alive',return_value=False):
            with self.assertRaises(CadError) as error:bridge.reconcile_missing_identity(**params)
            self.assertEqual(error.exception.code,'RECOVERY_MODEL_MISMATCH')

    def test_failed_job_keeps_native_diagnostics_and_run_id(self):
        class Failure:
            cad_operation_state='available'
            def request(self,*args,**kwargs):raise CadError('RESTORATION_FAILED','failed','unknown',{'run_id':kwargs['run_id'],'translation_m':0.003})
        jobs=Jobs(Failure(),self.root);submitted=jobs.submit('run_user_study',{})
        jobs._pool.shutdown(wait=True);job=jobs.get(submitted['job_id'])
        self.assertEqual(job['status'],'failed')
        self.assertEqual(job['error']['diagnostics']['run_id'],job['params']['run_id'])

    def artifact(self):
        identifier='a'*32;folder=self.root/'runs'/identifier;folder.mkdir(parents=True)
        path=folder/'component-poses.csv'
        with path.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['frame','time_s','component_id','instance','x_m','y_m','z_m','r00','r01','r02','r10','r11','r12','r20','r21','r22'])
            for frame,x in enumerate([0,0.015,0]):writer.writerow([frame,frame/2,'component_a','moving',x,0,0,1,0,0,0,1,0,0,0,1])
        (folder/'solve.json').write_text(json.dumps({'run_id':identifier,'restoration_status':'unknown','result_validity':'inconclusive','poses_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}),encoding='utf-8')
        return identifier,path

    def test_quarantined_artifacts_remain_readable_with_pagination(self):
        identifier,path=self.artifact();artifacts=Artifacts(self.root)
        first=artifacts.poses(identifier,limit=1);second=artifacts.poses(identifier,limit=1,cursor=first['next_cursor'])
        self.assertEqual(first['rows'][0]['x_m'],0);self.assertEqual(second['rows'][0]['x_m'],0.015)
        self.assertEqual(second['result_validity'],'inconclusive')
        self.assertEqual(second['current_model_validity'],'not_checked_offline')
        self.assertTrue(artifacts.summary(identifier)['poses_available'])

    def test_artifact_integrity_and_filter_bound_cursors(self):
        identifier,path=self.artifact();artifacts=Artifacts(self.root);first=artifacts.poses(identifier,limit=1)
        with self.assertRaises(ValueError):artifacts.poses(identifier,component_id='other',cursor=first['next_cursor'])
        path.write_text(path.read_text(encoding='utf-8')+'\n',encoding='utf-8')
        with self.assertRaises(ValueError):artifacts.poses(identifier)
        with self.assertRaises(ValueError):artifacts.summary('../other')

    def test_legacy_csv_is_readable_but_has_no_historical_integrity_claim(self):
        identifier,path=self.artifact();(path.parent/'solve.json').unlink()
        before=path.read_bytes();artifacts=Artifacts(self.root)
        summary=artifacts.summary(identifier);page=artifacts.poses(identifier,limit=1)
        self.assertEqual(summary['manifest_status'],'absent')
        self.assertEqual(summary['artifact_integrity'],'hash_not_recorded')
        self.assertEqual(page['result_validity'],'inconclusive')
        self.assertEqual(page['restoration_status'],'unknown')
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((path.parent/'solve.json').exists())

    def test_missing_run_manifest_and_poses_have_distinct_errors(self):
        artifacts=Artifacts(self.root)
        with self.assertRaises(ArtifactError) as error:artifacts.summary('f'*32)
        self.assertEqual(error.exception.code,'RUN_NOT_FOUND')
        folder=self.root/'runs'/('f'*32);folder.mkdir(parents=True)
        with self.assertRaises(ArtifactError) as error:artifacts.summary('f'*32)
        self.assertEqual(error.exception.code,'MANIFEST_MISSING')
        identifier,path=self.artifact();path.unlink()
        with self.assertRaises(ArtifactError) as error:artifacts.poses(identifier)
        self.assertEqual(error.exception.code,'POSES_MISSING')
        self.assertNotIn(str(self.root),str(error.exception))

    def test_corrupt_manifest_cannot_fall_back_to_legacy_csv(self):
        identifier,path=self.artifact();(path.parent/'solve.json').write_text('{bad',encoding='utf-8')
        with self.assertRaises(ArtifactError) as error:Artifacts(self.root).summary(identifier)
        self.assertEqual(error.exception.code,'MANIFEST_INVALID')

    def test_legacy_csv_rejects_nonfinite_values_beyond_first_page(self):
        identifier,path=self.artifact();(path.parent/'solve.json').unlink()
        path.write_text(path.read_text(encoding='utf-8').replace('0.015','nan'),encoding='utf-8')
        with self.assertRaises(ArtifactError) as error:Artifacts(self.root).poses(identifier,limit=1)
        self.assertEqual(error.exception.code,'POSES_INVALID')

    def test_startup_retry_requires_explicit_no_session_and_no_prior_dispatch(self):
        bridge=self.bridge({'protocol_version':1,'ready':False,'error':{'code':'COM_SESSION_NOT_FOUND'}})
        self.assertTrue(bridge._retryable_startup_failure())
        bridge._ever_dispatched=True
        self.assertFalse(bridge._retryable_startup_failure())
        bridge._ever_dispatched=False;bridge._journal({'status':'unknown'})
        self.assertFalse(bridge._retryable_startup_failure())
        other=self.bridge({'protocol_version':1,'ready':False,'error':{'code':'EXECUTOR_ALREADY_RUNNING'}})
        self.assertFalse(other._retryable_startup_failure())

    def test_dead_failed_startup_reconnects_but_ready_executor_loss_does_not(self):
        bridge=self.bridge({'protocol_version':1,'ready':False,'error':{'code':'COM_SESSION_NOT_FOUND'}})
        bridge._process.poll=lambda:1;bridge._process.stdout=StringIO()
        bridge._reader_thread=SimpleNamespace(join=lambda timeout:None,is_alive=lambda:False)
        (self.root/'executor/bin').mkdir(parents=True);(self.root/'executor/bin/SwExecutor.exe').write_bytes(b'not executed')
        process=SimpleNamespace(pid=900002,poll=lambda:None,stdin=StringIO(),stdout=StringIO())
        def hello():bridge._startup.set_result({'protocol_version':1,'ready':True,'process_id':22})
        with patch('sw_mcp.bridge.subprocess.Popen',return_value=process),patch('sw_mcp.bridge.threading.Thread',return_value=SimpleNamespace(start=hello)):
            bridge._start()
        self.assertIs(bridge._process,process)
        process.poll=lambda:1
        with self.assertRaises(CadError) as error:bridge._start()
        self.assertEqual(error.exception.code,'EXECUTOR_LOST')

    def test_finished_job_progress_is_terminal_and_late_native_progress_cannot_replace_it(self):
        class Failure:
            cad_operation_state='unknown_after_timeout'
            def request(self,*args,**kwargs):raise CadError('CAD_TIMEOUT','still unknown')
        jobs=Jobs(Failure(),self.root);submitted=jobs.submit('run_user_study',{})
        jobs._pool.shutdown(wait=True)
        progress=self.root/'runs/progress'/(submitted['job_id']+'.json')
        job=jobs.get(submitted['job_id'])
        self.assertEqual(job['progress']['stage'],'timed_out')
        self.assertFalse(job['progress']['cad_operation_finished'])
        progress.write_text(json.dumps({'job_id':submitted['job_id'],'stage':'native_calculate'}),encoding='utf-8')
        self.assertEqual(jobs.get(submitted['job_id'])['progress']['stage'],'timed_out')

if __name__=='__main__':unittest.main()
