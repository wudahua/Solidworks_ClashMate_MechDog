import copy
import math
import unittest
import asyncio
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock,patch
from sw_mcp import assembly_connections as joint
from tests.test_assembly_constraints import component, mate
from sw_mcp import connection_trials as trial


def survey(mates=()):
    cs=[component('body', True), component('moving')]
    for c in cs:
        c['cylinders']=[dict(native_reference=c['component_id']+'c',reference_kind='cylindrical_face',
            axis_global=[0,0,1],reference_point_global_m=[0,0,0])]
        c['completion_planes']=[dict(native_reference=c['component_id']+str(i),reference_kind='datum_plane',
            axis_global=n,reference_point_global_m=[0,0,0]) for i,n in enumerate(([1,0,0],[0,1,0],[0,0,1]))]
    return dict(components=cs,mates=list(mates),inventory_complete=True)


class ConnectionTests(unittest.TestCase):
    def test_targets_preserve_distinct_freedoms_at_offset_axis(self):
        for kind, rank in [('rigid',6),('revolute',5),('prismatic',5)]:
            rows=joint.target_rows(kind,[0,0,1],[.2,.3,0],[0,0,0],.01)
            self.assertEqual(len(joint.ac.basis(rows)),rank)
            hint=joint.mobility(rows,[0,0,0],.01)
            self.assertEqual(hint['recommended_joint_type'],kind)
            if kind=='revolute':
                self.assertLess(math.dist(hint['axis_point_global_m'],[.2,.3,0]),1e-9)

    def test_all_three_goals_plan_with_no_legacy_mates(self):
        for kind in joint.KINDS:
            r=joint.plan(survey(),[dict(component_a='moving',component_b='body',kind=kind)])
            self.assertEqual(r['status'],'plan_ready',r)
            self.assertNotIn('rigid_lock',[a['kind'] for a in r['actions']])
            self.assertFalse(r['motion_verified'])
            self.assertEqual(r['fixed_state_changes'],[])

    def test_revolute_adds_axial_location_without_locking_rotation(self):
        s=survey([mate(1,'body','moving','cylindrical_axis')])
        r=joint.plan(s,[dict(component_a='moving',component_b='body',kind='revolute')])
        self.assertEqual(r['status'],'plan_ready')
        self.assertEqual(len(r['actions']),1)
        self.assertEqual(r['actions'][0]['kind'],'distance')

    def test_existing_lock_cannot_be_called_healthy_revolute(self):
        with self.assertRaisesRegex(ValueError,'conflict'):
            joint.plan(survey([mate(1,'body','moving','lock')]),[dict(component_a='moving',component_b='body',kind='revolute')])

    def test_native_full_state_stops_mobile_goal_despite_local_slide_hint(self):
        s=survey([mate(1,'body','moving','planar_normal',axis=[0,1,0]),mate(2,'body','moving','planar_normal',axis=[1,0,0])])
        s['components'][1]['constraint_state']={'status':'observed','fully_constrained':True,'native_name':'swFullyConstrained'}
        self.assertEqual(joint.review(s)['connections'][0]['recommended_joint_type'],'prismatic')
        with self.assertRaisesRegex(ValueError,'native_fully_constrained_mobile_goal'):
            joint.plan(s,[dict(component_a='moving',component_b='body',kind='prismatic')])

    def test_no_missing_supplement_for_complete_revolute(self):
        s=survey([mate(1,'body','moving','cylindrical_axis'),mate(2,'body','moving','planar_normal')])
        r=joint.plan(s,[dict(component_a='moving',component_b='body',kind='revolute')])
        self.assertEqual(r['status'],'plan_ready')
        self.assertEqual(r['actions'],[])

    def test_direction_does_not_manufacture_rotation_axis(self):
        s=survey()
        for c in s['components']:c['cylinders']=[]
        r=joint.plan(s,[dict(component_a='moving',component_b='body',kind='revolute',axis_hint=[0,0,1])])
        self.assertEqual(r['status'],'axis_selection_required')
        self.assertFalse(r['write_dispatched'])

    def test_bad_candidate_never_rebinds(self):
        with self.assertRaisesRegex(ValueError,'invalid_axis_candidate'):
            joint.plan(survey(),[dict(component_a='moving',component_b='body',kind='revolute',candidate_id='axis-99')])

    def test_unknown_native_constraints_remain_visible(self):
        s=survey([mate(17,'body','moving','lock',t=99)])
        r=joint.review(s)
        self.assertEqual(r['omitted_native_feature_ids'],[17])
        self.assertIsNone(r['all_mates_sufficient'])
        self.assertIsNone(r['global_DOF'])

    def test_limit_distance_is_not_misread_as_axial_equality(self):
        m=mate(3,'body','moving','planar_normal',t=5);m['native_feature_type']='MateLimitDistanceDim'
        r=joint.review(survey([mate(1,'body','moving','cylindrical_axis'),m]))
        self.assertEqual(r['connections'][0]['supported_local_rank'],4)
        self.assertIn(3,r['omitted_native_feature_ids'])

    def test_geometry_absence_does_not_lead_to_partial_write_plan(self):
        s=survey([mate(1,'body','moving','cylindrical_axis')])
        for c in s['components']:c['completion_planes']=[]
        r=joint.plan(s,[dict(component_a='moving',component_b='body',kind='rigid')])
        self.assertEqual(r['status'],'unsupported_references')
        self.assertFalse(r['write_dispatched'])

    def test_native_lock_is_read_only_not_replaced_with_new_constraints(self):
        s=survey([mate(1,'body','moving','lock')])
        old=copy.deepcopy(s)
        p=joint.plan(s,[dict(component_a='moving',component_b='body',kind='rigid')])
        self.assertEqual(p['status'],'unsupported_native_lock_trial')
        self.assertEqual(p['actions'],[]);self.assertEqual(s,old)

    def test_names_and_order_do_not_change_needed_rank(self):
        s=survey(); goal=[dict(component_a='moving',component_b='body',kind='prismatic')]
        a=joint.plan(s,goal)
        s['components'].reverse()
        for c in s['components']:c['instance']='arbitrary_'+c['component_id']
        b=joint.plan(s,goal)
        self.assertEqual(a['actions'],b['actions'])


