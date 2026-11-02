import copy,unittest
from sw_mcp import assembly_overview as overview
from tests.test_assembly_constraints import component,mate

def survey(cs,ms=()):return {'components':cs,'mates':list(ms),'inventory_complete':True}

class OverviewTests(unittest.TestCase):
    def test_unrelated_fixed_parts_are_not_recommended_as_one_rigid_group(self):
        s=survey([component('a',True),component('b',True)]);r=overview.recommend(s)
        self.assertTrue(r['accounting_complete']);self.assertEqual(r['observed_rigid_groups'],[])
        self.assertEqual(r['category_counts'],{'clarification_required':2})
        self.assertTrue(all(c['already_satisfies_user_goal'] is None for c in r['components']))

    def test_internal_rigid_chain_has_evidence_without_ground_assignment(self):
        r=overview.recommend(survey([component('a'),component('b'),component('c')],
              [mate(1,'a','b','lock'),mate(2,'b','c','lock')]))
        self.assertEqual(len(r['observed_rigid_groups']),1)
        self.assertEqual(set(r['observed_rigid_groups'][0]['members']),{'a','b','c'})
        self.assertTrue(all(c['supported_ground_rank']==0 for c in r['components']))
        self.assertFalse(r['all_components_mechanically_assigned']);self.assertFalse(r['motion_verified'])

    def test_readonly_recommendation_does_not_mutate_native_input(self):
        s=survey([component('a',True),component('b')],[mate(1,'a','b','cylindrical_axis')]);before=copy.deepcopy(s)
        r=overview.recommend(s);self.assertEqual(s,before);self.assertFalse(r['write_dispatched'])
        self.assertEqual(r['accounted_component_count'],2)

    def test_unknown_constraints_are_visible_and_not_counted_as_missing_mates(self):
        m=mate(1,'a','b','lock');m['type']=999
        r=overview.recommend(survey([component('a'),component('b')],[m]))
        self.assertTrue(all(c['unknown_native_feature_ids']==[1] for c in r['components']))
        self.assertTrue(all(c['reason']=='unmodelled_constraint_requires_preservation_review' for c in r['components']))

    def test_duplicate_and_incomplete_inventory_never_claim_accounting_complete(self):
        for s in [survey([component('a'),component('a')]),{**survey([component('a')]),'inventory_complete':False}]:
            self.assertFalse(overview.recommend(s)['accounting_complete'])

    def test_component_permutation_does_not_change_membership(self):
        s=survey([component('a',True),component('b'),component('c')],[mate(1,'a','b','lock')]);a=overview.recommend(s)
        s['components'].reverse();b=overview.recommend(s)
        self.assertEqual(a['components'],b['components']);self.assertEqual(a['observed_rigid_groups'],b['observed_rigid_groups'])

    def test_whole_plan_cannot_silently_omit_an_unconnected_fixed_accessory(self):
        s=survey([component('base',True),component('moving'),component('unknown',True)])
        g=[{'component_a':'moving','component_b':'base','kind':'revolute'}];r=overview.coverage(s,g)
        self.assertFalse(r['all_components_have_declared_targets']);self.assertEqual(r['unassigned_components'],['unknown'])
        self.assertEqual(r['declared_component_count'],2)

    def test_existing_group_binding_counts_when_it_needs_no_new_mates(self):
        s=survey([component('base',True),component('moving'),component('key')]);g=[{'component_a':'moving','component_b':'base','kind':'revolute'}]
        r=overview.coverage(s,g,[{'component_a':'key','component_b':'moving','kind':'rigid'}]);self.assertTrue(r['all_components_have_declared_targets'])
        self.assertFalse(r['motion_verified'])

    def test_foreign_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'outside_inventory'):overview.coverage(survey([component('a')]),[{'component_a':'a','component_b':'foreign','kind':'rigid'}])

if __name__=='__main__':unittest.main()
