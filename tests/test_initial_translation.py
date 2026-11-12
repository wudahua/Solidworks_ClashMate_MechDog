import copy
import unittest
from sw_mcp import initial_translation as init
from tests.test_assembly_constraints import component


def survey(offset=2e-7):
    cs=[component('frame',True),component('moving')]
    for c,x in zip(cs,(0.,offset)):
        c['transform'][9]=x
        c['cylinders']=[{'axis_global':[0.,0.,1.],'reference_point_global_m':[x,0.,0.],
                         'cylinder_radius_m':.005,'reference_kind':'cylindrical_face'}]
    return {'inventory_complete':True,'components':cs,'mates':[]}


def goal(kind='revolute'):
    return {'component_a':'moving','component_b':'frame','kind':kind,'axis_hint':[0,0,1]}


class InitialTranslationTests(unittest.TestCase):
    def test_fixed_reference_and_rotations_preserved_and_input_immutable(self):
        s=survey();before=copy.deepcopy(s);v,p=init.propose(s,[goal()])
        self.assertEqual(s,before)
        self.assertAlmostEqual(v['components'][1]['transform'][9],0.,places=15)
        self.assertEqual(v['components'][0]['transform'],s['components'][0]['transform'])
        self.assertEqual(v['components'][1]['transform'][:9],s['components'][1]['transform'][:9])
        self.assertTrue(p['requires_alignment_confirmation'])
        self.assertFalse(p['native_pose_verified'] or p['coaxial_tolerance_relaxed'])

    def test_rigid_member_moves_with_its_declared_peer(self):
        s=survey();peer=component('peer');s['components'].append(peer)
        v,p=init.propose(s,[goal(),{'component_a':'peer','component_b':'moving','kind':'rigid'}])
        e={x['component_id']:x for x in p['entries']}
        for a,b in zip(e['peer']['delta_m'],e['moving']['delta_m']):self.assertAlmostEqual(a,b,places=15)

    def test_budget_excess_never_becomes_a_larger_coaxial_tolerance(self):
        with self.assertRaisesRegex(init.InitialTranslationError,'budget_exceeded'):
            init.propose(survey(1.5e-6),[goal()],.001)

    def test_existing_even_suppressed_mates_refused(self):
        s=survey();s['mates']=[{'suppressed':True}]
        with self.assertRaisesRegex(init.InitialTranslationError,'zero_existing_mates'):init.propose(s,[goal()])

    def test_rotation_needed_does_not_become_translation(self):
        s=survey();s['components'][1]['cylinders'][0]['axis_global']=[1,0,0]
        with self.assertRaisesRegex(init.InitialTranslationError,'axis_selection_required'):init.propose(s,[goal()])

    def test_two_near_material_axes_require_selection(self):
        s=survey();second=copy.deepcopy(s['components'][0]['cylinders'][0]);second['reference_point_global_m'][0]=5e-7
        s['components'][0]['cylinders'].append(second)
        with self.assertRaises(init.InitialTranslationError) as ctx:init.propose(s,[goal()])
        self.assertEqual(len(ctx.exception.diagnostics['choices']),2)

    def test_direction_alone_never_invents_a_rotation_axis(self):
        s=survey();s['components'][1]['cylinders']=[]
        with self.assertRaisesRegex(init.InitialTranslationError,'axis_selection_required'):init.propose(s,[goal()])

    def test_declared_slide_without_cylinders_only_preserves_current_offset(self):
        s=survey();s['components'][1]['cylinders']=[]
        v,p=init.propose(s,[goal('prismatic')])
        self.assertEqual(v['components'][1]['transform'],s['components'][1]['transform'])
        self.assertFalse(p['requires_alignment_confirmation'])

    def test_two_fixed_misaligned_bodies_refused(self):
        s=survey();s['components'][1]['fixed_component']=True
        with self.assertRaisesRegex(init.InitialTranslationError,'inconsistent'):init.propose(s,[goal()])

    def test_budget_type_and_policy_cap(self):
        for bad in (True,False,float('nan'),float('inf'),0,-1,.011):
            with self.subTest(value=bad),self.assertRaisesRegex(init.InitialTranslationError,'budget_invalid'):
                init.propose(survey(),[goal()],bad)

    def test_no_fixed_reference_refused(self):
        s=survey();s['components'][0]['fixed_component']=False
        with self.assertRaisesRegex(init.InitialTranslationError,'fixed_reference'):init.propose(s,[goal()])

    def test_exact_initial_state_does_not_request_alignment_authorization(self):
        s=survey(0);v,p=init.propose(s,[goal()]);self.assertEqual(v,s)
        self.assertEqual(p['moved_components'],0);self.assertFalse(p['requires_alignment_confirmation'])

    def test_native_readback_is_complete_and_stricter_than_old_pose_tolerance(self):
        s=survey();v,p=init.propose(s,[goal()]);r=init.verify_native(p,s['components'],v['components'])
        self.assertTrue(r['native_readback_verified']);self.assertEqual(r['all_component_count'],2)
        bad=copy.deepcopy(v);bad['components'][1]['transform'][9]+=1e-8
        with self.assertRaisesRegex(init.InitialTranslationError,'native_pose_mismatch'):init.verify_native(p,s['components'],bad['components'])
        with self.assertRaisesRegex(init.InitialTranslationError,'inventory_mismatch'):init.verify_native(p,s['components'],v['components'][:1])

    def test_pattern_relation_does_not_become_an_independent_part_translation(self):
        s=survey();s['structural_relations']={'components':[{'component_id':'moving','is_pattern_instance':True}]}
        with self.assertRaisesRegex(init.InitialTranslationError,'pattern_relations'):init.propose(s,[goal()])

    def test_solver_numeric_readback_is_distinct_from_translation_only_initialization(self):
        from sw_mcp import connection_trials as trials
        s=survey();s['components'][1]['box']=[-.01,-.01,-.01,.01,.01,.01]
        v,p=init.propose(s,[goal()]);v['components'][1]['transform']=trials.target(v['components'][1]['transform'],[0,0,1],1e-10,True)
        with self.assertRaisesRegex(init.InitialTranslationError,'native_pose_mismatch'):init.verify_native(p,s['components'],v['components'])
        proof=init.verify_native(p,s['components'],v['components'],solver_readback=True)
        self.assertTrue(proof['passed']);self.assertFalse(proof['initialization_rotation_authorized']);self.assertLess(proof['maximum_material_residual_m'],2e-9)
        self.assertEqual(p['maximum_rotation_rad'],0)

    def test_solver_rotation_cannot_move_material_points_beyond_nanometre_bound(self):
        from sw_mcp import connection_trials as trials
        s=survey();s['components'][1]['box']=[-100,-100,-100,100,100,100]
        v,p=init.propose(s,[goal()]);v['components'][1]['transform']=trials.target(v['components'][1]['transform'],[0,0,1],1e-10,True)
        with self.assertRaisesRegex(init.InitialTranslationError,'native_pose_mismatch'):init.verify_native(p,s['components'],v['components'],solver_readback=True)

    def test_solver_readback_never_advances_the_original_baseline_or_moves_fixed_bodies(self):
        s=survey();v,p=init.propose(s,[goal()]);v['components'][1]['transform'][9]+=1.2e-9
        self.assertTrue(init.verify_native(p,s['components'],v['components'],solver_readback=True)['passed'])
        v['components'][1]['transform'][9]+=1.2e-9
        with self.assertRaisesRegex(init.InitialTranslationError,'native_pose_mismatch'):init.verify_native(p,s['components'],v['components'],solver_readback=True)
        v,p=init.propose(s,[goal()]);v['components'][0]['transform'][9]+=5e-10
        with self.assertRaisesRegex(init.InitialTranslationError,'fixed_mismatch'):init.verify_native(p,s['components'],v['components'],solver_readback=True)

    def test_solver_orientation_residual_requires_observed_material_extent_and_small_rotation(self):
        from sw_mcp import connection_trials as trials
        s=survey();v,p=init.propose(s,[goal()]);v['components'][1]['transform']=trials.target(v['components'][1]['transform'],[0,0,1],1e-10,True)
        with self.assertRaisesRegex(init.InitialTranslationError,'box_unobserved'):init.verify_native(p,s['components'],v['components'],solver_readback=True)
        s['components'][1]['box']=[-.01,-.01,-.01,.01,.01,.01];v,p=init.propose(s,[goal()]);v['components'][1]['transform']=trials.target(v['components'][1]['transform'],[0,0,1],2e-6,True)
        with self.assertRaisesRegex(init.InitialTranslationError,'native_pose_mismatch'):init.verify_native(p,s['components'],v['components'],solver_readback=True)

    def test_material_resolution_not_uniform_matrix_coefficients_controls_solver_readback(self):
        from sw_mcp import connection_trials as trials
        s=survey();s['components'][1]['box']=[-.01,-.01,-.01,.01,.01,.01]
        v,p=init.propose(s,[goal()]);v['components'][1]['transform']=trials.target(v['components'][1]['transform'],[0,0,1],2e-9,True)
        r=init.verify_native(p,s['components'],v['components'],solver_readback=True)
        self.assertTrue(r['passed']);self.assertIsNone(r['rotation_coefficient_tolerance']);self.assertLess(r['maximum_material_residual_m'],2e-9)
        s['components'][1]['box']=[-1,-1,-1,1,1,1];v,p=init.propose(s,[goal()]);v['components'][1]['transform'][0]+=1e-8
        with self.assertRaisesRegex(init.InitialTranslationError,'native_pose_mismatch'):init.verify_native(p,s['components'],v['components'],solver_readback=True)


if __name__=='__main__':unittest.main()
