import csv,hashlib,json,sys,shutil,unittest,uuid
import os,time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.artifacts import Artifacts,ArtifactError
from sw_mcp.bridge import Bridge
from sw_mcp.jobs import Jobs
from scripts.local_storage import inventory,delete_run

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'runs/feedback-tests'/uuid.uuid4().hex[:8];self.root.mkdir(parents=True)
        self.run='a'*32;self.folder=self.root/'runs'/self.run;self.folder.mkdir(parents=True)
        self.csv=self.folder/'component-poses.csv'
        fields=['frame','time_s','component_id','instance','x_m','y_m','z_m','r00','r01','r02','r10','r11','r12','r20','r21','r22']
        with self.csv.open('w',newline='',encoding='utf-8') as out:
            writer=csv.writer(out);writer.writerow(fields)
            for i in range(3):writer.writerow([i,i/5,'component_a','part',i*.002,0,0,1,0,0,0,1,0,0,0,1])
        self.data={'run_id':self.run,'poses_sha256':hashlib.sha256(self.csv.read_bytes()).hexdigest(),'sampling_status':'completed','native_time_axis_verified':True,'frames':3,'output_fps':5,'duration_s':.4,'result_validity':'inconclusive','restoration_status':'unknown'}
        self.save()
    def save(self):(self.folder/'solve.json').write_text(json.dumps(self.data),encoding='utf-8')
    def tearDown(self):
        self.root.resolve().relative_to((ROOT/'runs/feedback-tests').resolve())
        if self.root.is_symlink():raise RuntimeError('test root link')
        shutil.rmtree(self.root)
    def test_explicit_history_export_without_cad_retains_inconclusive_and_unknown(self):
        with patch.object(Bridge,'request',side_effect=AssertionError('COM must not be called')):
            result=Artifacts(self.root).export_history_curve(self.run,'component_a','linear_velocity','x')
        self.assertFalse(result['physical_validation_claim']);self.assertEqual(result['result_validity'],'inconclusive');self.assertEqual(result['restoration_status'],'unknown');self.assertAlmostEqual(result['max'],.01)
        self.assertTrue(Path(result['metadata_path']).is_file())
    def test_history_export_rejects_changed_hash(self):
        self.csv.write_text(self.csv.read_text()+'\n',encoding='utf-8')
        with self.assertRaises(ArtifactError) as error:Artifacts(self.root).export_history_curve(self.run,'component_a','position','x')
        self.assertEqual(error.exception.code,'ARTIFACT_HASH_MISMATCH')
    def test_history_export_requires_complete_verified_sampling(self):
        for key,value in [('native_time_axis_verified',False),('sampling_status','not_completed'),('poses_sha256','')]:
            original=self.data[key];self.data[key]=value;self.save()
            with self.assertRaises(ArtifactError):Artifacts(self.root).export_history_curve(self.run,'component_a','position','x')
            self.data[key]=original
    def test_history_export_rejects_missing_frames_and_component(self):
        self.data['frames']=4;self.save()
        with self.assertRaises(ArtifactError):Artifacts(self.root).export_history_curve(self.run,'component_a','position','x')
        self.data['frames']=3;self.save()
        with self.assertRaises(ArtifactError):Artifacts(self.root).export_history_curve(self.run,'absent','position','x')
    def test_history_export_rejects_path_component(self):
        with self.assertRaises(ValueError):Artifacts(self.root).export_history_curve(self.run,'../outside','position','x')
    def test_job_execution_success_is_not_verification_pass(self):
        class FakeBridge:
            cad_operation_state='available'
            def request(self,*args,**kwargs):return {'assertion':'inconclusive','verification_status':'inconclusive'}
        jobs=Jobs(FakeBridge(),self.root)
        with patch.object(jobs._pool,'submit'):
            job=jobs.submit('verify_motion_preservation',{})
        jobs._execute(job['job_id']);result=jobs.get(job['job_id']);jobs._pool.shutdown()
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['verification_status'],'inconclusive')
    def test_recovery_busy_description_does_not_relax_guard(self):
        bridge=Bridge(self.root)
        bridge._journal({'status':'active','owner_id':bridge._owner_id,'request_id':'current'})
        state=bridge.recovery_state();self.assertTrue(state['recovery_required']);self.assertEqual(state['cad_request_policy'],'wait_for_current_request')
        bridge._journal({'status':'unknown','owner_id':bridge._owner_id})
        self.assertTrue(bridge.recovery_state()['requires_checkpoint_restore']);bridge.close()
    def old_terminal_run(self):
        self.data.update(restoration_status='restored',solver_status='completed',sampling_status='completed',finished_at='2026-10-01T00:00:00Z');self.save()
        stamp=time.time()-10*86400;os.utime(self.folder,(stamp,stamp))
    def test_storage_inventory_never_deletes(self):
        self.old_terminal_run();report=inventory(self.root)
        self.assertFalse(report['deletion_performed']);self.assertTrue(self.folder.exists())
        self.assertTrue(report['run_candidates'][0]['eligible_for_explicit_cleanup'])
    def test_storage_preserves_latest_and_unknown_recovery(self):
        self.old_terminal_run();history=self.root/'runs/study-history/model';history.mkdir(parents=True)
        (history/'study.json').write_text(json.dumps({'run_id':self.run}),encoding='utf-8')
        self.assertIn('latest_study_run_or_active_job',inventory(self.root)['run_candidates'][0]['protected_reasons'])
        (self.root/'runs/executor-state.json').write_text(json.dumps({'status':'unknown'}),encoding='utf-8')
        with self.assertRaises(ValueError):delete_run(self.root,self.run,self.run)
        self.assertTrue(self.folder.exists())
    def test_storage_requires_double_identity_and_service_lease(self):
        self.old_terminal_run()
        with self.assertRaises(ValueError):delete_run(self.root,self.run,'wrong')
        first=Bridge(self.root);first._acquire_lease()
        try:
            with self.assertRaises(Exception):delete_run(self.root,self.run,self.run)
            self.assertTrue(self.folder.exists())
        finally:first.close()
    def test_explicit_storage_cleanup_only_selected_old_run(self):
        self.old_terminal_run();checkpoint=self.root/'experiments/user_assemblies/model/checkpoints/keep';checkpoint.mkdir(parents=True);(checkpoint/'checkpoint.json').write_text('{}',encoding='utf-8')
        result=delete_run(self.root,self.run,self.run)
        self.assertTrue(result['deletion_performed']);self.assertFalse(self.folder.exists());self.assertTrue(checkpoint.exists())

if __name__=='__main__':unittest.main()
