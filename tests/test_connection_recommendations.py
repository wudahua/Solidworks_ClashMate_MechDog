"""Read-only automatic drafts, ambiguity, bounded search and public integration."""
import copy
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from sw_mcp import connection_recommendations as recommendations
from sw_mcp import assembly_connections as joints
import tests.test_assembly_connections as fixtures
from tests.test_assembly_constraints import component,mate


class DraftTests(unittest.TestCase):
    def test_unmated_coaxial_parts_offer_mechanical_alternatives_without_token_or_writes(self):
        s=fixtures.survey();before=copy.deepcopy(s)
        d=recommendations.draft(s);self.assertEqual(d['status'],'draft_ready')
        c=d['candidates'][0]
        self.assertEqual({o['kind'] for o in c['options']},{'rigid','revolute','prismatic'})
        self.assertIsNone(c['preferred_option_index'])
        self.assertFalse(c['missing_connection_proven'])
        self.assertFalse(d['confirmation_token_created']);self.assertFalse(d['write_dispatched'])
        self.assertFalse(d['mechanical_intent_proven']);self.assertEqual(s,before)

    def test_existing_revolute_is_preserved_without_fabricating_a_missing_mate(self):
        s=fixtures.survey([mate(1,'body','moving','cylindrical_axis'),mate(2,'body','moving','planar_normal')])
        c=recommendations.draft(s)['candidates'][0]
        self.assertEqual(c['status'],'existing_supported_joint')
        self.assertEqual(len(c['options']),1)
        o=c['options'][0];self.assertEqual(o['kind'],'revolute')
        self.assertEqual(o['supported_local_missing_coordinates_if_goal_chosen'],0)

    def guide(self):
        s=fixtures.survey([mate(1,'body','moving','planar_normal',axis=[0,1,0])])
        for c in s['components']:c['cylinders']=[]
        s['components'][0]['box']=[-.2,-.03,-.02,.2,.03,.02]
        s['components'][1]['box']=[-.03,-.02,-.01,.03,.02,.01]
        return s

    def test_partial_planar_joint_recommends_evidenced_slide_direction_not_historical_axis(self):
        s=self.guide();c=recommendations.draft(s)['candidates'][0]
        o=c['options'][c['preferred_option_index']]
        self.assertEqual(o['kind'],'prismatic')
        self.assertEqual(o['connection_intent']['axis_hint'],[1,0,0])
        self.assertEqual(o['source'],'elongated_global_bounding_box_heuristic')
        self.assertFalse(c['evidence']['guide_direction_hypotheses'][0]['design_intent_proven'])
        self.assertTrue(o['requires_goal_confirmation']);self.assertFalse(o['executable'])

    def test_distant_bracket_is_not_recommended_as_slider_just_because_reference_is_long(self):
        s=self.guide();s['components'][1]['box']=[-.03,-.02,.1,.03,.02,.2]
        c=recommendations.draft(s)['candidates'][0]
        self.assertFalse(c['evidence']['guide_direction_hypotheses'])
        self.assertIsNone(c['preferred_option_index'])

    def test_nonelongated_or_invalid_box_does_not_invent_slide_direction(self):
        for box in ([0,0,0,.1,.1,.1],[0,0,0,.2,0,.1],[False,0,0,.2,.01,.01],[0,0,0,float('nan'),.01,.01]):
            s=self.guide();s['components'][0]['box']=box
            d=recommendations.draft(s)
            if not d['candidates']:
                self.assertEqual(d['reason'],'non_json_or_nonfinite_native_snapshot')
            else:self.assertFalse(d['candidates'][0]['evidence']['guide_direction_hypotheses'])

    def test_direction_that_existing_plane_prohibits_is_not_suggested(self):
        s=self.guide();s['components'][0]['box']=[-.02,-.2,-.02,.02,.2,.02]
        self.assertFalse(recommendations.draft(s)['candidates'][0]['evidence']['guide_direction_hypotheses'])

    def test_suppressed_mate_names_and_metadata_do_not_supply_the_goal(self):
        s=self.guide();d=recommendations.draft(s)
        suppressed=mate(99,'body','moving','cylindrical_axis');suppressed.update(suppressed=True,name='IMPORTANT_ROTATE_Z')
        s['mates'].append(suppressed)
        other=recommendations.draft(s)
        self.assertEqual(d['candidates'],other['candidates'])

    def test_renaming_and_input_order_do_not_change_geometric_recommendation(self):
        s=self.guide();d=recommendations.draft(s)['candidates'][0]
        s['components'].reverse()
        for c in s['components']:c['instance']='renamed_'+c['component_id']
        other=recommendations.draft(s)['candidates'][0]
        self.assertEqual(d['candidate_id'],other['candidate_id'])
        self.assertEqual(d['preferred_option_index'],other['preferred_option_index'])
        self.assertEqual(d['options'][0]['axis_global'],other['options'][0]['axis_global'])
        self.assertTrue(other['options'][0]['connection_intent']['component_a'].startswith('renamed_'))

    def test_parallel_but_different_rotation_axes_are_not_silently_merged(self):
        s=fixtures.survey()
        for c in s['components']:
            c['cylinders'].append({**c['cylinders'][0],'reference_point_global_m':[.1,0,0],'native_reference':c['component_id']+'second'})
        c=recommendations.draft(s)['candidates'][0]
        rotations=[o for o in c['options'] if o['kind']=='revolute']
        self.assertEqual(len(rotations),2)
        self.assertNotEqual(rotations[0]['axis_point_global_m'],rotations[1]['axis_point_global_m'])
        self.assertNotEqual(rotations[0]['connection_intent']['candidate_id'],rotations[1]['connection_intent']['candidate_id'])

    def test_full_native_state_and_lock_have_explicit_readonly_blockers(self):
        s=fixtures.survey([mate(1,'body','moving','cylindrical_axis')])
        s['components'][1]['constraint_state']={'status':'observed','fully_constrained':True}
        c=recommendations.draft(s)['candidates'][0]
        self.assertEqual(c['status'],'review_required');self.assertIsNone(c['preferred_option_index'])
        self.assertEqual(c['blocker'],'native_full_constraint_mobile_goal_requires_review')
        c=recommendations.draft(fixtures.survey([mate(1,'body','moving','lock')]))['candidates'][0]
        self.assertEqual(c['blocker'],'native_lock_trial_unsupported')

    def test_health_or_incomplete_inventory_does_not_produce_actionable_draft(self):
        s=fixtures.survey();s['inventory_complete']=False
        self.assertEqual(recommendations.draft(s)['candidates'],[])
        s=fixtures.survey([mate(1,'body','moving','cylindrical_axis')]);s['mates'][0]['error']=1
        self.assertEqual(recommendations.draft(s)['status'],'review_required')

    def test_pair_and_candidate_budgets_are_explicit_not_silent_global_completion(self):
        s=fixtures.survey();seed=s['components'][1]
        s['components']=[{**copy.deepcopy(seed),'component_id':str(i),'instance':'part-'+str(i)} for i in range(14)]
        d=recommendations.draft(s);search=d['search']
        self.assertEqual(search['eligible_pairs'],91)
        self.assertEqual(search['examined_pairs'],8)
        self.assertEqual(search['unexamined_pair_count'],83)
        self.assertEqual(len(d['candidates']),8)
        self.assertFalse(search['candidate_list_complete'])
        self.assertTrue(search['absence_is_not_proof_of_no_missing_connection'])
        seen=set();end=0
        while True:
            self.assertEqual(d['search']['pair_range_start'],end)
            end=d['search']['pair_range_end_exclusive']
            for c in d['candidates']:
                self.assertNotIn(c['candidate_id'],seen);seen.add(c['candidate_id'])
            cursor=d['next_cursor']
            if not cursor:break
            d=recommendations.draft(s,cursor=cursor)
        self.assertEqual(end,91);self.assertEqual(len(seen),91)
        self.assertFalse(d['search']['all_eligible_pairs_examined'])
        self.assertIsNone(d['search']['all_prior_pages_read_by_client'])

    def test_cursor_is_bound_to_task_scope_and_snapshot(self):
        s=fixtures.survey();seed=s['components'][1]
        s['components']=[{**copy.deepcopy(seed),'component_id':str(i),'instance':str(i)} for i in range(6)]
        d=recommendations.draft(s,binding='task-one');self.assertTrue(d['next_cursor'])
        with self.assertRaisesRegex(ValueError,'scope_mismatch'):recommendations.draft(s,cursor=d['next_cursor'],binding='task-two')
        s['components'][0]['box']=[0,0,0,1,1,1]
        with self.assertRaisesRegex(ValueError,'scope_mismatch'):recommendations.draft(s,cursor=d['next_cursor'],binding='task-one')

    def test_truncated_geometry_and_unknown_constraints_remain_visible(self):
        s=fixtures.survey([mate(17,'body','moving','lock',t=99)]);s['components'][1]['geometry_complete']=False
        d=recommendations.draft(s)
        self.assertFalse(d['search']['geometry_complete']);self.assertIn(17,d['omitted_native_feature_ids'])
        self.assertFalse(d['global_DOF_certified'])

    def test_no_material_pair_evidence_does_not_turn_all_floating_parts_into_rigid_candidates(self):
        s=fixtures.survey()
        for c in s['components']:c['cylinders']=[]
        d=recommendations.draft(s)
        self.assertEqual(d['candidates'],[])
        self.assertTrue(d['search']['all_eligible_pairs_examined'])
        self.assertFalse(d['mechanical_intent_proven'])


