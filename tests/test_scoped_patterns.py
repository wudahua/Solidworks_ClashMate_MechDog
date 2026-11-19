import copy,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from sw_mcp import connection_groups as groups
from sw_mcp import mirror_connections
from sw_mcp.conversation import connection_task,core
from sw_mcp.task_errors import task_failure
from tests.test_assembly_connections import survey
from tests.test_assembly_constraints import component


def fixture():
    s=survey();s['components'].append(component('copy'))
    s['structural_relations']={'components':[
        {'component_id':'body','instance':'body','native_feature_id':1,'is_pattern_instance':False,'parent_features':[]},
        {'component_id':'moving','instance':'moving','native_feature_id':2,'is_pattern_instance':False,'parent_features':[]},
        {'component_id':'copy','instance':'copy','native_feature_id':3,'is_pattern_instance':True,'parent_features':[{'native_feature_id':10},{'native_feature_id':2}]}],
        'patterns':[{'native_feature_id':10,'type':'LocalCirPattern','suppressed':False,'seed_component_ids':['moving'],'child_features':[{'native_feature_id':3}]}],
        'feature_inventory_truncated':False,'issues':[]}
    return s


def mirror_fixture():
    s=fixture();structure=s['structural_relations']
    structure['components'][2]['parent_features']=[
        {'native_feature_id':10,'name':'镜向零部件1','type':'MirrorCompFeat'},
        {'native_feature_id':2,'name':'moving','type':'Reference'}]
    structure['patterns']=[]
    structure['mirrors']=[{'native_feature_id':10,'name':'镜向零部件1','definition_available':True,
        'suppressed':False,'definition_source_component_ids':['moving'],'child_features':[{'native_feature_id':3}]}]
    return s


