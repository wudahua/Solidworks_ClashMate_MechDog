"""Finite-stroke audit and archived-result binding; all fixtures are offline."""
import asyncio,copy,json,math,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp.conversation import working_stroke as w,core,driven_loop_motion
from sw_mcp import connection_trials as trials
from tests import test_driven_loop_motion as loop_fixtures

R=Path(__file__).resolve().parents[1]


class WorkingStrokeAuditTests(unittest.TestCase):
    def value(self,stroke=.01,frames=31):
        poses,bounds,review,_=loop_fixtures.DrivenLoopMotionTests().value()
        grid=[{cid:trials.target(p,[0,0,1],stroke*i/(frames-1)) if cid!='frame' else list(p) for cid,p in poses.items()} for i in range(frames)]
        return poses,bounds,review,grid
    def test_10mm_is_explicit_working_scope_and_does_not_weaken_old_small_trial(self):
        p,b,r,grid=self.value();result=w.audit(grid,p,b,r,.01)
        self.assertTrue(result['passed']);self.assertEqual(result['pose_rows'],124)
        self.assertFalse(result['whole_travel_certified'] or result['global_DOF_certified'] or result['contact_or_force_validated'])
        self.assertFalse(driven_loop_motion.audit(grid,p,b,r,.01)['passed'])
    def test_longer_exact_grid_and_negative_direction(self):
        p,b,r,grid=self.value(-.02,61);v=w.audit(grid,p,b,r,-.02,2,30)
        self.assertTrue(v['passed']);self.assertEqual(v['frames'],61);self.assertAlmostEqual(v['actual_input_m'],-.02)
    def test_partial_wrong_direction_missing_component_and_mid_frame_joint_failure(self):
        p,b,r,grid=self.value()
        with self.assertRaises(core.StopBatch):w.audit(grid[:30],p,b,r,.01)
        self.assertFalse(w.audit(grid,p,b,r,-.01)['passed'])
        for cid in ('frame','output'):
            p,b,r,grid=self.value();grid[15][cid][9]+=.001
            self.assertFalse(w.audit(grid,p,b,r,.01)['passed'])
        p,b,r,grid=self.value();grid[8].pop('output')
        with self.assertRaises(core.StopBatch):w.audit(grid,p,b,r,.01)
    def test_unchanged_output_and_incomplete_goal_scope_fail(self):
        p,b,r,grid=self.value()
        for f in grid:f['output']=list(p['output'])
        self.assertFalse(w.audit(grid,p,b,r,.01)['passed'])
        p,b,r,grid=self.value();p['uncovered']=list(p['frame'])
        with self.assertRaises(core.StopBatch):w.audit(grid,p,b,r,.01)
    def test_input_envelope_and_strict_parameters(self):
        p,b,r,grid=self.value()
        for value in (0,.02001,True,float('nan'),float('inf'),'0.01'):
            with self.assertRaises(core.StopBatch):w.audit(grid,p,b,r,value)
        for duration,fps in ((True,30),(1,True),(6,30),(1,121)):
            with self.assertRaises(core.StopBatch):w.audit(grid,p,b,r,.01,duration,fps)
    def test_all_component_translation_envelope_even_when_joints_hold(self):
        p,b,r,grid=self.value(.06)
        # The declared input is kept inside policy; transform overshoot still
        # fails both the complete waveform and the separate component envelope.
        result=w.audit(grid,p,b,r,.02)
        self.assertFalse(result['passed']);self.assertFalse(result['sample_audits'][-1]['component_envelope_passed'])