class DraftContractTests(unittest.TestCase):
    def test_cursor_page_reads_saved_snapshot_without_live_session_or_native_reconciliation(self):
        from test_service import temporary_workspace
        from pathlib import Path
        from sw_mcp.conversation.task_engine import TaskEngine
        from sw_mcp.conversation.core import StopBatch
        with temporary_workspace() as directory:
            work=Path(directory);tid='a'*32;task=work/('task-'+tid);(task/'session').mkdir(parents=True)
            s=fixtures.survey();seed=s['components'][1]
            s['components']=[{**copy.deepcopy(seed),'component_id':str(i),'instance':str(i)} for i in range(6)]
            (task/'session/通用配合原生调查.json').write_text(json.dumps(s),encoding='utf-8')
            first=recommendations.draft(s,binding=str(task.absolute()))
            engine=SimpleNamespace(work=work,tasks={tid:{'directory':str(task),'task_kind':'assembly_constraints'}})
            page=TaskEngine.get(engine,tid,draft_cursor=first['next_cursor'])
            self.assertEqual(page['connection_draft']['search']['pair_range_start'],8)
            self.assertFalse(page['write_dispatched'])
            with self.assertRaises(StopBatch) as error:TaskEngine.get(engine,tid,draft_cursor='wrong')
            self.assertEqual(error.exception.code,'CONNECTION_INTENT_INVALID')

    def test_public_cursor_rejects_evidence_collection_mix_before_any_dispatch(self):
        import motion_server
        from unittest.mock import patch,AsyncMock
        with patch.object(motion_server,'dialogue_call',new_callable=AsyncMock) as dispatch:
            result=asyncio.run(motion_server.get_mechanism_task('a'*32,True,'bad-cursor'))
        value=result.model_dump(mode='json',by_alias=True)
        self.assertTrue(value['isError']);dispatch.assert_not_called()
        self.assertEqual(value['structuredContent']['error']['code'],'CONNECTION_INTENT_INVALID')

    def test_readonly_draft_request_does_not_create_or_replace_a_native_plan(self):
        from sw_mcp.conversation import connection_task
        s=SimpleNamespace(connection_survey=fixtures.survey())
        t={'task_id':'a'*32,'phase':'awaiting_confirmation','plan_token':'old-token','proposal':{'plan_id':'old'},'connection_review':{}}
        before=copy.deepcopy(t)
        engine=SimpleNamespace(_require_session=Mock(),sessions={t['task_id']:s},_submit=Mock())
        result=connection_task.propose(engine,t,None)
        self.assertTrue(result['needs_connection_intent']);self.assertIn('connection_draft',result)
        self.assertFalse(result['write_dispatched']);self.assertEqual(t,before)
        engine._submit.assert_not_called()

    def test_selected_public_snippet_plans_using_current_geometry(self):
        s=fixtures.survey([mate(1,'body','moving','cylindrical_axis')])
        c=recommendations.draft(s)['candidates'][0]
        snippet=next(o['connection_intent'] for o in c['options'] if o['kind']=='revolute')
        by_name={c['instance']:c['component_id'] for c in s['components']}
        goal={**snippet,'component_a':by_name[snippet['component_a']],'component_b':by_name[snippet['component_b']]}
        p=joints.plan(s,[goal])
        self.assertEqual(p['status'],'plan_ready');self.assertEqual(len(p['actions']),1)
        self.assertEqual(p['existing_mates_deleted'],[]);self.assertEqual(p['fixed_state_changes'],[])


if __name__=='__main__':unittest.main()
