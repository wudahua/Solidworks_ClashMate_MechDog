"""Mechanical-purpose clarification must retain the rest of the machine."""
import asyncio,copy,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import assembly_assessment as a,assembly_connections as j,assembly_overview as o,connection_recommendations as d
from sw_mcp.conversation import connection_task,core
from tests.test_assembly_connections import survey
from tests.test_assembly_constraints import mate


def assessment(s):
    review=j.review(s)
    return a.build(s,review,o.recommend(s,review),d.draft(s,review))


class PartialGoalsTests(unittest.TestCase):
    def test_partial_revolute_purpose_fills_one_gap_not_rigid_lock(self):
        s=survey([mate(1,'moving','body','cylindrical_axis')]);before=copy.deepcopy(s);old=assessment(s)
        self.assertFalse(old['automatic_plan_available'])
        result=a.clarify(s,old,[{'component_a':'moving','component_b':'body','kind':'revolute'}])
        self.assertTrue(result['automatic_plan_available']);self.assertEqual(result['expected_added_mates'],1)
        self.assertEqual(result['proposed_connection_intent'][0]['kind'],'revolute')
        self.assertFalse(result['native_motion_verified']);self.assertFalse(result['write_dispatched']);self.assertEqual(s,before)
        self.assertFalse(old['automatic_plan_available'])
    def test_other_observed_joint_is_retained_without_restatement(self):
        s=survey([mate(1,'moving','body','cylindrical_axis')]);other=copy.deepcopy(s['components'][1]);other.update(component_id='other',instance='other')
        for row in other['cylinders']+other['completion_planes']:row['native_reference']='other-'+row['native_reference']
        other['cylinders']=[]  # No coincident material line to the first shaft.
        s['components'].append(other);s['mates'] += [mate(2,'other','body','cylindrical_axis'),mate(3,'other','body','planar_normal')]
        old=assessment(s);result=a.clarify(s,old,[{'component_a':'moving','component_b':'body','kind':'revolute'}])
        self.assertTrue(result['automatic_plan_available']);self.assertGreaterEqual(result['retained_observed_goal_count'],1)
        self.assertTrue(any(g['kind']=='revolute' and {g['component_a'],g['component_b']}=={'other','body'} for g in result['proposed_connection_intent']))
    def test_unclarified_pair_still_blocks_whole_plan(self):
        s=survey([mate(1,'moving','body','cylindrical_axis')]);old=assessment(s)
        old['unresolved_connection_candidates'].append({'instance_a':'moving','instance_b':'body','options':[{'kind':'rigid'}]})
        other=copy.deepcopy(s['components'][1]);other.update(component_id='other',instance='other');s['components'].append(other)
        result=a.clarify(s,old,[{'component_a':'other','component_b':'body','kind':'rigid'}])
        self.assertFalse(result['automatic_plan_available']);self.assertTrue(result['unresolved_connection_candidates'])
        self.assertNotIn('suggested_plan_arguments',result)
    def test_incomplete_search_does_not_dispatch_whole_plan(self):
        s=survey();old=assessment(s);old['candidate_search']['all_pair_ranges_read']=False
        result=a.clarify(s,old,[{'component_a':'moving','component_b':'body','kind':'revolute'}])
        self.assertFalse(result['automatic_plan_available']);self.assertNotIn('suggested_plan_arguments',result)
    def test_duplicate_reverse_pair_is_rejected_not_last_wins(self):
        s=survey();goal={'component_a':'moving','component_b':'body','kind':'revolute'}
        with self.assertRaisesRegex(ValueError,'duplicate_component_pair'):
            a.clarify(s,assessment(s),[goal,{**goal,'component_a':'body','component_b':'moving','kind':'rigid'}])
    def test_unknown_component_cannot_be_merged(self):
        s=survey()
        with self.assertRaisesRegex(ValueError,'outside_inventory'):a.clarify(s,assessment(s),[{'component_a':'outside','component_b':'body','kind':'rigid'}])
    def test_native_health_is_not_waived_by_explicit_purpose(self):
        s=survey([mate(1,'moving','body','cylindrical_axis')]);old=assessment(s);s['mates'][0]['error']=1
        with self.assertRaisesRegex(ValueError,'native_inventory_or_health'):a.clarify(s,old,[{'component_a':'moving','component_b':'body','kind':'revolute'}])
    def test_native_full_mobile_gate_is_still_used(self):
        s=survey([mate(1,'moving','body','cylindrical_axis')]);old=assessment(s);s['components'][1]['constraint_state']={'status':'observed','fully_constrained':True,'native_value':3}
        with self.assertRaisesRegex(ValueError,'native_fully_constrained_mobile_goal_requires_review'):
            a.clarify(s,old,[{'component_a':'moving','component_b':'body','kind':'revolute'}])
    def test_name_ambiguity_stops_before_native_preview(self):
        s=SimpleNamespace(connection_survey=survey(),call=Mock());t={'task_id':'a'*32,'phase':'constraint_review_ready'};engine=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:s})
        value=connection_task.propose(engine,t,[{'component_a':'unknown','component_b':'body','kind':'revolute'}],auto_plan=True)
        self.assertTrue(value['needs_mechanical_clarification']);s.call.assert_not_called()
    def test_pending_confirmation_is_not_overwritten(self):
        s=SimpleNamespace(connection_survey=survey(),call=Mock());t={'task_id':'a'*32,'phase':'awaiting_confirmation','plan_token':'pending'};engine=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:s})
        with self.assertRaises(core.StopBatch):connection_task.propose(engine,t,[{'component_a':'moving','component_b':'body','kind':'rigid'}],auto_plan=True)
        self.assertEqual(t['plan_token'],'pending');s.call.assert_not_called()
    def test_actual_public_schema_forwards_partial_goals(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock(return_value={'accepted':True}))
        with patch.object(server,'_task_engine',engine):value=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'auto_plan':True,'connection_intent':[{'component_a':'moving','component_b':'body','kind':'revolute'}]}))
        self.assertFalse(value.is_error);self.assertTrue(engine.plan.call_args.kwargs['auto_plan'])
        # Public wrapper forwards positional connection intents to the normal
        # task handler; the handler never receives a removed-feature answer key.
        self.assertTrue(any(isinstance(v,list) and v and isinstance(v[0],dict) and v[0].get('kind')=='revolute' for v in engine.plan.call_args.args))
