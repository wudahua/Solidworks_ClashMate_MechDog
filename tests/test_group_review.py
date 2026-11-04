"""Membership proposals, uncertainty boundaries and real MCP read-only admission."""
import asyncio,copy,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import group_review as g,assembly_overview
from sw_mcp.conversation import connection_task,core
from test_assembly_constraints import component,mate
from test_service import temporary_workspace


def model():
    return {'components':[component(n,n=='ground') for n in ('ground','shaft','other','cover','bolt')],
        'mates':[],'inventory_complete':True}


class GroupReviewTests(unittest.TestCase):
    def test_single_group_path_is_reviewable_hypothesis_not_rigidity(self):
        s=model();s['mates']=[mate(1,'ground','cover','cylindrical_axis'),mate(2,'cover','bolt','cylindrical_axis')]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other']});body=next(x for x in r['rigid_groups_draft'] if x['name']=='机体')
        self.assertEqual(set(body['members']),{'ground','cover','bolt'});self.assertTrue(r['all_memberships_proposed'])
        self.assertFalse(r['mechanical_intent_inferred']);self.assertFalse(r['fragment_is_executable']);self.assertFalse(r['confirmation_token_created'])
        self.assertTrue(next(x for x in r['components'] if x['instance']=='cover')['relative_motion_would_be_constrained_if_group_chosen'])
        self.assertFalse(any(x['membership_confirmed'] or x['motion_verified'] for x in r['components']))

    def test_multiple_seed_paths_keep_bridge_pending(self):
        s=model();s['mates']=[mate(1,'ground','cover','planar_normal'),mate(2,'cover','bolt','cylindrical_axis'),mate(3,'bolt','shaft','planar_normal')]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other']})
        self.assertEqual(r['pending_component_count'],2);self.assertEqual(r['question_count'],1)
        self.assertEqual(set(r['mechanical_questions'][0]['instances']),{'cover','bolt'})
        self.assertTrue(r['mechanical_questions'][0]['independent_motion_option_available'])

    def test_unsupported_equation_is_preserved_as_healthy_topology(self):
        s=model();s['mates']=[mate(1,'ground','cover','planar_normal'),mate(2,'cover','shaft','planar_normal',t=99)]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other'],'附件':['bolt']})
        row=next(x for x in r['components'] if x['instance']=='cover');self.assertIsNone(row['proposed_group'])
        self.assertEqual(set(row['candidate_groups']),{'机体','输入'});self.assertEqual(row['unknown_native_feature_ids'],[2])

    def test_invalid_geometry_native_pair_is_not_erased_to_create_unique_group(self):
        s=model();s['mates']=[mate(1,'ground','cover','planar_normal'),mate(2,'cover','shaft','planar_normal',axis=[0,0,0])]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other'],'附件':['bolt']})
        self.assertIsNone(next(x for x in r['components'] if x['instance']=='cover')['proposed_group'])

    def test_unrelated_fixed_flags_and_names_never_assign_group(self):
        s=model();s['components'][3]['fixed_component']=True;s['components'][4]['instance']='螺栓垫片'
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other']})
        self.assertEqual(r['pending_component_count'],2);self.assertEqual(r['proposed_component_count'],3)
        self.assertEqual(r['fixed_state_changes'],[])

    def test_integral_bearing_is_one_negative_ambiguity_group(self):
        s=model();s['components'][3]['instance']='bearing1';s['components'][4]['instance']='轴承2'
        s['mates']=[mate(1,'shaft','cover','cylindrical_axis'),mate(2,'other','bolt','cylindrical_axis')]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other']})
        self.assertEqual(r['pending_component_count'],2);self.assertEqual(r['question_count'],1)
        self.assertEqual(r['mechanical_questions'][0]['reason'],'integral_bearing_motion_intent')

    def test_unknown_bearing_boundary_cannot_give_ring_false_unique_path(self):
        s=model();s['components'][3]['instance']='bearing1';s['mates']=[mate(1,'shaft','bolt','cylindrical_axis'),mate(2,'cover','bolt','cylindrical_axis'),mate(3,'ground','cover','cylindrical_axis')]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other']});row=next(x for x in r['components'] if x['instance']=='bolt')
        self.assertIsNone(row['proposed_group']);self.assertEqual(row['reason'],'unresolved_bearing_or_reference_boundary')

    def test_previously_declared_bearing_purpose_resolves_without_name_assignment(self):
        s=model();s['components'][3]['instance']='bearing1';s['mates']=[mate(1,'shaft','cover','cylindrical_axis'),mate(2,'cover','bolt','cylindrical_axis')]
        r=g.recommend(s,{'机体':['ground','bearing1'],'输入':['shaft'],'输出':['other']})
        self.assertTrue(r['all_memberships_proposed']);self.assertEqual(next(x for x in r['components'] if x['instance']=='bolt')['proposed_group'],'机体')

    def test_health_failure_cannot_produce_clean_draft(self):
        s=model();s['mates']=[{**mate(1,'ground','cover','cylindrical_axis'),'error':1}]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other']});self.assertEqual(r['native_health_issue_feature_ids'],[1]);self.assertNotEqual(r['status'],'group_draft_ready_for_mechanical_review')

    def test_suppressed_relation_is_not_active_membership_path(self):
        s=model();s['mates']=[{**mate(1,'ground','cover','lock'),'suppressed':True}]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other']});self.assertIsNone(next(x for x in r['components'] if x['instance']=='cover')['proposed_group'])

    def test_internal_rigidity_attached_to_seed_wins_over_partial_paths(self):
        s=model();s['mates']=[mate(i+1,'shaft','cover','planar_normal',axis=v) for i,v in enumerate(([1,0,0],[0,1,0],[0,0,1]))]+[mate(4,'cover','ground','cylindrical_axis')]
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other'],'附件':['bolt']})
        row=next(x for x in r['components'] if x['instance']=='cover');self.assertEqual(row['proposed_group'],'输入')
        self.assertEqual(row['evidence']['kind'],'supported_internal_rigidity_observation_connected_to_seed');self.assertFalse(row['evidence']['finite_motion_verified'])

    def test_pattern_ancestry_proposes_membership_but_not_motion(self):
        s=model();s['structural_relations']={'components':[{'native_feature_id':10,'component_id':'bolt','instance':'bolt','is_pattern_instance':True}],
            'patterns':[{'native_feature_id':20,'suppressed':False,'seed_component_ids':['ground'],'child_features':[{'native_feature_id':10}]}]}
        r=g.recommend(s,{'机体':['ground'],'输入':['shaft'],'输出':['other'],'独立':['cover']});row=next(x for x in r['components'] if x['instance']=='bolt')
        self.assertEqual(row['proposed_group'],'机体');self.assertFalse(row['evidence']['pattern_motion_proven'])

    def test_order_changes_do_not_change_membership(self):
        s=model();s['mates']=[mate(1,'ground','cover','cylindrical_axis'),mate(2,'cover','bolt','cylindrical_axis')];seeds={'B':['shaft'],'A':['ground'],'C':['other']}
        a=g.recommend(s,seeds);b=g.recommend({**s,'components':list(reversed(s['components'])),'mates':list(reversed(s['mates']))},dict(reversed(list(seeds.items()))))
        self.assertEqual(a,b)

    def test_nine_independent_pieces_do_not_need_rigid_merging(self):
        s={'components':[component(str(i),i==0) for i in range(9)],'mates':[],'inventory_complete':True}
        r=g.recommend(s,{str(i):[str(i)] for i in range(9)});self.assertTrue(r['all_memberships_proposed']);self.assertEqual(r['plan_input_fragment'],{});self.assertEqual(r['seed_group_count'],9)

    def test_more_than_eight_nontrivial_groups_do_not_emit_partial_plan(self):
        s={'components':[component(str(i)) for i in range(18)],'mates':[],'inventory_complete':True}
        r=g.recommend(s,{str(i):[str(i*2),str(i*2+1)] for i in range(9)});self.assertEqual(r['plan_input_fragment'],{});self.assertTrue(r['plan_fragment_blockers'])

    def test_inputs_cannot_alias_or_overlap_components(self):
        for seeds in ({},{'A':['ground'],'a':['shaft']},{'A':['ground'],'B':['ground']},{'A':[]},{'A':['missing']},{'A':[True]}):
            with self.subTest(seeds=seeds),self.assertRaises(ValueError):g.recommend(model(),seeds)

    def test_incomplete_inventory_refuses_and_source_is_not_mutated(self):
        s=model();before=copy.deepcopy(s);g.recommend(s,{'A':['ground']});self.assertEqual(s,before)
        s['inventory_complete']=False
        with self.assertRaises(ValueError):g.recommend(s,{'A':['ground']})

    def test_default_seed_suggestions_do_not_merge_unrelated_fixed_parts(self):
        s=model();s['components'][1]['fixed_component']=True;o=assembly_overview.recommend(s);r=g.seed_suggestions(s,o)
        self.assertEqual(len(r['candidates']),2);self.assertTrue(all(len(x['seed_instances'])==1 for x in r['candidates']));self.assertFalse(r['automatic_seed_selection'])

    def test_group_query_preserves_pending_token_and_never_calls_native(self):
        with temporary_workspace() as folder:
            t={'task_id':'a'*32,'phase':'awaiting_confirmation','plan_token':'retain-token'};s=SimpleNamespace(connection_survey=model(),folder=Path(folder),call=Mock());e=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:s},save=Mock())
            r=connection_task.propose(e,t,None,group_seeds={'参考':['ground']});self.assertTrue(r['pending_plan_preserved']);self.assertEqual(t['plan_token'],'retain-token');s.call.assert_not_called();self.assertFalse(r['confirmation_token_created'])

    def test_group_query_rejects_mixed_plan_and_readonly_write_scope(self):
        t={'task_id':'a'*32,'phase':'constraint_review_ready'};e=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:SimpleNamespace()})
        with self.assertRaises(core.StopBatch):connection_task.propose(e,t,[],group_seeds={'A':['x']})
        t['connection_review']={'write_scope_allowed':False}
        with self.assertRaises(core.StopBatch):connection_task.propose(e,t,None,group_seeds={'A':['x']})

    def test_real_mcp_schema_forwards_group_seeds_and_rejects_wrong_value_types(self):
        import motion_server as server
        for value,valid in (({'参考':['ground']},True),({'参考':'ground'},False),({'参考':[True]},False)):
            engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock(return_value={'accepted':True}))
            with patch.object(server,'_task_engine',engine):r=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'group_seeds':value}))
            self.assertEqual(not r.is_error,valid)
            if valid:self.assertEqual(engine.plan.call_args.kwargs['group_seeds'],value)
            else:engine.plan.assert_not_called()

    def test_other_task_kind_cannot_silently_discard_group_seeds(self):
        from sw_mcp.conversation.motion_tasks import MotionTaskEngine
        e=SimpleNamespace(tasks={'a'*32:{'task_kind':'motion'}})
        with self.assertRaises(core.StopBatch):MotionTaskEngine.plan(e,'a'*32,group_seeds={'A':['ground']})


if __name__=='__main__':unittest.main()
