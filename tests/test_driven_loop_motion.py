import copy,unittest,asyncio,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import mechanism_loop,connection_trials as trials,assembly_connections as joints
from sw_mcp.conversation import driven_loop_motion
from tests.test_mechanism_loop import fixture


class DrivenLoopMotionTests(unittest.TestCase):
    def test_known_motion_failure_prepares_model_context_before_snapshot_close(self):
        self.cleanup_case('known')
    def test_unknown_motion_does_not_prepare_or_restore(self):
        self.cleanup_case('unknown')
    def test_unverified_model_switch_stops_without_closing_documents(self):
        self.cleanup_case('unverified_context')
    def cleanup_case(self,mode):
        from sw_mcp.conversation import core
        poses,bounds,review,grid=self.value();goals=copy.deepcopy(bounds)
        goals[review['primary_goal_index']]['driven_loop_driver']={'drive':{'entity_id':'face'},'positive_trial_reverse':False,'speed_mm_s':.1,'translation_step_m':.0001}
        folder=Path(__file__).resolve().parents[1]/'runs'/('loop-cleanup-'+uuid.uuid4().hex);folder.mkdir()
        s=SimpleNamespace(model='owned',result_checkpoint='saved',unknown=False,folder=folder,state=lambda *a,**kw:None);calls=[]
        def call(name,**kw):
            calls.append(name)
            if name=='_connection_reference_state':return {'mate_parameters_signature':'same','native_mate_count':3,'study_states':[],'fixed_states':{}}
            if name=='inspect_model':return {'components':[{'component_id':k,'transform':v} for k,v in poses.items()]}
            if name=='create_motion_study':return {}
            if name=='verify_motion_preservation':
                if mode=='unknown':s.unknown=True;raise core.StopBatch('CONNECTION_NATIVE_UNKNOWN')
                return {'assertion':'inconclusive','restoration_status':'restored','source_files_unchanged':True,'run_id':kw['run_id']}
            if name=='_prepare_owned_snapshot_restore':return {'model_context_verified':mode!='unverified_context','source_files_unchanged':True}
            if name=='restore_model_checkpoint':return {'restoration_status':'restored','source_files_unchanged':True,'maximum_transform_delta':0}
            raise AssertionError(name)
        s.call=call
        with self.assertRaises(core.StopBatch):driven_loop_motion.run(s,goals,poses,bounds,review)
        self.assertEqual(calls.count('verify_motion_preservation'),1)
        self.assertEqual(calls.count('restore_model_checkpoint'),1 if mode=='known' else 0)
        self.assertEqual(calls.count('_prepare_owned_snapshot_restore'),0 if mode=='unknown' else 1)
        if mode=='known':self.assertLess(calls.index('_prepare_owned_snapshot_restore'),calls.index('restore_model_checkpoint'))

    def test_ordinary_motion_restore_prepares_context_and_unknown_never_restores(self):
        from sw_mcp.conversation.motion_tasks import MotionSession
        from sw_mcp.conversation.task_engine import ConversationSession
        from sw_mcp.conversation import core
        s=MotionSession.__new__(MotionSession);s.task_kind='motion';s.model='owned';s.folder=Path('unused');s.unknown=False;s.temporary_motion_created=True
        events=[];s.call=lambda *a,**kw:events.append('prepare') or {'model_context_verified':True,'source_files_unchanged':True}
        with patch.object(ConversationSession,'restore',side_effect=lambda:events.append('restore') or {'restoration_status':'restored'}),patch.object(core,'write'):
            self.assertEqual(s.restore()['restoration_status'],'restored');self.assertEqual(events,['prepare','restore'])
            events.clear();s.unknown=True
            with self.assertRaises(core.StopBatch):s.restore()
            self.assertEqual(events,[])

    def test_micro_alignment_requires_separate_confirmation_before_plan_consumption(self):
        from sw_mcp.conversation import connection_task,core
        task={'task_id':'a'*32,'phase':'awaiting_confirmation','plan_token':'b'*32,
              'proposal':{'initial_translation':{'requires_alignment_confirmation':True}}}
        engine=SimpleNamespace(_require_session=Mock(),save=Mock(),_submit=Mock(return_value='submitted'))
        before=copy.deepcopy(task)
        with self.assertRaises(core.StopBatch) as caught:connection_task.execute(engine,task,'b'*32,True,True,False)
        self.assertEqual(caught.exception.code,'CONFIRMATION_REQUIRED');self.assertEqual(task,before);engine._submit.assert_not_called()
        self.assertEqual(connection_task.execute(engine,task,'b'*32,True,True,True),'submitted')
        self.assertTrue(task['execution_consumed'] and task['confirmation']['alignment_confirmed'])

    def test_public_loop_route_preserves_natural_names_and_strict_budget_schema(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock(return_value={'accepted':True}))
        args={'task_id':'a'*32,'verification_mode':'driven_loop','moving_component_hint':'中央杆-1','reference_component_hint':'机架-1',
            'output_component_hints':['左爪-1','右爪-1'],'completion_scope':'whole_assembly','alignment_mode':'small_translation','initial_translation_limit_mm':.001}
        with patch.object(server,'_task_engine',engine):result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',args))
        self.assertFalse(result.is_error,result);self.assertEqual(engine.plan.call_args.kwargs['verification_mode'],'driven_loop')
        self.assertEqual(engine.plan.call_args.kwargs['output_component_hints'],['左爪-1','右爪-1'])
        for change in ({'initial_translation_limit_mm':True},{'initial_translation_limit_mm':.011},{'output_component_hints':['左爪-1',False]},{'verification_mode':'skip_verification'}):
            engine.plan.reset_mock()
            with patch.object(server,'_task_engine',engine):result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{**args,**change}))
            self.assertTrue(result.is_error,result);engine.plan.assert_not_called()

    def value(self):
        s,goals,primary=fixture();poses={c['component_id']:c['transform'] for c in s['components']}
        review=mechanism_loop.review(s,goals,mechanism_loop.ideal_graph(s,goals).matrix,primary,['output'])
        bounds=[trials.bind(goal,poses) for goal in goals];grid=[]
        for i in range(31):grid.append({cid:trials.target(p,[0,0,1],.0001*i/30) if cid!='frame' else list(p) for cid,p in poses.items()})
        return poses,bounds,review,grid
    def test_complete_primary_driven_loop_audits_all_joints_and_outputs(self):
        p,b,r,grid=self.value();v=driven_loop_motion.audit(grid,p,b,r,.0001)
        self.assertTrue(v['passed']);self.assertEqual(v['pose_rows'],124);self.assertEqual(v['all_declared_joint_count'],4)
        self.assertFalse(v['independent_joint_actuation_certified'] or v['whole_travel_certified'])
    def test_no_output_movement_cannot_be_certified_by_successful_input_alone(self):
        p,b,r,grid=self.value()
        for frame in grid:frame['output']=list(p['output'])
        v=driven_loop_motion.audit(grid,p,b,r,.0001);self.assertFalse(v['passed']);self.assertFalse(v['output_checks'][0]['passed'])
    def test_mid_run_joint_violation_and_grounded_drift_fail(self):
        for cid in ('brace','frame'):
            p,b,r,grid=self.value();grid[15][cid][9]+=.00001;self.assertFalse(driven_loop_motion.audit(grid,p,b,r,.0001)['passed'])
    def test_partial_grid_missing_component_wrong_direction_and_zero_stroke_fail(self):
        p,b,r,grid=self.value()
        with self.assertRaisesRegex(ValueError,'31_frame'):driven_loop_motion.audit(grid[:30],p,b,r,.0001)
        self.assertFalse(driven_loop_motion.audit(grid,p,b,r,-.0001)['passed'])
        self.assertFalse(driven_loop_motion.audit([copy.deepcopy(p) for _ in range(31)],p,b,r,.0001)['passed'])
        grid[10].pop('output')
        with self.assertRaisesRegex(ValueError,'scope_mismatch'):driven_loop_motion.audit(grid,p,b,r,.0001)

    def test_opt_in_planner_keeps_default_closed_loop_refusal(self):
        from tests.test_assembly_connections import survey
        s=survey();drive=copy.deepcopy(s['components'][1]);drive['component_id']='output';drive['instance']='output';s['components'].append(drive)
        goals=[{'component_a':'moving','component_b':'body','kind':'prismatic','axis_hint':[0,0,1]},
               {'component_a':'output','component_b':'moving','kind':'rigid'}]
        p=joints.plan(s,goals,whole_assembly=True,driven_loop={'primary':{'component_a':'moving','component_b':'body','kind':'prismatic'},'outputs':['output']})
        self.assertEqual(p['status'],'plan_ready');self.assertFalse(p['driven_loop_review']['finite_motion_verified'])
        bad=copy.deepcopy(goals);bad[0]['kind']='rigid'
        with self.assertRaisesRegex(ValueError,'primary_goal_not_unique'):
            joints.plan(s,bad,whole_assembly=True,driven_loop={'primary':{'component_a':'moving','component_b':'body','kind':'prismatic'},'outputs':['output']})

if __name__=='__main__':unittest.main()
