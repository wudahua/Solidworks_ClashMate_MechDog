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
        with self.assertRaisesRegex(loop.LoopReviewError,'primary_input_locked'):
            loop.review(s,goals,loop.ideal_graph(s,goals).matrix,p,['output'])

    def test_missing_declared_constraint_not_excused_as_coupling(self):
        s,goals,p=fixture();matrix=loop.ideal_graph(s,[g for i,g in enumerate(goals) if i!=2]).matrix
        with self.assertRaisesRegex(loop.LoopReviewError,'targets_not_fulfilled'):loop.review(s,goals,matrix,p,['output'])

    def test_excess_constraints_not_excused_as_coupling(self):
        s,goals,p=fixture();matrix=loop.ideal_graph(s,goals+[{'component_a':'drive','component_b':'frame','kind':'rigid'}]).matrix
        with self.assertRaisesRegex(loop.LoopReviewError,'exceed_declared_targets'):loop.review(s,goals,matrix,p,['output'])

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
