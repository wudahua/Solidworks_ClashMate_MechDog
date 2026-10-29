import copy,unittest,asyncio
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import connection_groups as groups,assembly_connections as joints
from tests.test_assembly_connections import survey
from tests.test_assembly_constraints import component,mate


class GroupTests(unittest.TestCase):
    def raw(self,**kw):return {'name':'declared','members':['body','moving'],**kw}
    def test_group_expands_without_mutating_the_native_snapshot(self):
        s=survey();before=copy.deepcopy(s);e=groups.expand(s,[],[self.raw()])
        self.assertEqual(e['status'],'group_expanded');self.assertEqual(e['goals'],[{'component_a':'moving','component_b':'body','kind':'rigid'}])
        self.assertEqual(e['fixed_state_changes'],[]);self.assertEqual(s,before)

    def test_existing_indirect_group_is_not_given_redundant_goals(self):
        s=survey([mate(1,'body','moving','lock')]);e=groups.expand(s,[],[self.raw()])
        self.assertEqual(e['status'],'supported_groups_need_no_write');self.assertEqual(e['goals'],[])
        self.assertEqual(len(e['group_bindings']),1);self.assertFalse(e['write_dispatched'])

    def test_fixed_rotor_first_returns_a_nonexecuting_named_review(self):
        s=survey();s['components'][1]['fixed_component']=True
        e=groups.expand(s,[{'component_a':'moving','component_b':'body','kind':'revolute'}])
        self.assertEqual(e['status'],'fixed_release_review_required');self.assertEqual(e['suggested_release_fixed_components'],['moving'])
        self.assertFalse(e['write_dispatched']);self.assertFalse(e['executable'])

    def test_explicit_release_only_changes_the_virtual_plan_until_execute(self):
        s=survey();s['components'][1].update(fixed_component=True,constraint_state={'status':'observed','fully_constrained':True})
        old=copy.deepcopy(s);e=groups.expand(s,[{'component_a':'moving','component_b':'body','kind':'revolute'}],release_names=['moving'])
        self.assertTrue(s['components'][1]['fixed_component']);self.assertEqual(s,old)
        self.assertFalse(e['planning_survey']['components'][1]['fixed_component'])
        self.assertIsNone(e['planning_survey']['components'][1]['constraint_state']['fully_constrained'])
        p=joints.plan(e['planning_survey'],e['goals']);self.assertEqual(p['status'],'plan_ready')
        self.assertEqual(e['fixed_state_changes'][0]['instance'],'moving')

    def test_all_fixed_moving_group_members_are_reported_together(self):
        s=survey();s['components'][1]['fixed_component']=True;s['components'].append(component('key',True))
        e=groups.expand(s,[{'component_a':'moving','component_b':'body','kind':'revolute'}],[self.raw(members=['moving','key'])])
        self.assertEqual(set(e['suggested_release_fixed_components']),{'moving','key'})

    def test_moving_endpoint_is_an_automatic_coordinate_anchor_not_inferred_intent(self):
        s=survey();c=copy.deepcopy(s['components'][1]);c.update(component_id='key',instance='key');s['components'].append(c)
        e=groups.expand(s,[{'component_a':'moving','component_b':'body','kind':'revolute'}],[self.raw(members=['key','moving'])])
        self.assertEqual(e['rigid_groups'][0]['anchor'],'moving')
        self.assertIn({'component_a':'key','component_b':'moving','kind':'rigid'},e['goals'])

    def test_no_stationary_ownership_is_assigned_to_omitted_components(self):
        s=survey();s['components'].append(component('unknown_accessory'))
        e=groups.expand(s,[],[self.raw()]);self.assertEqual(e['unassigned_components'],['unknown_accessory'])
        self.assertFalse(e['mechanical_ownership_of_unassigned_components_inferred'])

    def test_overlap_is_not_silently_merged(self):
        with self.assertRaisesRegex(groups.GroupIntentError,'overlapping'):
            groups.expand(survey(),[],[self.raw(),self.raw(name='other')])

    def test_mobile_joint_inside_one_rigid_group_is_a_conflict(self):
        with self.assertRaisesRegex(groups.GroupIntentError,'mobile_joint_inside'):
            groups.expand(survey(),[{'component_a':'moving','component_b':'body','kind':'revolute'}],[self.raw()])

    def test_unknown_names_and_aliases_are_not_substituted(self):
        for members in (['body','not-present'],['body','mov']):
            with self.assertRaisesRegex(groups.GroupIntentError,'name_not_unique'):groups.expand(survey(),[],[self.raw(members=members)])

    def test_releasing_the_last_fixed_reference_is_refused(self):
        with self.assertRaisesRegex(groups.GroupIntentError,'fixed_reference_to_remain'):
            groups.expand(survey(),[],[self.raw()],['body'])

    def test_unrelated_or_floating_release_is_refused(self):
        s=survey();s['components'].append(component('unrelated',True))
        with self.assertRaisesRegex(groups.GroupIntentError,'not_bound_to'):
            groups.expand(s,[],[self.raw()],['unrelated'])
        with self.assertRaisesRegex(groups.GroupIntentError,'not_observed_fixed'):
            groups.expand(s,[],[self.raw()],['moving'])

    def test_pattern_is_not_individually_released_or_supplemented(self):
        s=survey();s['structural_relations']={'components':[{'component_id':'moving','is_pattern_instance':True}]}
        with self.assertRaisesRegex(groups.GroupIntentError,'pattern_group'):groups.expand(s,[],[self.raw()])
        s['components'][1]['fixed_component']=True
        with self.assertRaisesRegex(groups.GroupIntentError,'pattern_member_fixed_release'):groups.expand(s,[],[self.raw()],['moving'])

    def test_budget_refuses_the_whole_expansion_instead_of_partial_commit(self):
        s=survey()
        for i in range(8):
            c=copy.deepcopy(s['components'][1]);c.update(component_id=str(i),instance=str(i));s['components'].append(c)
        e=groups.expand(s,[],[self.raw(members=[c['instance'] for c in s['components']])])
        self.assertEqual(e['status'],'group_goal_budget_review_required');self.assertEqual(e['expanded_goal_count'],9)
        self.assertFalse(e['write_dispatched']);self.assertFalse(e['executable'])

    def test_groups_cannot_combine_rotation_and_slide_into_a_false_green_plan(self):
        s=survey();peer=copy.deepcopy(s['components'][1]);peer.update(component_id='peer',instance='peer');s['components'].append(peer)
        intents=[{'component_a':'moving','component_b':'body','kind':'revolute'},
                 {'component_a':'peer','component_b':'body','kind':'prismatic'},
                 {'component_a':'peer','component_b':'moving','kind':'rigid'}]
        with self.assertRaisesRegex(ValueError,'proposed_group_constraints_conflict'):
            joints.plan(s,intents)