class WorkingStrokeBindingTests(unittest.TestCase):
    def setUp(self):
        self.root=R/'runs'/('working-stroke-fixture-'+uuid.uuid4().hex);self.root.mkdir()
        p,b,r,grid=WorkingStrokeAuditTests().value();self.original=[];self.current=[];source=self.root/'saved';source.mkdir()
        assembly=source/'model.SLDASM';assembly.write_bytes(b'fake assembly: offline fixture only')
        self.oldid='a'*32;self.newid='b'*32;self.model='user_'+'c'*32
        self.folder=self.root/('task-'+self.newid)/'session';self.folder.mkdir(parents=True)
        olddir=self.root/('task-'+self.oldid);(olddir/'session').mkdir(parents=True)
        modeldir=self.root/'runtime/experiments/user_assemblies'/self.model[5:];copies=modeldir/'files';copies.mkdir(parents=True)
        files={str(assembly):core.digest(assembly)};copy_paths=[]
        for cid,pose in p.items():
            part=source/(cid+'.SLDPRT');part.write_bytes(('fake-part-'+cid).encode());files[str(part)]=core.digest(part)
            target=copies/('0001_hash_'+part.name);target.write_bytes(part.read_bytes());copy_paths.append(str(target))
            old={'component_id':cid,'instance':cid+'-1','path':str(part),'configuration':'Default','fixed_component':cid=='frame','transform':pose,'loaded':True,'subassembly':False,'suppressed':False,'speedpak':False}
            self.original.append(old);self.current.append({**old,'component_id':'new-'+cid,'path':str(target),'instance':target.stem+'-1'})
        target=copies/'model.SLDASM';target.write_bytes(assembly.read_bytes());copy_paths.append(str(target))
        core.write(modeldir/'model.json',{'Id':self.model,'Files':copy_paths});core.write(modeldir/'import-evidence.json',{'copy_paths':copy_paths,'source_hashes':files})
        snap=olddir/'session/checkpoint.json';core.write(snap,{'files':files})
        core.write(olddir/'session/成果检查点.json',{'checkpoint':{'checkpoint_path':str(snap)},'inspection':{'components':self.original,'mates':[]}})
        self.old={'task_id':self.oldid,'directory':str(olddir),'closed':True,'task_kind':'assembly_constraints',
            'verification':{'declared_scope_passed':True,'whole_assembly_declared_targets_passed':True,'native_motion_study_solved':True},
            'proposal':{'goals':b,'driven_loop_review':r},'finish':{'cleanup_status':'pass','source_files_unchanged':True,
            'session':{'committed_copy_preserved':True},'native_exit':{'normal_zero_exit':True,'force_kill':False},'executor_exit':{'confirmed':True,'executor_exit_code':0,'force_kill':False},
            'result_assembly_path':str(assembly),'result_assembly_sha256':core.digest(assembly)}}
        core.write(olddir/'任务状态.json',self.old)
        self.task={'task_id':self.newid,'source':str(assembly),'motion_parameters':{'motion':'linear','expected_travel':10,'reverse_direction':False,'duration_s':1,'output_fps':30}}
        self.s=SimpleNamespace(folder=self.folder,runtime=self.root/'runtime',model=self.model,initial_inspection={'components':self.current,'mates':[]})
        self.engine=SimpleNamespace(tasks={self.oldid:self.old},work=self.root)
        self.candidate={'drive':{'component_id':'new-'+r['primary']['component_a'],'entity_id':'offline-face','kind':'planar_normal','axis_global':[0,0,1],'face_in_surface_sense':False,'face_normal_global':[0,0,1]},'reference':{'component_id':'new-'+r['primary']['component_b']}}
    def bind(self):return w.bind(self.engine,self.task,self.s,self.oldid,self.candidate)
    def test_exact_kept_result_binds_all_occurrences_poses_and_targets_without_CAD(self):
        summary=self.bind();self.assertEqual(summary['components'],4);self.assertEqual(summary['joint_targets'],4)
        value=w.load(self.s,summary);self.assertEqual(set(value['poses']),{'new-'+c['component_id'] for c in self.original})
        self.assertEqual(value['requested_input_m'],.01)
    def test_mutated_source_old_proof_and_binding_are_rejected(self):
        summary=self.bind();old=Path(self.old['directory'])/'任务状态.json';old.write_bytes(old.read_bytes()+b' ')
        with self.assertRaises(core.StopBatch):w.load(self.s,summary)
        self.setUp();summary=self.bind();p=Path(self.task['source']);p.write_bytes(b'changed')
        with self.assertRaises(core.StopBatch):w.load(self.s,summary)
        self.setUp();summary=self.bind();p=Path(summary['binding_path']);p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(core.StopBatch):w.load(self.s,summary)
    def test_unverified_unclosed_unkept_and_nonzero_cleanup_rejected(self):
        for section,key,value in ((self.old,'closed',False),(self.old['verification'],'declared_scope_passed',False),(self.old['finish']['session'],'committed_copy_preserved',False),(self.old['finish']['native_exit'],'normal_zero_exit',False)):
            before=section[key];section[key]=value
            with self.assertRaises(core.StopBatch):self.bind()
            section[key]=before
    def test_wrong_axis_reference_pose_configuration_or_occurrence_rejected(self):
        for which in ('axis','reference','pose','configuration','ordinal'):
            self.setUp()
            if which=='axis':self.candidate['drive']['axis_global']=[1,0,0]
            elif which=='reference':self.candidate['reference']['component_id']='new-output'
            elif which=='pose':self.current[1]['transform']=trials.target(self.current[1]['transform'],[0,0,1],.001)
            elif which=='configuration':self.current[1]['configuration']='other'
            else:self.current[1]['instance']=self.current[0]['instance']
            with self.assertRaises(core.StopBatch):self.bind()
    def test_native_part_copy_hash_and_dependency_set_are_required(self):
        Path(self.current[1]['path']).write_bytes(b'corrupt')
        with self.assertRaises(core.StopBatch):self.bind()
        self.setUp();p=self.s.runtime/'experiments/user_assemblies'/self.model[5:]/'import-evidence.json';v=core.read(p);v['source_hashes'].pop(next(iter(v['source_hashes'])));core.write(p,v)
        with self.assertRaises(core.StopBatch):self.bind()
    def test_signed_axis_binding_is_chosen_before_any_motion(self):
        self.task['motion_parameters']['reverse_direction']=True
        self.assertEqual(w.load(self.s,self.bind())['requested_input_m'],-.01)
    def test_missing_loop_scope_and_force_exit_do_not_fall_through_to_internal_error(self):
        for change in ('scope','native_force','executor_force','missing_force'):
            self.setUp()
            if change=='scope':self.old['proposal']['driven_loop_review']=None
            elif change=='native_force':self.old['finish']['native_exit']['force_kill']=True
            elif change=='executor_force':self.old['finish']['executor_exit']['force_kill']=True
            else:self.old['finish']['executor_exit'].pop('force_kill')
            with self.assertRaises(core.StopBatch) as raised:self.bind()
            self.assertEqual(raised.exception.code,'CONNECTION_EVIDENCE_FAILED')


