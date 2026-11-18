import copy
import unittest
from sw_mcp import mechanism_loop as loop
from tests.test_assembly_constraints import component


def fixture():
    s={'inventory_complete':True,'components':[component(n,n=='frame') for n in ['frame','drive','brace','output']],'mates':[]}
    goals=[{'component_a':'drive','component_b':'frame','kind':'prismatic','axis_global':[0,0,1],'reference_point_global_m':[0,0,0]},
           {'component_a':'brace','component_b':'drive','kind':'rigid'},
           {'component_a':'output','component_b':'brace','kind':'rigid'},
           {'component_a':'output','component_b':'drive','kind':'revolute','axis_global':[0,0,1],'reference_point_global_m':[0,0,0]}]
    primary={'component_a':'drive','component_b':'frame','kind':'prismatic'}
    return s,goals,primary


class MechanismLoopTests(unittest.TestCase):
    def test_later_multirow_mate_can_make_an_earlier_new_scalar_bundle_redundant(self):
        from sw_mcp.assembly_completion import SparseBasis
        base=SparseBasis();base.add({2:1.})
        bundles=[[{0:1.}],[{0:1.,1:1.},{1:1.}]]
        kept,removed,matrix=loop.prune_bundles(base,bundles)
        self.assertEqual(kept,[1]);self.assertEqual(removed,[0]);self.assertEqual(len(matrix.pivots),3)
        self.assertEqual(base.pivots,{2:{2:1.}});self.assertEqual(matrix.trial([{0:1.},{1:1.},{2:1.}]),0)

    def test_irreplaceable_new_bundle_and_existing_native_rows_remain(self):
        from sw_mcp.assembly_completion import SparseBasis
        base=SparseBasis();base.add({0:1.})
        kept,removed,matrix=loop.prune_bundles(base,[[{1:1.}],[{0:1.}]])
        self.assertEqual(kept,[0]);self.assertEqual(removed,[1]);self.assertEqual(len(matrix.pivots),2)
        self.assertEqual(base.trial([{1:1.}]),1)

    def test_unused_local_joint_not_claimed_independently_actuable(self):
        s,goals,p=fixture();before=copy.deepcopy(s);matrix=loop.ideal_graph(s,goals).matrix
        old=copy.deepcopy(matrix.pivots);v=loop.review(s,goals,matrix,p,['output'])
        self.assertEqual(v['coupled_goal_indices'],[3]);self.assertEqual(s,before);self.assertEqual(matrix.pivots,old)
        self.assertTrue(v['native_motion_required'] and v['both_directions_required'] and v['all_declared_joint_residuals_required'])
        self.assertFalse(v['global_DOF_certified'] or v['finite_motion_verified'] or v['independent_joint_actuation_certified'])

    def test_locking_primary_input_always_refused(self):
        s,goals,p=fixture();goals.append({'component_a':'drive','component_b':'frame','kind':'rigid'})
        with self.assertRaisesRegex(loop.LoopReviewError,'primary_input_locked') as raised:
            loop.review(s,goals,loop.ideal_graph(s,goals).matrix,p,['output'])
        evidence=raised.exception.diagnostics
        self.assertEqual(evidence['input_rank'],6)
        self.assertEqual(evidence['conflict_witness']['closing_goal']['instance_a'],'drive')
        self.assertIsNone(evidence['alternative_joint_to_review'])

    def test_missing_declared_constraint_not_excused_as_coupling(self):
        s,goals,p=fixture();matrix=loop.ideal_graph(s,[g for i,g in enumerate(goals) if i!=2]).matrix
        with self.assertRaisesRegex(loop.LoopReviewError,'targets_not_fulfilled') as raised:
            loop.review(s,goals,matrix,p,['output'])
        evidence=raised.exception.diagnostics
        self.assertGreater(evidence['missing_constraint_rank'],0)
        self.assertTrue(any(row['goal_index']==2 and row['instance_a']=='output' and row['witness_twists'] for row in evidence['affected_goals']))

    def test_excess_constraints_not_excused_as_coupling(self):
        s,goals,p=fixture();matrix=loop.ideal_graph(s,goals+[{'component_a':'drive','component_b':'frame','kind':'rigid'}]).matrix
        with self.assertRaisesRegex(loop.LoopReviewError,'exceed_declared_targets') as raised:
            loop.review(s,goals,matrix,p,['output'])
        evidence=raised.exception.diagnostics
        self.assertTrue(any(r['goal_index']==0 and r['required_projected_rank']==5 and r['planned_projected_rank']==6 for r in evidence['affected_goals']))

    def test_wrong_primary_returns_a_named_compatible_candidate(self):
        s,goals,p=fixture();matrix=loop.ideal_graph(s,goals).matrix
        with self.assertRaisesRegex(loop.LoopReviewError,'primary_goal_not_unique') as raised:
            loop.review(s,goals,matrix,{**p,'component_a':'output'},['output'])
        evidence=raised.exception.diagnostics
        self.assertEqual(evidence['matching_goal_count'],0)
        self.assertEqual(evidence['recommended_primary']['instance_a'],'drive')
        self.assertEqual(evidence['recommended_primary']['instance_b'],'frame')
        self.assertEqual(evidence['recommended_primary']['projected_rank'],5)

    def test_closing_revolute_suggests_reviewing_a_proven_axial_release(self):
        s,goals,p=fixture()
        goals.append({'component_a':'brace','component_b':'frame','kind':'revolute',
                      'axis_global':[0,0,1],'reference_point_global_m':[0,0,0],
                      'source':'current_native_coaxial_geometry_not_motion_proof'})
        with self.assertRaisesRegex(loop.LoopReviewError,'primary_input_locked') as raised:
            loop.review(s,goals,loop.ideal_graph(s,goals).matrix,p,['output'])
        advice=raised.exception.diagnostics['alternative_joint_to_review']
        self.assertEqual((advice['goal_index'],advice['review_kind'],advice['projected_input_rank']),(4,'cylindrical',5))
        self.assertFalse(advice['automatic_change'] or advice['native_motion_verified'])
        self.assertEqual(goals[-1]['kind'],'revolute')

    def test_unknown_native_constraint_is_not_treated_as_absent(self):
        s,goals,p=fixture();s['mates']=[{'native_feature_id':3,'suppressed':False,'error':0,'warning':False,'type':999,'entities':[]}]
        with self.assertRaisesRegex(loop.LoopReviewError,'unknown_constraints'):loop.ideal_graph(s,goals)

    def test_output_reachable_only_through_stationary_frame_refused(self):
        s,goals,p=fixture();s['components'].append(component('unrelated'))
        goals.append({'component_a':'unrelated','component_b':'frame','kind':'revolute','axis_global':[0,0,1],'reference_point_global_m':[0,0,0]})
        with self.assertRaisesRegex(loop.LoopReviewError,'output_not_connected'):loop.review(s,goals,loop.ideal_graph(s,goals).matrix,p,['unrelated'])

    def test_missing_outputs_or_guessed_rotary_input_refused(self):
        s,goals,p=fixture();matrix=loop.ideal_graph(s,goals).matrix
        with self.assertRaisesRegex(loop.LoopReviewError,'one_to_16'):loop.review(s,goals,matrix,p,[])
        with self.assertRaisesRegex(loop.LoopReviewError,'explicit_linear_input'):loop.review(s,goals,matrix,{**p,'kind':'revolute'},['output'])


if __name__=='__main__':unittest.main()