class ScopedPatternTests(unittest.TestCase):
    def expand(self,s,members=None):
        return groups.expand(s,[],[{'name':'declared','anchor':'body','members':members or ['body','moving','copy']}])

    def test_closed_local_family_preserves_derived_native_relation_no_individual_mate(self):
        s=fixture();before=copy.deepcopy(s);e=self.expand(s)
        self.assertEqual(s,before);self.assertEqual(e['goals'],[{'component_a':'moving','component_b':'body','kind':'rigid'}])
        self.assertEqual({b['component_a'] for b in e['group_bindings']},{'moving','copy'})
        self.assertEqual(e['pattern_scope_reviews'][0]['seed_component_ids'],['moving'])
        self.assertFalse(e['pattern_scope_reviews'][0]['individual_mate_write_allowed'])
        self.assertFalse(e['pattern_scope_reviews'][0]['rigid_motion_proven'])

    def test_missing_same_group_seed_names_the_needed_component(self):
        with self.assertRaises(groups.GroupIntentError) as caught:self.expand(fixture(),['body','copy'])
        self.assertEqual(caught.exception.diagnostics['required_seed_instances'],['moving'])

    def test_foreign_seed_is_not_filtered_away_by_dependency_analysis(self):
        s=fixture();s['structural_relations']['patterns'][0]['seed_component_ids'].append('foreign')
        with self.assertRaises(groups.GroupIntentError) as caught:self.expand(s)
        self.assertEqual(caught.exception.diagnostics['unresolved_seed_ids'],['foreign'])

    def test_partial_or_failed_feature_scan_cannot_admit_local_family(self):
        for field,value in [('feature_inventory_truncated',True),('feature_inventory_truncated',None),('issues',[{'hresult':-1}])]:
            with self.subTest(field=field,value=value):
                s=fixture();s['structural_relations'][field]=value
                with self.assertRaisesRegex(groups.GroupIntentError,'seed_scope_review'):self.expand(s)

    def test_duplicate_or_omitted_observed_component_is_not_complete(self):
        for duplicate in (True,False):
            s=fixture();rows=s['structural_relations']['components']
            if duplicate:rows.append(copy.deepcopy(rows[0]))
            else:rows.pop(0)
            with self.assertRaisesRegex(groups.GroupIntentError,'seed_scope_review'):self.expand(s)

    def test_feature_id_collision_is_not_unique_pattern_evidence(self):
        s=fixture();s['structural_relations']['patterns'].append(copy.deepcopy(s['structural_relations']['patterns'][0]))
        with self.assertRaisesRegex(groups.GroupIntentError,'seed_scope_review'):self.expand(s)

    def test_suppressed_unknown_and_missing_seed_patterns_are_not_admitted(self):
        for field,value in [('suppressed',True),('suppressed',None),('type','DerivedPattern'),('seed_component_ids',[])]:
            with self.subTest(field=field,value=value):
                s=fixture();s['structural_relations']['patterns'][0][field]=value
                with self.assertRaisesRegex(groups.GroupIntentError,'seed_scope_review'):self.expand(s)

    def test_parent_or_child_one_sided_relationship_is_not_enough(self):
        for missing in ('parent','child'):
            s=fixture()
            if missing=='parent':s['structural_relations']['components'][2]['parent_features']=[{'native_feature_id':2}]
            else:s['structural_relations']['patterns'][0]['child_features']=[]
            with self.assertRaisesRegex(groups.GroupIntentError,'seed_scope_review'):self.expand(s)

    def test_self_seed_cycle_is_rejected(self):
        s=fixture();s['structural_relations']['patterns'][0]['seed_component_ids']=['copy']
        with self.assertRaises(groups.GroupIntentError) as caught:self.expand(s)
        self.assertEqual(caught.exception.diagnostics['scope_reason'],'cyclic_pattern_seed_dependency')

    def test_native_take_limits_do_not_prove_a_complete_relationship(self):
        for part,count in [('parent',64),('child',256)]:
            s=fixture()
            if part=='parent':s['structural_relations']['components'][2]['parent_features']=[{'native_feature_id':10}]*count
            else:s['structural_relations']['patterns'][0]['child_features']=[{'native_feature_id':3}]*count
            with self.assertRaises(groups.GroupIntentError):self.expand(s)

    def test_shared_nested_seed_is_reviewed_once_without_dropping_bindings(self):
        s=fixture()
        for i in (2,3):
            cid='copy'+str(i);fid=i+2;s['components'].append(component(cid))
            s['structural_relations']['components'].append({'component_id':cid,'instance':cid,'native_feature_id':fid,'is_pattern_instance':True,'parent_features':[{'native_feature_id':10+i},{'native_feature_id':3}]})
            s['structural_relations']['patterns'].append({'native_feature_id':10+i,'type':'LocalLPattern','suppressed':False,'seed_component_ids':['copy'],'child_features':[{'native_feature_id':fid}]})
        e=self.expand(s,['body','moving','copy','copy2','copy3'])
        self.assertEqual(len(e['pattern_scope_reviews']),3);self.assertEqual(len(e['group_bindings']),4)

    def test_nested_seed_chain_is_closed_and_checked_not_flattened_into_mates(self):
        s=fixture();s['components'].append(component('copy2'))
        s['structural_relations']['components'].append({'component_id':'copy2','instance':'copy2','native_feature_id':4,'is_pattern_instance':True,'parent_features':[{'native_feature_id':11},{'native_feature_id':3}]})
        s['structural_relations']['patterns'].append({'native_feature_id':11,'type':'LocalLPattern','suppressed':False,'seed_component_ids':['copy'],'child_features':[{'native_feature_id':4}]})
        e=self.expand(s,['body','moving','copy','copy2']);self.assertEqual(len(e['goals']),1);self.assertEqual(len(e['pattern_scope_reviews']),2)
        s['structural_relations']['patterns'][0]['seed_component_ids']=['copy2']
        with self.assertRaises(groups.GroupIntentError):self.expand(s,['body','moving','copy','copy2'])

    def test_derived_member_cannot_be_released_or_be_an_anchor(self):
        s=fixture();s['components'][-1]['fixed_component']=True
        with self.assertRaisesRegex(groups.GroupIntentError,'pattern_member_fixed_release'):
            groups.expand(s,[],[{'name':'g','members':['body','moving','copy']}],['copy'])
        with self.assertRaisesRegex(groups.GroupIntentError,'cannot_be_group_anchor'):
            groups.expand(fixture(),[],[{'name':'g','anchor':'copy','members':['body','moving','copy']}])

    def test_normal_member_and_goal_budgets_are_preserved(self):
        s=fixture()
        for i in range(30):s['components'].append(component('extra'+str(i)))
        with self.assertRaisesRegex(groups.GroupIntentError,'member_budget'):
            self.expand(s,[c['instance'] for c in s['components']])

    def test_mirror_review_keeps_native_parent_source_and_no_automatic_remap(self):
        row=mirror_connections.review(mirror_fixture())[0]
        self.assertEqual(row['source_binding_status'],'unique_native_source_observed')
        self.assertEqual(row['source_candidates'],[{'component_id':'moving','instance':'moving'}])
        self.assertEqual(row['root_source_candidates'],row['source_candidates'])
        self.assertFalse(row['rigid_motion_proven'] or row['automatic_goal_remap'] or row['individual_mate_write_allowed'])

    def test_explicit_mirror_family_keeps_derived_member_for_verification(self):
        s=mirror_fixture()
        for whole in (False,True):
            e=groups.expand(s,[],[{'name':'test','members':['body','moving','copy'],'anchor':'body'}],whole_assembly=whole)
            self.assertEqual([g['component_a'] for g in e['goals']],['moving'])
            self.assertEqual({b['component_a'] for b in e['group_bindings']},{'moving','copy'})
            self.assertEqual(e['pattern_scope_reviews'][0]['instance'],'copy')
            self.assertFalse(e['pattern_scope_reviews'][0]['rigid_motion_proven'])
        with self.assertRaisesRegex(groups.GroupIntentError,'pattern_group_requires_seed_scope_review'):
            groups.expand(s,[],[{'name':'test','members':['body','copy'],'anchor':'body'}])

    def test_mirror_incomplete_native_definition_is_only_a_candidate(self):
        for what in ('definition','children','candidates','multiple_parent_features','inventory'):
            with self.subTest(what=what):
                s=mirror_fixture()
                structure=s['structural_relations'];m=structure['mirrors'][0]
                if what=='definition':m['definition_available']=False
                elif what=='children':m['child_features']=[]
                elif what=='candidates':m['definition_source_component_ids']=['moving','outside_scope']
                elif what=='multiple_parent_features':
                    structure['components'][2]['parent_features'].append({'native_feature_id':11,'type':'MirrorCompFeat','name':'other'})
                else:structure['feature_inventory_truncated']=True
                row=mirror_connections.review(s)[0]
                self.assertEqual(row['source_binding_status'],'mirror_source_review_required')
                self.assertEqual(row['root_source_candidates'],[])

    def test_nested_mirror_can_have_one_root_without_exact_nested_remap(self):
        s=mirror_fixture();structure=s['structural_relations']
        s['components'].append(component('nested'))
        parent={'native_feature_id':11,'name':'镜向零部件2','type':'MirrorCompFeat'}
        structure['components'].append({'component_id':'nested','native_feature_id':4,'is_pattern_instance':True,
                                        'parent_features':[parent,{'native_feature_id':2,'type':'Reference'}]})
        structure['mirrors'].append({'native_feature_id':11,'definition_available':True,'suppressed':False,
            'definition_source_component_ids':['moving','copy'],'child_features':[{'native_feature_id':4}]})
        nested=mirror_connections.review(s)[1]
        self.assertEqual(nested['source_binding_status'],'mirror_source_review_required')
        self.assertEqual(nested['root_source_candidates'],[{'component_id':'moving','instance':'moving'}])
        self.assertFalse(nested['automatic_goal_remap'])

    def test_direct_mirror_goal_refused_before_native_queue_with_goal_indices(self):
        s=mirror_fixture()
        task={'task_id':'t','phase':'constraint_review_ready','connection_review':{'write_scope_allowed':True}}
        session=SimpleNamespace(connection_survey=s)
        engine=Mock();engine.sessions={'t':session}
        goals=[{'component_a':'moving','component_b':'body','kind':'revolute'},
               {'component_a':'copy','component_b':'body','kind':'revolute'}]
        for mode in ('declared','whole_assembly'):
            with self.subTest(mode=mode),self.assertRaises(core.StopBatch) as caught:
                connection_task.propose(engine,task,goals,completion_scope=mode)
            diag=caught.exception.diagnostics
            self.assertEqual(caught.exception.code,'CONNECTION_SCOPE_UNSUPPORTED')
            self.assertEqual(diag['blocked_goals'][0]['goal_index'],1)
            self.assertEqual(diag['remaining_goal_indices_not_verified'],[0])
            self.assertFalse(diag['cad_dispatched'] or diag['partial_submission'] or diag['confirmation_token_created'])
            self.assertEqual(task['phase'],'constraint_review_ready')
            engine._submit.assert_not_called()
        query={'task_id':'a'*32,'snapshot_cursor':'b'*64+':mirror_dependencies:0'}
        failure=task_failure(caught.exception.code,str(caught.exception),{**diag,'mirror_review_arguments':query},task_id='a'*32)
        self.assertIs(failure['diagnostics']['cad_dispatched'],False)
        self.assertIs(failure['diagnostics']['job_created'],False)
        self.assertEqual(failure['restoration_status'],'not_required')
        self.assertEqual(failure['next_action']['arguments'],query)


if __name__=='__main__':unittest.main()