class WorkingStrokeProtocolTests(unittest.TestCase):
    def test_formal_plan_preserves_history_ID_and_rejects_invalid_types(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={'b'*32:{}},plan=Mock(return_value={'accepted':True}))
        args={'task_id':'b'*32,'validated_assembly_task_id':'a'*32}
        with patch.object(server,'_task_engine',engine):result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',args))
        self.assertFalse(result.is_error);self.assertEqual(engine.plan.call_args.kwargs['validated_assembly_task_id'],'a'*32)
        for value in (True,1,'bad'):
            engine.plan.reset_mock()
            with patch.object(server,'_task_engine',engine):result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{**args,'validated_assembly_task_id':value}))
            self.assertTrue(result.is_error);engine.plan.assert_not_called()

    def test_native_success_cannot_mask_whole_mechanism_failure_or_export_as_pass(self):
        from tests.test_motion_task_feedback import MotionFailureTests
        helper=MotionFailureTests();self.addCleanup(helper.doCleanups)
        answer={'run_id':'c'*32,'assertion':'pass','signed_net_travel':2,'restoration_status':'restored','source_files_unchanged':True}
        root,engine,tid,planned,wait=helper.fixture(answer);session=engine.sessions[tid]
        path=session.runtime/'runs'/('c'*32)/'component-poses.csv';path.parent.mkdir(parents=True)
        path.write_text('frame,time_s,component_id,x_m,y_m,z_m,r00,r01,r02,r10,r11,r12,r20,r21,r22\n0,0,moving,0,0,0,1,0,0,0,1,0,0,0,1\n',encoding='utf8')
        engine.tasks[tid]['proposal']['working_stroke_validation']={'fixture':'offline_only'}
        with patch.object(w,'load',return_value={}),patch.object(w,'verify',side_effect=core.StopBatch('CONNECTION_EVIDENCE_FAILED','mid-frame joint violation')) as verify,patch('sw_mcp.artifacts.Artifacts.export_history_curve') as export,patch.object(session,'call',wraps=session.call) as calls:
            engine.execute(tid,planned['plan_token'],True,True);state=wait(tid)
        self.assertEqual(state['phase'],'failed');self.assertFalse(state['verification']['declared_scope_passed'])
        self.assertEqual(state['verification']['scope'],'sampled_declared_mechanism_working_stroke')
        self.assertEqual(state['verification']['curve_status'],'not_exported_working_stroke_verification_failed')
        self.assertEqual(state['error']['code'],'CONNECTION_EVIDENCE_FAILED');verify.assert_called_once();export.assert_not_called()
        self.assertEqual(sum(c.args[0]=='verify_motion_preservation' for c in calls.call_args_list),1)
        with self.assertRaises(core.StopBatch):engine.execute(tid,planned['plan_token'],True,True)
        engine.finish(tid);self.assertTrue(wait(tid)['closed'])

    def test_plan_binds_prior_scope_before_confirmation_and_rejects_wrong_task_kind(self):
        from tests.test_motion_task_feedback import MotionFailureTests
        helper=MotionFailureTests();self.addCleanup(helper.doCleanups)
        root,engine,tid,planned,wait=helper.fixture({});engine.tasks[tid]['phase']='proposal_ready'
        with patch.object(w,'bind',return_value={'components':4,'joint_targets':4,'scope':'sampled_declared_mechanism_working_stroke'}) as bind:
            engine.plan(tid,validated_assembly_task_id='a'*32);state=wait(tid)
        bind.assert_called_once();self.assertEqual(state['phase'],'awaiting_confirmation')
        self.assertEqual(state['proposal']['working_stroke_validation']['joint_targets'],4)
        engine.tasks[tid]['task_kind']='assembly_constraints'
        with self.assertRaises(core.StopBatch):engine.plan(tid,validated_assembly_task_id='a'*32)


if __name__=='__main__':unittest.main()
