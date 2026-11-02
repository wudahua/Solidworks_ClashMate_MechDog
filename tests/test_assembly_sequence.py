"""Sequence ownership, saved-copy binding, scope admission and no write replay."""
import copy
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from sw_mcp.conversation import assembly_sequence as seq, core


def layer(name, selectable=True):
    return {'instance': name, 'configuration': 'Default', 'scope_selectable': selectable,
            'shared_document_instances': 1 if selectable else 2,
            'refusal_reason': None if selectable else 'shared_document_requires_multi_instance_policy'}


class SchedulingTests(unittest.TestCase):
    def test_descendants_precede_parents_and_root_is_last(self):
        value = seq.schedule({'inventory_complete': True, 'layers': [layer('A-1'), layer('B-1'), layer('A-1/C-1')]})
        self.assertEqual([r['instance'] for r in value['steps']], ['A-1/C-1', 'A-1', 'B-1', '$root'])
        self.assertFalse(value['mechanical_intent_inferred'])
        self.assertFalse(value['atomic_all_layer_rollback'])

    def test_unsupported_layer_is_reported_never_silently_completed(self):
        value = seq.schedule({'inventory_complete': True, 'layers': [layer('shared-1', False)]})
        self.assertEqual([r['instance'] for r in value['steps']], ['$root'])
        self.assertEqual(value['unsupported_layers'][0]['instance'], 'shared-1')

    def test_empty_catalog_still_checks_root(self):
        self.assertEqual(seq.schedule({'inventory_complete': True, 'layers': []})['steps'][0]['instance'], '$root')

    def test_incomplete_duplicate_and_budget_do_not_create_partial_queue(self):
        for catalog in ({'inventory_complete': False, 'layers': []},
                        {'inventory_complete': True, 'layers': [layer('A'), layer('A')]},
                        {'inventory_complete': True, 'layers': [layer(str(i)) for i in range(33)]}):
            with self.assertRaises(ValueError): seq.schedule(catalog)

    def test_scope_matching_requires_original_configuration_and_unique_admission(self):
        expected = {'instance': 'A', 'configuration': 'Default', 'shared_document_instances': 1}
        for changed in ({'configuration': 'Other'}, {'shared_document_instances': 2}, {'scope_selectable': False}):
            row = layer('A'); row.update(changed)
            with self.assertRaises(core.StopBatch): seq._scope_row({'layers': [row]}, expected)
        self.assertEqual(seq._scope_row({'layers': [layer('A')]}, expected)['instance'], 'A')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / 'source.SLDASM'; self.source.write_bytes(b'original')
        self.copy_root = self.root / 'rt/experiments/user_assemblies' / ('b' * 32) / 'files'
        self.copy_root.mkdir(parents=True)
        self.result = self.copy_root / 'root.SLDASM'; self.result.write_bytes(b'kept root')
        self.part = self.copy_root / 'part.SLDPRT'; self.part.write_bytes(b'unchanged part')
        self.sid = 'c' * 32; self.tid = 'a' * 32
        self.task = {'task_id': self.tid, 'directory': str(self.root / 'task'), 'source': str(self.source),
                     'phase': 'constraint_review_ready', 'task_kind': 'assembly_constraints', 'busy': False, 'closed': False,
                     'source_dependency_hashes': {str(self.source): core.digest(self.source)}}
        self.session = SimpleNamespace(assembly_layers={'inventory_complete': True, 'layers': [layer('A')]})
        self.engine = SimpleNamespace(work=self.root, sessions={self.tid: self.session}, tasks={self.tid: self.task},
                                      _require_session=Mock(), _submit=Mock(return_value={'accepted': True}), save=Mock(),
                                      prepare=Mock(return_value={'accepted': True}), continuation_gate=Mock())
        self.value = {**seq.schedule(self.session.assembly_layers), 'sequence_id': self.sid, 'current_step': 0,
                      'status': 'reviewing_layer', 'original_source': str(self.source),
                      'original_inputs': {str(self.source): core.digest(self.source)}, 'last_verified_result': None,
                      'native_exit_warnings': [], 'all_layers_completed': False, 'all_supported_documents_completed': False}
        self.value['steps'][0].update(task_id=self.tid, status='reviewing')
        self.task.update(assembly_sequence_id=self.sid, assembly_sequence_step=0)
        seq._save(self.engine, self.value)

    def keep(self, exit_code=0):
        self.task.update(closed=True, phase='closed', verification={'declared_scope_passed': True, 'completed_trials': 6},
                         finish={'native_exit': {'native_process_exited': True, 'exit_code': exit_code,
                                                'normal_zero_exit': exit_code == 0, 'force_kill': False},
                                 'executor_exit': {'confirmed': True, 'executor_exit_code': 0, 'force_kill': False},
                                 'restoration_status': 'not_requested_result_preserved', 'next_round_allowed': True,
                                 'source_files_unchanged': True, 'result_assembly_path': str(self.result),
                                 'result_assembly_sha256': core.digest(self.result)})
        folder = pathlib.Path(self.task['directory']) / 'session'
        core.write(folder / '导入.json', {'model_id': 'user_' + 'b' * 32, 'path': str(self.result), 'file_count': 2})
        core.write(folder / '活会话归属.json', {'runtime': str(self.root / 'rt')})
        core.write(self.copy_root.parent / 'import-evidence.json', {'copy_paths': [str(self.result), str(self.part)]})

    def test_start_binds_before_worker_and_does_not_write_native(self):
        self.task.pop('assembly_sequence_id'); self.task.pop('assembly_sequence_step')
        result = seq.start(self.engine, self.task)
        self.assertTrue(result['accepted'])
        value, i = seq._load(self.engine, self.task)
        self.assertEqual(i, 0); self.assertEqual(value['steps'][0]['task_id'], self.tid)
        self.engine.prepare.assert_not_called()

    def test_start_refuses_reusing_selected_or_executed_scope(self):
        for key, val in (('assembly_sequence_id', self.sid), ('execution_consumed', True)):
            self.task.pop('assembly_sequence_id', None); self.task[key] = val
            with self.assertRaises(core.StopBatch): seq.start(self.engine, self.task)
            self.task.pop(key)
        self.session.selected_assembly_layer = {'selected_instance': 'A'}
        with self.assertRaises(core.StopBatch): seq.start(self.engine, self.task)
        self.engine._submit.assert_not_called()

    def test_after_prepare_uses_frozen_scope_on_worker(self):
        self.task['next_action'] = {'instruction': 'plan'}
        with patch('sw_mcp.conversation.connection_task.select_scope') as selected:
            seq.after_prepare(self.engine, self.task, self.session)
        selected.assert_called_once(); self.assertIn('1/2', self.task['next_action']['instruction'])

    def test_root_step_never_calls_select_internal(self):
        self.value['steps'][0]['instance'] = '$root'; seq._save(self.engine, self.value)
        self.task['next_action'] = {'instruction': 'plan'};self.task['phase']='selecting_assembly_layer'
        with patch('sw_mcp.conversation.connection_task.select_scope') as selected:
            seq.after_prepare(self.engine, self.task, self.session)
        selected.assert_not_called();self.assertEqual(self.task['phase'],'constraint_review_ready')

    def test_verified_keep_binds_all_registered_files_and_exposes_continuation(self):
        self.keep(); seq.closed(self.engine, self.task)
        value, _ = seq._load(self.engine, self.task)
        self.assertEqual(value['status'], 'ready_to_continue')
        self.assertEqual(set(value['steps'][0]['result_inputs']), {str(self.result), str(self.part)})
        self.assertEqual(self.task['next_action']['arguments']['assembly_sequence'], 'continue')
        seq.advance(self.engine, self.task)
        self.engine.continuation_gate.assert_called_once()
        self.engine.prepare.assert_called_once_with(str(self.result), task_kind='assembly_constraints', _sequence_binding=(self.sid, 1))

    def test_cleanup_nonzero_is_preserved_as_warning_not_zero(self):
        self.keep(91); seq.closed(self.engine, self.task)
        value, _ = seq._load(self.engine, self.task)
        self.assertEqual(value['native_exit_warnings'][0]['exit_code'], 91)
        self.assertFalse(self.task['finish']['native_exit']['normal_zero_exit'])

    def test_unconfirmed_forced_or_failed_native_cannot_advance(self):
        for kind, key, val in (('native_exit', 'native_process_exited', False), ('native_exit', 'force_kill', True),
                               ('executor_exit', 'confirmed', False), ('executor_exit', 'executor_exit_code', 3)):
            self.keep(); self.task['finish'][kind][key] = val
            with self.assertRaises(core.StopBatch): seq._result_inputs(self.task)

    def test_lost_evidence_retains_closed_state_and_blocks_sequence(self):
        self.keep(); (self.copy_root.parent / 'import-evidence.json').unlink()
        seq.closed(self.engine, self.task)
        self.assertTrue(self.task['closed'])
        self.assertEqual(seq.view(self.engine, self.task)['status'], 'blocked_after_close')
        with self.assertRaises(core.StopBatch): seq.advance(self.engine, self.task)
        self.engine.prepare.assert_not_called()

    def test_missing_copy_inventory_does_not_fallback_to_folder_scan(self):
        self.keep(); core.write(self.copy_root.parent / 'import-evidence.json', {})
        with self.assertRaises(core.StopBatch): seq._result_inputs(self.task)

    def test_duplicate_or_outside_paths_are_refused(self):
        self.keep()
        for rows in ([str(self.result), str(self.result)], [str(self.result), str(self.source)]):
            core.write(self.copy_root.parent / 'import-evidence.json', {'copy_paths': rows})
            with self.assertRaises((core.StopBatch, ValueError)): seq._result_inputs(self.task)

    def test_each_dependency_is_rechecked_before_lease_or_new_task(self):
        self.keep(); seq.closed(self.engine, self.task); self.part.write_bytes(b'tampered')
        with self.assertRaises(core.StopBatch) as caught: seq.advance(self.engine, self.task)
        self.assertEqual(caught.exception.code, 'SOURCE_CHANGED')
        self.engine.continuation_gate.assert_not_called(); self.engine.prepare.assert_not_called()

    def test_original_inputs_are_rechecked_between_layers(self):
        self.keep(); seq.closed(self.engine, self.task); self.source.write_bytes(b'changed original')
        with self.assertRaises(core.StopBatch): seq.advance(self.engine, self.task)
        self.engine.prepare.assert_not_called()

    def test_repeated_continue_returns_existing_next_without_dispatch(self):
        self.keep(); seq.closed(self.engine, self.task)
        value, _ = seq._load(self.engine, self.task)
        value['steps'][1]['task_id'] = 'd' * 32; value['current_step'] = 1; seq._save(self.engine, value)
        self.engine.tasks['d'*32]={'assembly_sequence_id':self.sid,'assembly_sequence_step':1}
        result = seq.advance(self.engine, self.task)
        self.assertEqual(result['task_id'], 'd' * 32)
        self.assertFalse(result['replayed']); self.engine.prepare.assert_not_called()

    def test_restore_current_does_not_erase_previous_successes_or_claim_global_undo(self):
        self.task.update(closed=True, finish={'restoration_status': 'restored'})
        self.value['last_verified_result'] = 'earlier-kept-copy'; seq._save(self.engine, self.value)
        seq.closed(self.engine, self.task)
        value, _ = seq._load(self.engine, self.task)
        self.assertEqual(value['status'], 'stopped_current_layer_restored')
        self.assertEqual(value['last_verified_result'], 'earlier-kept-copy')
        with self.assertRaises(core.StopBatch): seq.advance(self.engine, self.task)

    def test_stop_does_not_close_or_modify_native_session(self):
        result = seq.stop(self.engine, self.task)
        self.assertFalse(result['native_calls']); self.assertFalse(self.task['closed'])
        self.assertEqual(result['assembly_sequence']['status'], 'stopped_by_request')

    def test_stop_is_not_canceled_by_subsequent_keep(self):
        seq.stop(self.engine, self.task); self.keep(); seq.closed(self.engine, self.task)
        self.assertEqual(seq.view(self.engine, self.task)['status'], 'stopped_by_request')
        with self.assertRaises(core.StopBatch): seq.advance(self.engine, self.task)

    def test_end_reports_supported_and_all_layer_completion_separately(self):
        self.keep(); self.value['steps'] = [self.value['steps'][0]]
        self.value['unsupported_layers'] = [{'instance': 'shared', 'reason': 'shared_document'}]
        seq._save(self.engine, self.value); seq.closed(self.engine, self.task)
        value, _ = seq._load(self.engine, self.task)
        self.assertTrue(value['all_supported_documents_completed']); self.assertFalse(value['all_layers_completed'])
        self.assertEqual(value['status'], 'partial_unsupported_layers')

    def test_task_binding_cannot_change_current_index_or_task(self):
        self.task['assembly_sequence_step'] = 1
        with self.assertRaises(core.StopBatch): seq.view(self.engine, self.task)

    def test_new_binding_rejects_wrong_source_and_skip(self):
        self.keep(); seq.closed(self.engine, self.task)
        child = {'task_id': 'd' * 32, 'source': 'different-copy'}
        with self.assertRaises(core.StopBatch): seq.bind_new(self.engine, child, (self.sid, 1))
        child['source'] = str(self.result)
        seq.bind_new(self.engine, child, (self.sid, 1))
        self.assertEqual(child['assembly_sequence_step'], 1)
        self.assertEqual(seq.view(self.engine, child)['current_step'], 1)

    def test_registered_next_task_without_matching_record_is_not_recreated(self):
        self.keep();seq.closed(self.engine,self.task)
        value,_=seq._load(self.engine,self.task);value['steps'][1]['task_id']='d'*32;seq._save(self.engine,value)
        with self.assertRaises(core.StopBatch):seq.advance(self.engine,self.task)
        self.engine.prepare.assert_not_called()

    def test_scoped_verification_does_not_claim_complete_component_coverage(self):
        self.keep();self.value['steps']=[self.value['steps'][0]];seq._save(self.engine,self.value)
        seq.closed(self.engine,self.task);value,_=seq._load(self.engine,self.task)
        self.assertTrue(value['all_supported_documents_completed']);self.assertFalse(value['all_layers_completed'])

    def test_summary_retains_step_status_without_repeating_all_dependency_hashes(self):
        self.keep();seq.closed(self.engine,self.task);view=seq.view(self.engine,self.task)
        self.assertEqual(view['steps'][0]['bound_result_file_count'],2)
        self.assertNotIn('result_inputs',view['steps'][0]);self.assertNotIn('original_inputs',view)

    def test_current_failure_is_visible_without_mutating_persisted_history(self):
        self.task.update(phase='failed',error={'code':'CAD_TIMEOUT'})
        value=seq.view(self.engine,self.task);self.assertEqual(value['status'],'blocked_current_layer')
        self.assertEqual(value['current_failure_code'],'CAD_TIMEOUT')
        persisted,_=seq._load(self.engine,self.task);self.assertEqual(persisted['status'],'reviewing_layer')


if __name__ == '__main__': unittest.main()
