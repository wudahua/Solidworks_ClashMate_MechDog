import copy,unittest
from sw_mcp import assembly_hierarchy as h

def node(cid,kind=1,parent=None,mode=None,fixed=False,owning_fixed=False):
    return {'component_id':cid,'instance':cid,'document_type':kind,'parent_component_id':parent,'subassembly_solving':mode,
            'native_hierarchy_observed':True,'fixed_component':fixed,
            'parent_document_fixed_component':owning_fixed if parent is not None else None,
            'fixed_flag_observation_scope':'root_context_only' if parent is not None else 'assembly_root'}

class HierarchyTests(unittest.TestCase):
    def example(self):return [node('base',fixed=True),node('carrier',2,mode=0),node('fixed_child',parent='carrier',owning_fixed=True),node('floating_child',parent='carrier')]
    def test_rigid_subassembly_includes_fixed_and_floating_child_relations(self):
        cs=self.example();before=copy.deepcopy(cs);r=h.analyze(cs,require_native=True)
        self.assertEqual({b['component_a'] for b in r['rigid_child_pairs']},{'fixed_child','floating_child'})
        self.assertTrue(r['supported_for_connection_writes']);self.assertEqual(cs,before)
        self.assertEqual(r['parents']['fixed_child'],'carrier')
    def test_fixed_child_does_not_become_a_world_reference(self):
        r=h.analyze(self.example());self.assertIsNotNone(r['parents']['fixed_child'])
        with self.assertRaisesRegex(ValueError,'parent_scope'):h.require_top_level_target('fixed_child',r)
        h.require_top_level_target('carrier',r)
    def test_flexible_observation_is_retained_without_changing_it(self):
        cs=self.example();cs[1]['subassembly_solving']=1;r=h.analyze(cs)
        self.assertFalse(r['supported_for_connection_writes']);self.assertEqual(r['flexible_subassemblies'],['carrier'])
        self.assertEqual(r['rigid_child_pairs'],[])
        with self.assertRaisesRegex(ValueError,'flexible'):h.inherited_coverage({'carrier'},r)
    def test_parent_target_inherits_children_without_default_stationary_ownership(self):
        r=h.analyze(self.example());covered,proof=h.inherited_coverage({'carrier'},r)
        self.assertEqual(covered,{'carrier','fixed_child','floating_child'});self.assertNotIn('base',covered)
        self.assertEqual({p['declared_ancestor'] for p in proof},{'carrier'})
    def test_missing_parent_and_cycle_are_refused(self):
        cs=self.example();cs[2]['parent_component_id']='missing'
        with self.assertRaisesRegex(ValueError,'outside'):h.analyze(cs)
        cs=[node('a',2,'b',0),node('b',2,'a',0)]
        with self.assertRaisesRegex(ValueError,'cycle'):h.analyze(cs)
    def test_part_cannot_be_a_parent_or_carry_rigid_solving_mode(self):
        with self.assertRaisesRegex(ValueError,'parent_not'):h.analyze([node('a'),node('b',parent='a')])
        with self.assertRaisesRegex(ValueError,'part_cannot'):h.analyze([node('a',mode=0)])
    def test_unknown_and_boolean_modes_are_not_coerced_to_rigid(self):
        for mode in [False,None,-1,2,'0']:
            with self.assertRaisesRegex(ValueError,'solving_not_observed'):h.analyze([node('a',2,mode=mode)])
    def test_mixed_or_incomplete_observation_is_refused(self):
        cs=self.example();cs[2].pop('parent_component_id')
        with self.assertRaisesRegex(ValueError,'incomplete'):h.analyze(cs)
    def test_legacy_flat_fixtures_cannot_satisfy_required_native_observation(self):
        cs=[{'component_id':'a'}];self.assertTrue(h.analyze(cs)['legacy_flat_scope'])
        with self.assertRaisesRegex(ValueError,'native_hierarchy'):h.analyze(cs,require_native=True)
    def test_nested_rigid_assembly_coverage_and_depth(self):
        cs=[node('a',2,mode=0),node('b',2,'a',0),node('c',parent='b')];r=h.analyze(cs)
        self.assertEqual(r['maximum_depth'],3);self.assertEqual(h.inherited_coverage({'a'},r)[0],{'a','b','c'})

    def test_graph_fixed_child_is_rigid_to_floating_parent_but_not_world_grounded(self):
        from sw_mcp import constraint_graph
        from tests.test_assembly_constraints import component
        cs=[component(c['component_id'],c['fixed_component'])|c for c in self.example()]
        g=constraint_graph.model({'components':cs,'mates':[],'inventory_complete':True})
        self.assertEqual(g.rank('fixed_child','carrier'),6);self.assertEqual(g.rank('floating_child','carrier'),6)
        self.assertEqual(g.rank('fixed_child'),0);self.assertEqual(g.rank('carrier'),0)
        self.assertEqual(g.rank('base'),6)

    def test_graph_grounded_parent_grounds_descendants_without_changing_child_flags(self):
        from sw_mcp import constraint_graph
        from tests.test_assembly_constraints import component
        cs=[component(c['component_id'],c['fixed_component'])|c for c in self.example()];cs[1]['fixed_component']=True
        g=constraint_graph.model({'components':cs,'mates':[],'inventory_complete':True})
        self.assertEqual(g.rank('floating_child'),6);self.assertFalse(cs[3]['fixed_component'])

    def test_fixed_child_can_follow_translating_parent_but_cannot_slip(self):
        from sw_mcp import connection_trials as t
        from tests.test_assembly_constraints import component
        before={'carrier':component('carrier')['transform'],'child':component('child',point=[1,0,0])['transform']};after=copy.deepcopy(before)
        for pose in after.values():pose[9]+=.1
        parents={'carrier':None,'child':'carrier'};flags={'carrier':False,'child':True}
        self.assertTrue(t.fixed_pose_checks(before,after,flags,parents,parents)['passed'])
        after['child'][9]+=.001;self.assertFalse(t.fixed_pose_checks(before,after,flags,parents,parents)['passed'])

    def test_fixed_child_can_follow_rotating_parent_in_world_coordinates(self):
        from sw_mcp import connection_trials as t
        from tests.test_assembly_constraints import component
        import math
        before={'carrier':component('carrier')['transform'],'child':component('child',point=[1,0,0])['transform']};after=copy.deepcopy(before)
        angle=.1;c=math.cos(angle);s=math.sin(angle)
        after['carrier'][:9]=[c,s,0,-s,c,0,0,0,1];after['child'][:9]=after['carrier'][:9];after['child'][9:12]=[c,s,0]
        parents={'carrier':None,'child':'carrier'}
        self.assertTrue(t.fixed_pose_checks(before,after,{'carrier':False,'child':True},parents,parents)['passed'])

    def test_missing_or_forged_parent_scope_cannot_relax_world_fixed_checks(self):
        from sw_mcp import connection_trials as t
        from tests.test_assembly_constraints import component
        poses={'base':component('base')['transform'],'child':component('child')['transform']};parents={'base':None,'child':'base'}
        for observed in [None,{'base':None,'child':None},{'child':'base'}]:
            with self.assertRaisesRegex(ValueError,'parent_scope'):t.fixed_pose_checks(poses,poses,{'base':True,'child':True},parents,observed)
        with self.assertRaisesRegex(ValueError,'expected_parent_scope'):t.fixed_pose_checks(poses,poses,{'base':True,'child':True},None,parents)

    def test_indirect_missing_parent_is_structured_refusal(self):
        from sw_mcp import connection_trials as t
        from tests.test_assembly_constraints import component
        poses={key:component(key)['transform'] for key in ('child','parent')}
        parents={'child':'parent','parent':'missing'}
        with self.assertRaisesRegex(ValueError,'trial_parent_outside_inventory'):
            t.fixed_pose_checks(poses,poses,{'child':True,'parent':False},parents,parents)

    def test_overview_exposes_parent_frame_without_offering_internal_child_edits(self):
        from sw_mcp import assembly_overview
        from tests.test_assembly_constraints import component
        cs=[component(c['component_id'],c['fixed_component'])|c for c in self.example()]
        result=assembly_overview.recommend({'components':cs,'mates':[],'inventory_complete':True})
        ledger={c['component_id']:c for c in result['components']}
        self.assertEqual(ledger['fixed_child']['fixed_flag_reference_scope'],'root_context_only')
        self.assertFalse(ledger['fixed_child']['native_fixed_flag']);self.assertTrue(ledger['fixed_child']['parent_document_fixed_component'])
        self.assertFalse(ledger['fixed_child']['connection_target_selectable'])
        self.assertTrue(ledger['carrier']['connection_target_selectable'])
        self.assertEqual(ledger['fixed_child']['supported_ground_rank'],0)
        from sw_mcp import constraint_graph
        observed=constraint_graph.model({'components':cs,'mates':[],'inventory_complete':True}).report()
        self.assertFalse(next(c for c in observed['components'] if c['component_id']=='fixed_child')['no_observed_constraint_or_pattern_relation'])
        group=next(g for g in result['observed_rigid_groups'] if 'fixed_child' in g['members'])
        self.assertEqual(group['anchor_instance'],'carrier')
        self.assertEqual(group['top_level_target_instances'],['carrier'])
        self.assertEqual(set(group['native_descendant_instances_preserved']),{'fixed_child','floating_child'})
        from sw_mcp import assembly_constraints
        local=assembly_constraints.analyze(cs,[])
        child=next(c for c in local['components'] if c['component_id']=='fixed_child')
        self.assertIsNone(child['suggested_group'])
        self.assertEqual(child['fixed_flag_reference_scope'],'root_context_only')
        self.assertEqual(child['status'],'preserve_native_rigid_parent_membership')
        self.assertFalse(any(q['component_id']=='fixed_child' for q in local['questions']))
        coverage=assembly_overview.coverage({'components':cs},[{'component_a':'carrier','component_b':'base','kind':'revolute'}])
        self.assertTrue(coverage['all_components_have_declared_targets'])
        self.assertFalse(coverage['motion_verified'])

    def test_draft_only_offers_top_level_rigid_body_pairs(self):
        from sw_mcp import connection_recommendations as recommendations
        from tests.test_assembly_constraints import component
        from tests.test_assembly_connections import survey
        s=survey();s['components'][0].update(node('body',fixed=True));s['components'][1].update(node('moving',2,mode=0))
        child=component('child',False)|node('child',parent='moving',owning_fixed=True)
        child['cylinders']=s['components'][1]['cylinders'];s['components'].append(child)
        result=recommendations.draft(s)
        self.assertTrue(result['candidates'])
        for candidate in result['candidates']:
            self.assertEqual({candidate['component_a'],candidate['component_b']},{'body','moving'})
        s['components'][1]['subassembly_solving']=1
        denied=recommendations.draft(s)
        self.assertEqual(denied['reason'],'flexible_subassembly_scope_unsupported')
        self.assertFalse(denied['candidates'])

    def test_owning_document_flag_defines_relative_fixed_state_in_flexible_readonly_graph(self):
        from sw_mcp import constraint_graph
        from tests.test_assembly_constraints import component
        cs=[component(c['component_id'],c['fixed_component'])|c for c in self.example()]
        cs[1]['subassembly_solving']=1
        graph=constraint_graph.model({'components':cs,'mates':[],'inventory_complete':True})
        self.assertFalse(cs[2]['fixed_component']);self.assertTrue(cs[2]['parent_document_fixed_component'])
        self.assertEqual(graph.rank('fixed_child','carrier'),6)
        self.assertEqual(graph.rank('floating_child','carrier'),0)
        self.assertEqual(graph.rank('fixed_child'),0)

    def test_root_context_child_fixed_value_never_substitutes_for_owning_document_flag(self):
        from sw_mcp import constraint_graph
        from tests.test_assembly_constraints import component
        cs=[component(c['component_id'],c['fixed_component'])|c for c in self.example()]
        cs[1]['subassembly_solving']=1;cs[3]['fixed_component']=True
        graph=constraint_graph.model({'components':cs,'mates':[],'inventory_complete':True})
        self.assertEqual(graph.rank('floating_child','carrier'),0)
        self.assertEqual(graph.rank('floating_child'),0)

    def test_missing_or_coerced_owning_document_flag_is_refused(self):
        for invalid in (None,0,1,'false'):
            cs=self.example();cs[2]['parent_document_fixed_component']=invalid
            with self.assertRaisesRegex(ValueError,'owning_document_fixed_flag_not_observed'):h.analyze(cs)
        cs=self.example();cs[2].pop('parent_document_fixed_component')
        with self.assertRaisesRegex(ValueError,'incomplete'):h.analyze(cs)

if __name__=='__main__':unittest.main()
