import copy,unittest,tempfile,pathlib,asyncio
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import connection_layers as layers

def observation(name='转子组-1',**changes):
    return dict(instance=name,document_path='copy/rotor.SLDASM',configuration='Default',native_rigid=True,
                shared_document_instances=1,internal_direct_components=3,internal_fixed_components=1,
                internal_mates=0,scope_selectable=True,refusal_reason=None,**changes)

def catalog(*rows):return layers.catalog({'inventory_complete':True,'layers':list(rows),'root_assembly_path':'copy/root.SLDASM'})

class LayerTests(unittest.TestCase):
    def test_rigid_mode_never_certifies_internal_completeness(self):
        result=catalog(observation());self.assertFalse(result['all_layers_completed'])
        self.assertFalse(result['layers'][0]['internal_completeness_certified'])
        self.assertFalse(result['mechanical_intent_inferred'])
    def test_one_unique_layer_is_recommended_without_user_copying_path(self):
        result=catalog(observation());self.assertEqual(result['recommended_scope_instance'],'转子组-1')
        selected,question=layers.resolve(result,'转子组');self.assertIsNone(question);self.assertEqual(selected['instance'],'转子组-1')
    def test_multiple_mechanical_layers_are_not_silently_chosen(self):
        result=catalog(observation('转子组-1'),observation('转子组-2'))
        self.assertIsNone(result['recommended_scope_instance']);selected,q=layers.resolve(result,'转子组')
        self.assertIsNone(selected);self.assertEqual(len(q['choices']),2);self.assertFalse(q['write_dispatched'])
    def test_exact_instance_wins_over_partial_name(self):
        selected,q=layers.resolve(catalog(observation('组-1'),observation('组-10')),'组-1')
        self.assertIsNone(q);self.assertEqual(selected['instance'],'组-1')
    def test_missing_hint_returns_candidates_instead_of_guessing(self):
        selected,q=layers.resolve(catalog(observation()),'不存在');self.assertIsNone(selected)
        self.assertEqual(q['field'],'assembly_scope_hint');self.assertEqual(len(q['choices']),1)
    def test_shared_documents_are_not_admitted_even_when_native_rigid(self):
        row=observation();row.update(shared_document_instances=2,scope_selectable=False,refusal_reason='shared_document_requires_multi_instance_policy')
        result=catalog(row);self.assertIsNone(result['recommended_scope_instance'])
        with self.assertRaisesRegex(ValueError,'shared_document'):layers.resolve(result,'转子组')
        row['scope_selectable']=True
        with self.assertRaisesRegex(ValueError,'shared_or_flexible'):catalog(row)
    def test_flexible_flag_cannot_be_promoted_to_selectable(self):
        row=observation();row['native_rigid']=False
        with self.assertRaisesRegex(ValueError,'shared_or_flexible'):catalog(row)
    def test_incomplete_inventory_is_refused(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):layers.catalog({'inventory_complete':False,'layers':[]})
    def test_count_types_and_negative_values_are_not_coerced(self):
        for key in ('internal_direct_components','internal_fixed_components','internal_mates','shared_document_instances'):
            for value in (True,-1,None,'1'):
                row=observation();row[key]=value
                with self.assertRaisesRegex(ValueError,'observation'):catalog(row)
    def test_duplicate_or_missing_instances_are_refused(self):
        with self.assertRaisesRegex(ValueError,'instance'):catalog(observation(),observation())
        row=observation();row['instance']=''
        with self.assertRaisesRegex(ValueError,'instance'):catalog(row)
    def test_native_admission_must_be_a_boolean(self):
        row=observation();row['scope_selectable']=1
        with self.assertRaisesRegex(ValueError,'admission'):catalog(row)
    def test_catalog_never_mutates_native_evidence(self):
        row=observation();before=copy.deepcopy(row);catalog(row);self.assertEqual(row,before)
    def test_counts_do_not_infer_missing_mates_or_stationary_ownership(self):
        row=observation();row.update(internal_mates=100,internal_fixed_components=0)
        result=catalog(row)['layers'][0];self.assertFalse(result['internal_completeness_certified'])
        self.assertTrue(result['floating_observation_does_not_prove_missing_mates'])
    def test_invalid_hint_is_refused(self):
        for hint in (None,True,'',' '*3,'a'*257):
            with self.assertRaisesRegex(ValueError,'hint'):layers.resolve(catalog(observation()),hint)

class ScopeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.session=SimpleNamespace(folder=pathlib.Path(self.temp.name),model='user_'+'a'*32,
            connection_survey={'components':[]},assembly_layers=catalog(observation()),call=Mock())
        self.task={'task_id':'a'*32,'phase':'constraint_review_ready'}
        self.engine=SimpleNamespace(sessions={self.task['task_id']:self.session},_require_session=Mock(),save=Mock(),
                                    _submit=Mock(return_value={'accepted':True}))

    def test_scope_selection_is_scheduled_and_never_calls_native_on_dispatch_thread(self):
        from sw_mcp.conversation import connection_task
        reply=connection_task.propose(self.engine,self.task,None,assembly_scope_hint='转子组')
        self.assertTrue(reply['accepted']);self.session.call.assert_not_called()
        self.assertEqual(self.engine._submit.call_args.args[1],'selecting_assembly_layer')

    def test_mixed_outer_goals_and_scope_selection_are_rejected_without_losing_confirmation(self):
        from sw_mcp.conversation import connection_task,core
        self.task.update(phase='awaiting_confirmation',plan_token='retain')
        with self.assertRaises(core.StopBatch) as caught:
            connection_task.propose(self.engine,self.task,[],assembly_scope_hint='转子组')
        self.assertEqual(caught.exception.code,'CONNECTION_INTENT_INVALID')
        self.assertEqual(self.task['plan_token'],'retain');self.session.call.assert_not_called()

    def test_ambiguous_scope_does_not_revoke_existing_plan_or_dispatch(self):
        from sw_mcp.conversation import connection_task
        self.session.assembly_layers=catalog(observation('组-1'),observation('组-2'))
        self.task.update(phase='awaiting_confirmation',plan_token='retain')
        result=connection_task.propose(self.engine,self.task,None,assembly_scope_hint='组')
        self.assertTrue(result['needs_mechanical_clarification']);self.assertEqual(self.task['plan_token'],'retain')
        self.engine._submit.assert_not_called();self.session.call.assert_not_called()

    def test_scope_change_revokes_previous_outer_confirmation_before_scheduling(self):
        from sw_mcp.conversation import connection_task
        self.task.update(phase='awaiting_confirmation',plan_token='outer',proposal={'plan_id':'old'})
        connection_task.propose(self.engine,self.task,None,assembly_scope_hint='转子组')
        self.assertNotIn('plan_token',self.task);self.assertNotIn('proposal',self.task)
        self.assertTrue(self.task['plan_token_revoked']);self.engine.save.assert_called()
        self.session.call.assert_not_called()

    def test_scoped_checkpoint_and_survey_are_bound_only_after_native_selection(self):
        from sw_mcp.conversation import connection_task
        selected={'selected_instance':'转子组-1','selected_assembly_path':'copy/rotor.SLDASM','full_import_file_count':5}
        self.session.call.side_effect=[selected,{'checkpoint_id':'b'*32},{'components':[],'mates':[]}]
        connection_task.propose(self.engine,self.task,None,assembly_scope_hint='转子组')
        operation=self.engine._submit.call_args.args[2]
        with patch.object(connection_task,'discover',return_value={'new':'survey'}) as discover,patch.object(connection_task,'publish_review',side_effect=lambda *a:self.task.update(next_action={'instruction':'plan'})) as publish:
            operation();discover.assert_called_once_with(self.session);publish.assert_called_once()
        self.assertEqual(self.session.checkpoint,'b'*32);self.assertEqual(self.task['selected_assembly_layer']['selected_instance'],selected['selected_instance'])
        self.assertEqual(self.task['selected_assembly_layer']['scope_import_checkpoint_id'],'b'*32)
        self.assertTrue(self.task['selected_assembly_layer']['scope_checkpoint_includes_all_import_files'])
        self.assertTrue((self.session.folder/'根装配原始调查.json').exists())
        self.assertEqual(self.session.call.call_args_list[0].args[0],'_select_connection_layer')
        self.assertEqual(self.session.call.call_args_list[1].args[0],'create_model_checkpoint')
        self.assertEqual(self.session.call.call_args_list[2].args[0],'inspect_model')
        self.assertEqual(self.session.initial_inspection,{'components':[],'mates':[]})

    def test_active_internal_document_is_not_silently_changed_again(self):
        from sw_mcp.conversation import connection_task,core
        self.session.selected_assembly_layer={'selected_instance':'转子组-1'}
        with self.assertRaises(core.StopBatch) as caught:
            connection_task.propose(self.engine,self.task,None,assembly_scope_hint='其他层')
        self.assertEqual(caught.exception.code,'CONNECTION_SCOPE_UNSUPPORTED');self.session.call.assert_not_called()

    def test_geometry_discovery_failure_keeps_inner_checkpoint_and_inner_comparison_frame(self):
        from sw_mcp.conversation import connection_task,core
        root={'components':[{'instance':'outer'}],'mates':[]}
        inner={'components':[{'instance':'shaft'},{'instance':'gear'}],'mates':[{'id':1}]}
        self.session.initial_inspection=root;self.session.checkpoint='root-cp'
        selected={'selected_instance':'转子组-1','selected_assembly_path':'copy/rotor.SLDASM'}
        self.session.call.side_effect=[selected,{'checkpoint_id':'b'*32},inner]
        connection_task.propose(self.engine,self.task,None,assembly_scope_hint='转子组')
        with patch.object(connection_task,'discover',side_effect=core.StopBatch('CONNECTION_PLAN_STALE')):
            with self.assertRaises(core.StopBatch):self.engine._submit.call_args.args[2]()
        self.assertIs(self.session.initial_inspection,inner)
        self.assertEqual(self.session.checkpoint,'b'*32)
        self.assertEqual(self.task['selected_assembly_layer']['scope_import_checkpoint_id'],'b'*32)
        self.assertIs(self.session.root_connection_survey,self.session.connection_survey)

    def test_inspection_failure_does_not_commit_child_checkpoint_with_root_frame(self):
        from sw_mcp.conversation import connection_task,core
        root={'components':[{'instance':'outer'}],'mates':[]}
        self.session.initial_inspection=root;self.session.checkpoint='root-cp'
        self.session.call.side_effect=[{'selected_instance':'转子组-1'},{'checkpoint_id':'b'*32},core.StopBatch('CAD_QUERY_FAILED')]
        connection_task.propose(self.engine,self.task,None,assembly_scope_hint='转子组')
        with self.assertRaises(core.StopBatch):self.engine._submit.call_args.args[2]()
        self.assertIs(self.session.initial_inspection,root);self.assertEqual(self.session.checkpoint,'root-cp')
        self.assertFalse(hasattr(self.session,'selected_assembly_layer'))

    def test_scope_parameter_is_rejected_for_motion_tasks_before_native_calls(self):
        from sw_mcp.conversation.motion_tasks import MotionTaskEngine
        from sw_mcp.conversation import core
        engine=SimpleNamespace(tasks={'a'*32:{'task_kind':'motion'}})
        with self.assertRaises(core.StopBatch) as caught:MotionTaskEngine.plan(engine,'a'*32,assembly_scope_hint='转子组')
        self.assertEqual(caught.exception.code,'CONNECTION_INTENT_INVALID')

    def test_formal_schema_keeps_thirty_tools_and_forwards_scope_as_keyword(self):
        import motion_server as server
        task='a'*32;engine=SimpleNamespace(tasks={task:{}},plan=Mock(return_value={'accepted':True}))
        with patch.object(server,'_task_engine',engine):
            result=asyncio.run(server.mcp.call_tool('plan_mechanism_task',{'task_id':task,'assembly_scope_hint':'转子组-1'}))
        self.assertFalse(result.is_error,result);self.assertEqual(engine.plan.call_args.kwargs['assembly_scope_hint'],'转子组-1')
        self.assertEqual(len(asyncio.run(server.mcp.list_tools())),30)