class GroupProtocolTests(unittest.TestCase):
    def test_group_options_on_other_task_kinds_are_refused_not_ignored(self):
        from sw_mcp.conversation.motion_tasks import MotionTaskEngine
        from sw_mcp.conversation.core import StopBatch
        engine=MotionTaskEngine.__new__(MotionTaskEngine);engine.tasks={'a'*32:{'task_kind':'motion'}}
        with self.assertRaises(StopBatch) as caught:engine.plan('a'*32,rigid_groups=[{'name':'x','members':['a','b']}])
        self.assertEqual(caught.exception.code,'CONNECTION_INTENT_INVALID')

    def test_public_group_route_preserves_names_and_does_not_add_a_tool(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock(return_value={'accepted':True}))
        with patch.object(server,'_task_engine',engine):
            result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'rigid_groups':[{'name':'转子','members':['轴-1','键-1']}],'release_fixed_components':['键-1']}))
        self.assertFalse(result.is_error,result);self.assertEqual(engine.plan.call_args.args[-2][0]['members'],['轴-1','键-1'])
        self.assertEqual(engine.plan.call_args.args[-1],['键-1']);self.assertEqual(len(asyncio.run(server.mcp.list_tools())),30)

    def test_closed_nested_group_schema_rejects_unknown_fields_before_engine(self):
        import motion_server as server
        for raw in ({'name':'x','members':['a','b'],'fix_all':True},{'name':False,'members':['a','b']},{'name':'x','members':['a',True]}):
            engine=SimpleNamespace(plan=Mock())
            with patch.object(server,'_task_engine',engine):r=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'rigid_groups':[raw]}))
            self.assertTrue(r.is_error);engine.plan.assert_not_called()


if __name__=='__main__':unittest.main()