class TrialAuditTests(unittest.TestCase):
    def goal(self,kind):
        return dict(component_a='moving',component_b='body',kind=kind,axis_global=[0,0,1],reference_point_global_m=[.2,0,0])

    def poses(self):
        return {c['component_id']:c['transform'] for c in survey()['components']}

    def test_rotation_uses_material_axis_not_component_origin(self):
        poses=self.poses();b=trial.bind(self.goal('revolute'),poses)
        for sign in (1,-1):
            p=copy.deepcopy(poses);p['moving']=trial.target(p['moving'],[0,0,1],sign*.001,True,[.2,0,0])
            m=trial.measure(b,p)
            self.assertTrue(m['passed'],m)
            self.assertAlmostEqual(m['signed_twist_rad'],sign*.001)
            self.assertGreater(math.dist(p['moving'][9:12],poses['moving'][9:12]),1e-5)

    def test_prismatic_rejects_tilt_and_transverse_displacement(self):
        poses=self.poses();b=trial.bind(self.goal('prismatic'),poses)
        for axis,angular,expected in [([0,0,1],False,True),([1,0,0],False,False),([0,0,1],True,False)]:
            moved=copy.deepcopy(poses);moved['moving']=trial.target(moved['moving'],axis,.001,angular)
            self.assertEqual(trial.measure(b,moved)['passed'],expected)

    def test_native_true_does_not_override_failed_travel_or_restore(self):
        poses=self.poses();goal=self.goal('prismatic');b=trial.bind(goal,poses);t=trial.trials(goal,poses)[0]
        e=dict(before=poses,after=poses,restored=poses,fixed_states={'body':True,'moving':False},
            original_mates_parameters_unchanged=True,restoration_status='restored',native_set_transform_return=True)
        self.assertFalse(trial.audit(e,[b],0,t)['passed'])
        e['after']=copy.deepcopy(poses);e['after']['moving']=t['target'];e['restored']=e['after']
        self.assertFalse(trial.audit(e,[b],0,t)['passed'])
        e['restored']=poses
        self.assertTrue(trial.audit(e,[b],0,t)['passed'])

    def test_fixed_peer_cannot_drift_to_fake_relative_motion(self):
        poses=self.poses();goal=self.goal('prismatic');b=trial.bind(goal,poses);t=trial.trials(goal,poses)[0]
        moved=copy.deepcopy(poses);moved['moving']=t['target'];moved['body']=trial.target(moved['body'],[1,0,0],.001)
        e=dict(before=poses,after=moved,restored=poses,fixed_states={'body':True,'moving':False},original_mates_parameters_unchanged=True,restoration_status='restored')
        self.assertFalse(trial.audit(e,[b],0,t)['passed'])

    def test_malformed_or_scaled_transforms_are_rejected(self):
        for index in (0,12,15):
            p=self.poses()['moving'];p[index]=2
            with self.assertRaises(ValueError):trial.validate(p)


