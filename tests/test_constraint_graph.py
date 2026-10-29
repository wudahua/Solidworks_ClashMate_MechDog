"""Indirect constraint, grounding, loop and uncertainty counterexamples."""
import copy
import unittest
from sw_mcp import constraint_graph as cg
from tests.test_assembly_constraints import component,mate


def survey(cs,ms):return {'components':cs,'mates':ms,'inventory_complete':True}


class GraphTests(unittest.TestCase):
    def test_three_part_rigid_chain_is_rigid_without_a_direct_end_pair(self):
        g=cg.model(survey([component('a',True),component('b'),component('c')],
                          [mate(1,'a','b','lock'),mate(2,'b','c','lock')]))
        r=g.relative('a','c')
        self.assertEqual((r['supported_direct_rank'],r['supported_effective_rank'],r['indirect_constraint_gain']),(0,6,6))
        self.assertFalse(r['finite_motion_verified']);self.assertFalse(r['global_DOF_certified'])
        self.assertTrue(all(c['supported_ground_rigidity'] for c in g.report()['components']))

    def test_constraints_to_different_rigid_peers_jointly_remove_a_relative_gap(self):
        cs=[component('base',True),component('peer'),component('moving')]
        ms=[mate(1,'base','peer','lock'),mate(2,'base','moving','planar_normal',axis=[1,0,0]),
            mate(3,'peer','moving','planar_normal',axis=[0,1,0]),mate(4,'peer','moving','planar_normal',axis=[0,0,1])]
        r=cg.model(survey(cs,ms)).relative('moving','base')
        self.assertEqual(r['supported_direct_rank'],3);self.assertEqual(r['supported_effective_rank'],6)

    def test_floating_rigid_group_is_not_world_grounded(self):
        r=cg.report(survey([component('a'),component('b')],[mate(1,'a','b','lock')]))
        self.assertEqual(len(r['rigid_groups']),1)
        self.assertFalse(any(c['supported_ground_rigidity'] for c in r['components']))

    def test_native_full_constraint_flag_does_not_create_a_mathematical_ground(self):
        c=component('moving');c['constraint_state']={'status':'observed','fully_constrained':True}
        r=cg.report(survey([c],[]))
        self.assertFalse(r['components'][0]['supported_ground_rigidity'])
        self.assertTrue(r['components'][0]['native_constraint_state']['fully_constrained'])

    def test_disconnected_parts_retain_six_relative_coordinates(self):
        g=cg.model(survey([component('a',True),component('b')],[]))
        self.assertEqual(g.relative('b','a')['supported_effective_rank'],0)
        self.assertEqual(len(g.report()['native_link_islands']),2)

    def test_serial_offset_rotary_axes_are_not_mislabeled_as_a_single_revolute(self):
        cs=[component('a',True),component('b'),component('c',point=[1,0,0])]
        ms=[]
        for i,a,b,p in [(1,'a','b',[0,0,0]),(3,'b','c',[1,0,0])]:
            ms.extend([mate(i,a,b,'cylindrical_axis',point=p),mate(i+1,a,b,'planar_normal',point=p)])
        r=cg.model(survey(cs,ms)).relative('c','a')
        self.assertEqual(r['supported_effective_rank'],4);self.assertEqual(len(r['free_basis']),2)

    def test_duplicate_and_reordered_constraints_do_not_change_effective_mobility(self):
        cs=[component('a',True),component('b'),component('c')]
        ms=[mate(1,'a','b','lock'),mate(2,'b','c','cylindrical_axis'),mate(3,'b','c','planar_normal')]
        g=cg.model(survey(cs,ms));other=cg.model(survey(list(reversed(cs)),list(reversed(ms))+[copy.deepcopy(ms[-1])]))
        self.assertEqual(g.relative('c','a')['supported_effective_rank'],5)
        self.assertEqual(other.relative('a','c')['supported_effective_rank'],5)
        self.assertEqual(len(g.matrix.pivots),len(other.matrix.pivots))

    def test_unknown_mate_keeps_the_native_link_and_uncertainty(self):
        r=cg.report(survey([component('a',True),component('b')],[mate(99,'a','b','lock',t=99)]))
        self.assertEqual(r['status'],'supported_graph_with_unknowns')
        self.assertEqual(r['unknown_constraints'][0]['native_feature_id'],99)
        self.assertEqual(len(r['native_link_islands']),1)
        self.assertFalse(r['components'][1]['no_observed_active_native_links'])
        self.assertFalse(r['unknown_constraints_treated_as_absent']);self.assertFalse(r['motion_verified'])

    def test_suppressed_lock_does_not_create_a_rigid_group(self):
        m=mate(1,'a','b','lock');m['suppressed']=True
        r=cg.report(survey([component('a'),component('b')],[m]))
        self.assertEqual(r['rigid_groups'],[]);self.assertEqual(r['suppressed_feature_ids'],[1])

    def root_mates(self,verified):
        ms=[mate(i,'moving','root','planar_normal',axis=v) for i,v in enumerate(([1,0,0],[0,1,0],[0,0,1]),1)]
        for m in ms:m['entities'][1].update(reference_owner_scope='assembly_root',root_reference_verified=verified)
        return ms

    def test_explicit_verified_native_root_planes_ground_without_changing_fixed_flag(self):
        r=cg.report(survey([component('moving')],self.root_mates(True)))
        self.assertTrue(r['components'][0]['supported_ground_rigidity'])
        self.assertFalse(r['components'][0]['native_fixed_flag']);self.assertEqual(len(r['verified_root_links']),3)

    def test_an_outside_component_or_unverified_root_is_not_an_anchor(self):
        r=cg.report(survey([component('moving')],self.root_mates(False)))
        self.assertFalse(r['components'][0]['supported_ground_rigidity']);self.assertEqual(len(r['unknown_constraints']),3)

    def test_new_snapshot_and_returned_result_mutation_do_not_poison_cached_evidence(self):
        s=survey([component('a',True),component('b')],[mate(1,'a','b','lock')])
        g=cg.model(s);r=g.relative('b','a');r['rows'].clear()
        self.assertEqual(g.relative('b','a')['supported_effective_rank'],6)
        report=g.report();report['components'][0]['active_native_feature_ids'].clear()
        self.assertEqual(g.report()['components'][0]['active_native_feature_ids'],[1])
        s['mates'][0]['suppressed']=True
        self.assertEqual(cg.model(s).relative('b','a')['supported_effective_rank'],0)
        self.assertEqual(g.relative('b','a')['supported_effective_rank'],6)

    def test_concurrent_readonly_drafts_do_not_mutate_the_shared_constraint_matrix(self):
        from concurrent.futures import ThreadPoolExecutor
        from sw_mcp import assembly_connections as j
        s=survey([component('a',True),component('b')],[mate(1,'a','b','cylindrical_axis')])
        g=cg.model(s);before=copy.deepcopy(g.matrix.pivots)
        def read(i):
            target=j.target_rows('rigid' if i%2 else 'revolute',[0,0,1],[0,0,0],g.origin,g.scale)
            missing=g.missing_target(target,'b','a')
            self.assertEqual(missing,2 if i%2 else 1)
            self.assertEqual(g.relative('b','a')['supported_effective_rank'],4)
        with ThreadPoolExecutor(max_workers=4) as workers:list(workers.map(read,range(60)))
        self.assertEqual(g.matrix.pivots,before)

    def test_missing_count_keeps_the_planners_absolute_rank_threshold(self):
        g=cg.Graph(survey([component('moving')],[]))
        g.matrix.add({0:1.0,1:1e-9})
        target=[[1.,0,0,0,0,0]]
        expected=g.matrix.trial(g.lift(target,'moving'))
        self.assertEqual(expected,0)
        self.assertEqual(g.missing_target(target,'moving'),expected)

    def test_missing_or_oversized_inventory_stays_unsupported(self):
        for s in ({'components':[],'mates':[],'inventory_complete':True},
                  {'components':[component(str(i)) for i in range(129)],'mates':[],'inventory_complete':True},
                  {'components':[component('a')],'mates':[],'inventory_complete':False}):
            with self.assertRaises(ValueError):cg.report(s)

    def test_pattern_dependency_is_not_fabricated_as_orphan_or_rigid_motion(self):
        s=survey([component('seed',True),component('instance')],[])
        s['structural_relations']={'components':[{'component_id':'instance','is_pattern_instance':True}]}
        r=cg.report(s);node=next(c for c in r['components'] if c['component_id']=='instance')
        self.assertTrue(node['no_observed_active_native_links'])
        self.assertFalse(node['no_observed_constraint_or_pattern_relation'])
        self.assertFalse(node['supported_ground_rigidity']);self.assertEqual(r['rigid_groups'],[])

    def indirect_locked(self):
        from tests.test_assembly_connections import survey as base
        s=base([mate(1,'body','moving','cylindrical_axis')]);s['components'].append(component('peer',True))
        s['mates'].extend([mate(2,'moving','peer','planar_normal'),mate(3,'moving','peer','planar_normal',axis=[1,0,0])])
        return s

    def test_draft_does_not_offer_free_rotation_through_an_indirectly_locked_chain(self):
        from sw_mcp import connection_recommendations as rec
        d=rec.draft(self.indirect_locked())
        c=next(c for c in d['candidates'] if {c['instance_a'],c['instance_b']}=={'moving','body'})
        self.assertEqual([o['kind'] for o in c['options']],['rigid'])
        self.assertEqual(c['supported_direct_rank'],4);self.assertEqual(c['supported_whole_inventory_effective_rank'],6)
        self.assertEqual(c['options'][0]['supported_whole_inventory_missing_coordinates_if_goal_chosen'],0)
        self.assertFalse(c['missing_connection_proven']);self.assertFalse(c['indirect_connection_sufficiency_not_evaluated'])

    def test_minimal_rigid_plan_adds_nothing_when_the_indirect_chain_already_suffices(self):
        from sw_mcp import assembly_connections as j
        p=j.plan(self.indirect_locked(),[{'component_a':'moving','component_b':'body','kind':'rigid'}])
        self.assertEqual(p['status'],'plan_ready');self.assertEqual(p['actions'],[])
        self.assertEqual(p['goals'][0]['missing_supported_constraints_before'],0)

    def test_goal_conflicting_only_through_other_parts_is_rejected_before_native_preview(self):
        from sw_mcp import assembly_connections as j
        with self.assertRaisesRegex(ValueError,'existing_indirect_constraints_conflict'):
            j.plan(self.indirect_locked(),[{'component_a':'moving','component_b':'body','kind':'revolute'}])


if __name__=='__main__':unittest.main()
