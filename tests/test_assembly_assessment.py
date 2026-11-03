import copy,unittest,asyncio
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import assembly_assessment as a,assembly_overview as o,assembly_connections as j,connection_recommendations as d
from sw_mcp.conversation import connection_task,core
from tests.test_assembly_constraints import component,mate

def scene():
    return {'components':[component('base',True),component('shaft')],'mates':[mate(1,'shaft','base','cylindrical_axis'),mate(2,'shaft','base','planar_normal')],'inventory_complete':True}

class AssessmentTests(unittest.TestCase):
    def build(self,s):
        r=j.review(s);return a.build(s,r,o.recommend(s,r),d.draft(s,r,binding='unit'),binding='unit')
    def test_complete_existing_joint_proposes_zero_supplement_not_motion_success(self):
        r=self.build(scene());self.assertTrue(r['accounting_complete']);self.assertTrue(r['automatic_plan_available']);self.assertEqual(r['expected_added_mates'],0)
        self.assertFalse(r['mechanical_intent_inferred']);self.assertFalse(r['native_motion_verified']);self.assertFalse(r['confirmation_token_created'])
    def test_all_component_names_accounted_once(self):
        r=self.build(scene());self.assertEqual({v['instance'] for v in r['components']},{'base','shaft'});self.assertEqual(sum(r['category_counts'].values()),2)
    def test_unrelated_fixed_parts_do_not_become_rigid_group(self):
        s=scene();s['components']=[component('a',True),component('b',True)];s['mates']=[];r=self.build(s)
        self.assertFalse(r['automatic_plan_available']);self.assertEqual(r['proposed_connection_intent'],[]);self.assertEqual(r['category_counts'],{'mechanical_clarification_required':2})
    def test_unassigned_body_blocks_automatic_whole_assembly(self):
        s=scene();s['components'].append(component('loose'));r=self.build(s)
        self.assertFalse(r['automatic_plan_available']);self.assertFalse(r['all_components_have_proposed_targets']);self.assertTrue(any('loose' in q['instances'] for q in r['mechanical_question_groups']))
    def test_supported_rigid_planes_are_preserved_without_fixed_flag_inference(self):
        s=scene();s['mates']=[mate(i+1,'shaft','base','planar_normal',axis=v) for i,v in enumerate(([1,0,0],[0,1,0],[0,0,1]))];r=self.build(s)
        self.assertTrue(r['automatic_plan_available']);self.assertEqual(r['proposed_connection_intent'][0]['kind'],'rigid');self.assertEqual(r['expected_added_mates'],0)
    def test_existing_native_lock_remains_explicit_unsupported(self):
        s=scene();s['mates']=[mate(1,'shaft','base','lock')];r=self.build(s)
        self.assertFalse(r['automatic_plan_available']);self.assertIn('unsupported_native_lock_trial',[x['reason'] for x in r['proposal_review_issues']])
    def test_native_health_failure_cannot_auto_preview(self):
        s=scene();s['mates'][0]['error']=1;r=self.build(s);self.assertFalse(r['automatic_plan_available']);self.assertTrue(r['proposal_review_issues'])
    def test_duplicate_component_identity_is_not_complete(self):
        s=scene();s['components'].append(copy.deepcopy(s['components'][0]));r=self.build(s);self.assertFalse(r['accounting_complete']);self.assertFalse(r['automatic_plan_available'])
    def test_unknown_native_full_mobile_goal_remains_blocked(self):
        s=scene();s['components'][1]['constraint_state']={'status':'observed','fully_constrained':True,'native_value':3};r=self.build(s)
        self.assertFalse(r['automatic_plan_available']);self.assertIn('native_fully_constrained_mobile_goal_requires_review',[x['reason'] for x in r['proposal_review_issues']])
    def test_readonly_captures_every_component_and_blocks_preview(self):
        r=a.readonly(scene(),{'write_scope_allowed':False});self.assertTrue(r['accounting_complete']);self.assertEqual(r['category_counts'],{'unsupported_for_writes':2});self.assertFalse(r['automatic_plan_available'])
    def test_explicit_plan_does_not_claim_unassigned_part_complete(self):
        s=scene();s['components'].append(component('unknown'));p=j.plan(s,[{'component_a':'shaft','component_b':'base','kind':'revolute'}]);r=a.for_plan(s,p)
        self.assertFalse(r['all_components_have_proposed_targets']);self.assertEqual(next(x['status'] for x in r['components'] if x['instance']=='unknown'),'mechanical_clarification_required')
    def test_missing_coordinates_report_requires_a_proposed_goal(self):
        s=scene();r=a.for_plan(s,{'goals':[{'component_a':'shaft','component_b':'base','kind':'rigid','added_action_count':1}],'actions':[{'kind':'distance'}]})
        self.assertEqual(r['category_counts'],{'supplement_proposed':2});self.assertEqual(r['expected_added_mates'],1);self.assertFalse(r['native_preview_completed'])
    def test_draft_page_budget_not_reported_as_full_search(self):
        s=scene();r=j.review(s);draft={'candidates':[],'next_cursor':'first'}
        with patch.object(a.drafts,'draft',side_effect=[{'candidates':[],'next_cursor':str(i)} for i in range(8)]):
            v=a.build(s,r,o.recommend(s,r),draft,binding='unit')
        self.assertEqual(v['candidate_search']['pages_read'],8);self.assertFalse(v['candidate_search']['all_pair_ranges_read']);self.assertIsNotNone(v['candidate_search']['remaining_cursor'])
    def test_cursor_cycle_refuses_instead_of_claiming_complete(self):
        s=scene();r=j.review(s);draft={'candidates':[],'next_cursor':'same'}
        with patch.object(a.drafts,'draft',return_value=draft),self.assertRaisesRegex(ValueError,'cycle'):a.build(s,r,o.recommend(s,r),draft)
    def test_assessment_does_not_mutate_native_snapshot(self):
        s=scene();before=copy.deepcopy(s);self.build(s);self.assertEqual(s,before)
    def test_auto_requires_new_review_no_overwriting_confirmation(self):
        t={'task_id':'a'*32,'phase':'awaiting_confirmation'};e=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:SimpleNamespace()})
        with self.assertRaises(core.StopBatch):connection_task.propose(e,t,None,auto_plan=True)
    def test_auto_never_silently_ignores_manual_goal(self):
        t={'task_id':'a'*32,'phase':'constraint_review_ready'};e=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:SimpleNamespace()})
        with self.assertRaises(core.StopBatch):connection_task.propose(e,t,[{}],auto_plan=True)
    def test_unavailable_auto_returns_grouped_question_without_cad(self):
        t={'task_id':'a'*32,'phase':'constraint_review_ready','assembly_assessment':{'automatic_plan_available':False,'mechanical_question_groups':[{'instances':['loose']}]}};s=SimpleNamespace(call=Mock());e=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:s})
        r=connection_task.propose(e,t,None,auto_plan=True);self.assertTrue(r['needs_mechanical_clarification']);s.call.assert_not_called();self.assertFalse(r['confirmation_token_created'])
    def test_readonly_auto_cannot_bypass_existing_write_gate(self):
        t={'task_id':'a'*32,'phase':'constraint_review_ready','connection_review':{'write_scope_allowed':False}};e=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:SimpleNamespace()})
        with self.assertRaises(core.StopBatch) as caught:connection_task.propose(e,t,None,auto_plan=True)
        self.assertEqual(caught.exception.code,'CONNECTION_SCOPE_UNSUPPORTED')
    def test_empty_or_incomplete_readonly_inventory_is_not_complete(self):
        self.assertFalse(a.readonly({}, {})['accounting_complete']);self.assertFalse(a.readonly(scene(),{'component_count':3})['accounting_complete'])
    def test_boolean_auto_plan_survives_real_mcp_schema_and_forwarding(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock(return_value={'accepted':True}))
        with patch.object(server,'_task_engine',engine):result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'auto_plan':True}))
        self.assertFalse(result.is_error);self.assertTrue(engine.plan.call_args.kwargs['auto_plan'])
    def test_text_or_number_auto_plan_never_dispatches(self):
        import motion_server as server
        for value in ('true',1,False.__str__()):
            engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock())
            with patch.object(server,'_task_engine',engine):result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'auto_plan':value}))
            self.assertTrue(result.is_error);engine.plan.assert_not_called()
    def test_component_coverage_cannot_hide_an_unresolved_connection(self):
        s={'components':[component('base',True),component('a'),component('b')],'inventory_complete':True,'mates':[
            mate(1,'a','base','planar_normal',axis=[1,0,0]),mate(2,'a','base','planar_normal',axis=[0,1,0]),
            mate(3,'b','base','planar_normal',axis=[0,1,0]),mate(4,'b','base','planar_normal',axis=[0,0,1]),mate(5,'a','b','planar_normal',axis=[0,1,0])]}
        r=self.build(s);self.assertFalse(r['automatic_plan_available']);self.assertTrue(r['unresolved_connection_candidates'])
        self.assertTrue(any({p['instance_a'],p['instance_b']}=={'a','b'} for p in r['unresolved_connection_candidates']))
        self.assertFalse(any(p['missing_connection_proven'] for p in r['unresolved_connection_candidates']))