class ConnectionContractTests(unittest.TestCase):
    def test_new_ambiguous_goal_revokes_previous_confirmation_without_native_call(self):
        from sw_mcp.conversation import connection_task as task,task_execution
        from sw_mcp.conversation.core import StopBatch
        s=SimpleNamespace(connection_survey=survey())
        t=dict(task_id='a'*32,phase='awaiting_confirmation',plan_token='old',proposal={'plan_id':'old-native'})
        engine=SimpleNamespace(sessions={t['task_id']:s},_require_session=Mock(),save=Mock())
        result=task.propose(engine,t,[dict(component_a='不存在',component_b='body',kind='rigid')])
        self.assertTrue(result['needs_mechanical_clarification'])
        self.assertNotIn('plan_token',t);self.assertEqual(t['phase'],'constraint_review_ready')
        with self.assertRaises(StopBatch) as e:task_execution.require_plan_token(t,'old')
        self.assertEqual(e.exception.code,'TASK_NOT_READY_FOR_EXECUTION')

    def test_existing_constraint_conflict_is_mechanical_not_parameter_correction(self):
        from sw_mcp.conversation import connection_task as task
        from sw_mcp.conversation.core import StopBatch
        s=SimpleNamespace(connection_survey=survey([mate(1,'body','moving','lock')]),folder=Path('unused'))
        t=dict(task_id='a'*32,phase='constraint_review_ready')
        engine=SimpleNamespace(sessions={t['task_id']:s},_require_session=Mock())
        with self.assertRaises(StopBatch) as e:task.propose(engine,t,[dict(component_a='moving',component_b='body',kind='revolute')])
        self.assertEqual(e.exception.code,'CONNECTION_GOAL_CONFLICT')

    def test_no_extra_public_tool_and_nested_schema_is_closed(self):
        import motion_server as server
        tools=asyncio.run(server.mcp.list_tools())
        self.assertEqual(len(tools),30)
        p=next(t.input_schema for t in tools if t.name=='plan_mechanism_task')
        self.assertFalse(p['$defs']['ConnectionIntent']['additionalProperties'])
        prepare=next(t.input_schema for t in tools if t.name=='prepare_mechanism_task')
        self.assertIn('assembly_constraints',prepare['properties']['task_kind']['enum'])

    def test_nested_bad_keys_types_and_kind_rejected_before_dispatch(self):
        import motion_server as server
        for field,value in [('unknown',1),('kind','gear'),('axis_hint',[True,0,1]),('component_a',False)]:
            goal=dict(component_a='滑块',component_b='导轨',kind='prismatic');goal[field]=value
            engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock())
            with patch.object(server,'_task_engine',engine):
                result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'connection_intent':[goal]}))
            self.assertTrue(result.is_error,(field,result));engine.plan.assert_not_called()

    def test_optional_goal_defaults_and_valid_names_preserved(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock(return_value={'accepted':True}))
        with patch.object(server,'_task_engine',engine):
            result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32}))
        self.assertFalse(result.is_error,result);self.assertIsNone(engine.plan.call_args.args[-1])
        engine.plan.reset_mock()
        with patch.object(server,'_task_engine',engine):
            result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'connection_intent':[
                dict(component_a='滑块2-1',component_b='导轨-1',kind='prismatic')]}))
        self.assertFalse(result.is_error,result)
        self.assertEqual(engine.plan.call_args.args[-1][0]['component_a'],'滑块2-1')


if __name__=='__main__':unittest.main()