class KeptSourceContractTests(unittest.TestCase):
    def setUp(self):
        from tests.basic_connections_native import kept_source_admission
        self.admit=kept_source_admission;self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=pathlib.Path(self.temp.name);session=self.folder/'session';session.mkdir()
        (session/'exit-control.json').write_text('{"ok":true,"result":{"exit_requested":true}}',encoding='utf-8')
        (session/'exit-control.stages.jsonl').write_text(
            '{"stage":"closed_document_inventory","evidence":{"document_count":0}}\n'
            '{"stage":"after_ExitApp_returned","evidence":{}}\n',encoding='utf-8')
        self.record={'directory':str(self.folder),'closed':True,'verification':{'declared_scope_passed':True},'finish':{
            'restoration_status':'not_requested_result_preserved','next_round_allowed':True,'source_files_unchanged':True,
            'cleanup_status':'warning_nonzero_native_exit','native_exit':{'native_process_exited':True,'force_kill':False,
                'exit_code':123,'normal_zero_exit':False,'helper_exit_code':0},
            'executor_exit':{'confirmed':True,'executor_exit_code':0,'force_kill':False}}}
    def test_known_warning_is_preserved_and_never_reclassified_as_normal_exit(self):
        result=self.admit(self.record);self.assertTrue(result['native_exit_warning'])
        self.assertFalse(result['normal_zero_exit_certified']);self.assertEqual(result['nonzero_exit_cause'],'not_proven')
    def test_zero_exit_is_separately_identified(self):
        self.record['finish'].update(cleanup_status='pass')
        self.record['finish']['native_exit'].update(exit_code=0,normal_zero_exit=True)
        result=self.admit(self.record);self.assertFalse(result['native_exit_warning']);self.assertTrue(result['normal_zero_exit_certified'])
    def test_pending_or_forced_resource_cannot_be_reused(self):
        for field in ('native_process_exited','force_kill'):
            record=copy.deepcopy(self.record);record['finish']['native_exit'][field]=field=='force_kill'
            with self.assertRaises(AssertionError):self.admit(record)
        record=copy.deepcopy(self.record);record['finish']['executor_exit']['confirmed']=False
        with self.assertRaises(AssertionError):self.admit(record)
    def test_changed_source_or_unverified_task_cannot_be_reused(self):
        record=copy.deepcopy(self.record);record['finish']['source_files_unchanged']=False
        with self.assertRaises(AssertionError):self.admit(record)
        record=copy.deepcopy(self.record);record['verification']['declared_scope_passed']=False
        with self.assertRaises(AssertionError):self.admit(record)
    def test_missing_empty_document_or_exit_request_evidence_refuses_warning(self):
        (self.folder/'session/exit-control.stages.jsonl').write_text('{"stage":"after_ExitApp_returned","evidence":{}}\n',encoding='utf-8')
        with self.assertRaises(AssertionError):self.admit(self.record)
    def test_warning_cannot_be_hidden_by_setting_cleanup_pass(self):
        self.record['finish']['cleanup_status']='pass'
        with self.assertRaises(AssertionError):self.admit(self.record)

if __name__=='__main__':unittest.main()
