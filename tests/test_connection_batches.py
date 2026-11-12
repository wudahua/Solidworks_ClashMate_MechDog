import asyncio,copy,json,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import connection_batches as batches,connection_groups as groups
from sw_mcp.conversation import connection_task,core
from tests.test_assembly_connections import survey
from tests.test_assembly_constraints import component

def proposal(count=9):
    goals=[{'component_a':str(i),'component_b':'base','kind':'rigid'} for i in range(count)]
    actions=[{**g,'kind':'distance'} for g in goals]
    return {'goals':goals,'actions':actions,'fixed_state_changes':[],'group_bindings':[]}

class BatchTests(unittest.TestCase):
    def test_initial_translation_is_exactly_frozen_once_in_first_payload(self):
        p=proposal();p['initial_translation']={'entries':[{'component_id':'moving','after':[0.,0.,1e-7]}]}
        t=batches.prepare(p);first=json.loads(t['payloads'][0]);second=json.loads(t['payloads'][1])
        self.assertEqual(first['initial_translation'],p['initial_translation']);self.assertNotIn('initial_translation',second)
        p['initial_translation']['entries'][0]['after'][2]=.003
        self.assertNotEqual(json.loads(t['payloads'][0])['initial_translation'],p['initial_translation'])
    def test_nine_goals_are_two_complete_batches_not_a_raised_native_limit(self):
        p=proposal();before=copy.deepcopy(p);t=batches.prepare(p)
        self.assertEqual([b['goals'] for b in t['batches']],[8,1]);self.assertEqual(sum(b['added_mates'] for b in t['batches']),9)
        self.assertEqual([g for s in t['payloads'] for g in json.loads(s)['goals']],p['goals']);self.assertEqual(p,before)
        self.assertTrue(t['all_or_restore_import_checkpoint']);self.assertFalse(t['execute_replay_allowed'])

    def test_payload_hash_binds_exact_non_ascii_json_bytes(self):
        p=proposal();p['goals'][0]['instance_a']='长轴-1';t=batches.prepare(p);r=batches.request(t,0,'state_'+'0'*24)
        self.assertIn('长轴-1',r['batch_payload_json']);self.assertEqual(r['batch_transaction']['batch_index'],0)
        t['payloads'][0]+=' '
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):batches.request(t,0,'state_'+'0'*24)

    def test_unrelated_actions_cannot_be_dropped_while_partitioning(self):
        p=proposal();p['actions'].append({'component_a':'foreign','component_b':'base'})
        with self.assertRaisesRegex(ValueError,'action_outside'):batches.prepare(p)

    def test_circular_query_signature_cannot_be_used_for_later_mate_preview(self):
        t=batches.prepare(proposal())
        for signature in ['query_'+'0'*24,'state_invalid',None,True]:
            with self.assertRaisesRegex(ValueError,'signature_domain_required'):batches.request(t,1,signature)

    def test_duplicate_goal_pair_and_reversed_pair_are_refused(self):
        p=proposal(2);p['goals'][1]={'component_a':'base','component_b':'0','kind':'rigid'}
        with self.assertRaisesRegex(ValueError,'duplicate_transaction_goal_pair'):batches.prepare(p)

    def test_overall_budget_refuses_whole_transaction(self):
        for p in [proposal(129),{**proposal(1),'actions':proposal(1)['actions']*513}]:
            with self.assertRaisesRegex(ValueError,'transaction_budget'):batches.prepare(p)

    def test_fixed_release_is_assigned_once_to_its_executable_batch(self):
        p=proposal();p['fixed_state_changes']=[{'component_id':'8','instance':'8','before':True,'after':False}];t=batches.prepare(p)
        self.assertEqual(json.loads(t['payloads'][0])['fixed_state_changes'],[])
        self.assertEqual(json.loads(t['payloads'][1])['fixed_state_changes'],p['fixed_state_changes'])

    def test_fixed_release_without_executable_goal_is_not_silently_ignored(self):
        p=proposal();p['fixed_state_changes']=[{'component_id':'foreign'}]
        with self.assertRaisesRegex(ValueError,'without_executable'):batches.prepare(p)

    def test_legacy_scope_still_rejects_nine_goals(self):
        s=SimpleNamespace(connection_survey=survey())
        with self.assertRaises(core.StopBatch):connection_task.resolve(s,[{'component_a':'moving','component_b':'body','kind':'rigid'}]*9)

    def test_whole_scope_cannot_prepare_with_an_omitted_fixed_accessory(self):
        from pathlib import Path
        s=survey();s['components'].append(component('omitted',True))
        with patch.object(connection_task.core,'write'):
            session=SimpleNamespace(folder=Path('not_created_in_readonly_test'),connection_survey=s,call=Mock())
            engine=SimpleNamespace(_require_session=Mock(),sessions={'a':session});t={'task_id':'a','phase':'constraint_review_ready'}
            r=connection_task.propose(engine,t,[{'component_a':'moving','component_b':'body','kind':'revolute'}],completion_scope='whole_assembly')
            self.assertEqual(r['status'],'assembly_goal_coverage_required');self.assertEqual(r['component_coverage']['unassigned_components'],['omitted'])
            self.assertFalse(r['confirmation_token_created']);session.call.assert_not_called()

    def test_large_groups_require_explicit_whole_scope(self):
        s=survey();s['components'] += [component('part'+str(i)) for i in range(32)]
        raw=[{'name':'rigid','members':[c['instance'] for c in s['components']]}]
        with self.assertRaises(groups.GroupIntentError):groups.expand(s,[],raw)
        e=groups.expand(s,[],raw,whole_assembly=True);self.assertEqual(e['status'],'group_expanded');self.assertEqual(len(e['goals']),33)

    def test_pattern_member_is_preserved_only_with_observed_seeds_in_same_group(self):
        s=survey();s['components'].append(component('pattern'))
        s['structural_relations']={'components':[{'component_id':'pattern','instance':'pattern','is_pattern_instance':True,'native_feature_id':21,'parent_features':[{'native_feature_id':20}]}],
            'patterns':[{'native_feature_id':20,'suppressed':False,'seed_component_ids':['moving'],'child_features':[{'native_feature_id':21}]}]}
        raw=[{'name':'group','members':['body','moving','pattern'],'anchor':'body'}]
        e=groups.expand(s,[],raw,whole_assembly=True)
        self.assertFalse(any(g['component_a']=='pattern' for g in e['goals']));self.assertTrue(any(g['component_a']=='pattern' for g in e['group_bindings']))
        s['structural_relations']['patterns'][0]['seed_component_ids']=['foreign']
        with self.assertRaisesRegex(groups.GroupIntentError,'seed_group_scope'):groups.expand(s,[],raw,whole_assembly=True)

    def test_releasing_already_rigid_member_still_has_an_executable_state_change(self):
        from tests.test_assembly_constraints import mate
        s=survey([mate(1,'body','moving','lock')]);s['components'][1]['fixed_component']=True
        e=groups.expand(s,[],[{'name':'g','members':['body','moving']}],['moving'])
        self.assertEqual(e['status'],'group_expanded');self.assertEqual(len(e['goals']),1)

    def test_native_full_rigid_observation_preserves_unmodelled_constraints_without_adding_a_mate(self):
        from sw_mcp import assembly_connections as j
        from tests.test_assembly_constraints import mate
        s=survey([mate(1,'body','moving','cylindrical_axis')]);s['components'][1]['constraint_state']={'status':'observed','fully_constrained':True}
        goal=[{'component_a':'moving','component_b':'body','kind':'rigid'}]
        with self.assertRaisesRegex(ValueError,'native_full_constraint_conflicts'):j.plan(s,goal)
        p=j.plan(s,goal,whole_assembly=True)
        self.assertEqual(p['status'],'plan_ready');self.assertEqual(p['actions'],[])
        self.assertTrue(p['goals'][0]['preserved_native_full_constraint_observation'])
        self.assertGreater(p['goals'][0]['remaining_supported_constraints'],0)
        self.assertFalse(p['goals'][0]['supported_target_fulfilment_certified']);self.assertFalse(p['motion_verified'])

    def test_public_whole_scope_is_closed_enum_and_does_not_create_another_tool(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={'a'*32:{}},plan=Mock(return_value={'accepted':True}))
        with patch.object(server,'_task_engine',engine):
            r=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'completion_scope':'whole_assembly'}))
        self.assertFalse(r.is_error);self.assertEqual(engine.plan.call_args.args[-1],'whole_assembly')
        for v in [True,'whole',1]:
            with patch.object(server,'_task_engine',engine):r=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':'a'*32,'completion_scope':v}))
            self.assertTrue(r.is_error)
        self.assertEqual(len(asyncio.run(server.mcp.list_tools())),30)

if __name__=='__main__':unittest.main()
