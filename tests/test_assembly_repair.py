import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import motion_server
from sw_mcp.bridge import CadError
from sw_mcp.conversation import assembly_repair, assembly_snapshot, core, task_progress
from sw_mcp.conversation.motion_tasks import MotionTaskEngine


class AssemblyRepairTests(unittest.TestCase):
    def setUp(self):
        self.task = {'task_id': 'a' * 32, 'task_kind': 'assembly_constraints', 'phase': 'constraint_review_ready'}
        self.session = SimpleNamespace(model='copy', folder=Path('fixture'), unknown=False,
            call=Mock(), capture_applied_result=Mock(), connection_survey={'inventory_complete': True,
                'components': [{'component_id': 'p', 'instance': 'slider'}, {'component_id': 'q', 'instance': 'base'}],
                'mates': [{'native_feature_id': 12, 'name': 'distance', 'type': 5, 'error': 0, 'suppressed': False,
                           'entities': [{'component_id': 'p'}, {'component_id': 'q'}]}]})
        self.engine = MotionTaskEngine.__new__(MotionTaskEngine)
        self.engine.tasks = {self.task['task_id']: self.task}
        self.engine.sessions = {self.task['task_id']: self.session}
        self.engine._require_session = Mock()
        self.engine._submit = Mock(side_effect=lambda task, stage, operation: operation())
        self.engine.save = Mock()
        self.requests = [{'native_feature_id': 12, 'suppressed': True}]
        self.native_plan = {'plan_id': 'native-plan', 'mate_changes': [{'native_feature_id': 12, 'name': 'distance',
            'type': 5, 'before': False, 'after': True, 'action': 'set_suppressed'}], 'mirror_features': [],
            'independent_occurrences': [], 'expected_added_mates': 0, 'motion_verified': False, 'write_dispatched': False}

    def test_standalone_mate_plan_needs_no_connection_intent_and_names_the_pair(self):
        self.session.call.return_value = self.native_plan
        with patch.object(core, 'write'):
            self.engine.plan(self.task['task_id'], mate_changes=self.requests)
        operation, = self.session.call.call_args.args
        self.assertEqual(operation, '_preview_assembly_repair')
        self.assertEqual(json.loads(self.session.call.call_args.kwargs['proposal_json']), {'mate_changes': self.native_plan['mate_changes']})
        self.assertEqual(self.task['proposal']['affected_component_pairs'][0]['components'], ['slider', 'base'])
        self.assertEqual(self.task['proposal']['expected_added_mates'], 0)
        self.assertEqual(self.task['phase'], 'awaiting_confirmation')

    def test_mirror_preview_is_separate_and_publicly_advertised(self):
        properties = next(t for t in asyncio.run(motion_server.mcp.list_tools()) if t.name == 'plan_mechanism_task').input_schema['properties']
        self.assertEqual(properties['independentize_mirrors']['type'], 'boolean')
        with self.assertRaisesRegex(core.StopBatch, 'PARAMETER_NOT_APPLICABLE'):
            self.engine.plan(self.task['task_id'], mate_changes=self.requests, independentize_mirrors=True)
        self.session.call.assert_not_called()
        self.session.call.return_value = {**self.native_plan, 'mate_changes': []}
        with patch.object(core, 'write'):
            self.engine.plan(self.task['task_id'], independentize_mirrors=True)
        self.assertTrue(self.session.call.call_args.kwargs['independentize_mirrors'])
        self.assertEqual(self.task['proposal']['task_operation'], 'independentize_mirrors')

    def test_unverified_mirror_scope_preserves_the_preexisting_plan(self):
        self.task.update(phase='awaiting_confirmation', plan_token='accepted-token', proposal={'plan_id': 'previous'})
        self.session.call.side_effect = CadError('ASSEMBLY_REPAIR_SCOPE_UNVERIFIED', 'mixed pattern')
        self.engine.plan(self.task['task_id'], independentize_mirrors=True)
        self.assertEqual(self.task['plan_token'], 'accepted-token')
        self.assertEqual(self.task['proposal']['plan_id'], 'previous')
        self.assertFalse(self.task['assembly_repair_review']['write_dispatched'])

    def test_confirmed_edit_captures_result_without_claiming_motion_verification(self):
        self.task.update(phase='awaiting_confirmation', plan_token='token',
                         proposal={**self.native_plan, 'task_operation': 'change_existing_mates'})
        with self.assertRaisesRegex(core.StopBatch, 'CONFIRMATION_REQUIRED'):
            self.engine.execute(self.task['task_id'], 'token', confirmed=True)
        self.session.call.assert_not_called()
        self.session.call.return_value = {k: True for k in ('mate_inventory_verified', 'poses_references_fixed_flags_verified',
                                                          'reopened_verified', 'source_files_unchanged')}
        self.session.call.return_value.update(added_mates=0, motion_verified=False, mate_changes=self.native_plan['mate_changes'],
                                              mirror_feature_ids=[], independent_occurrences=[])
        with patch.object(core, 'write'):
            self.engine.execute(self.task['task_id'], 'token', confirmed=True, scope_confirmed=True)
        self.session.call.assert_called_once_with('_apply_assembly_repair', plan_id='native-plan', confirmed=True)
        self.session.capture_applied_result.assert_called_once()
        self.assertFalse(self.task['verification']['motion_verified'])

    def test_unresolved_pair_is_refused_before_dispatch(self):
        self.session.connection_survey['mates'][0]['entities'][0]['component_id'] = None
        with self.assertRaisesRegex(core.StopBatch, 'MATE_CHANGE_REVIEW_REQUIRED'):
            assembly_repair.propose(self.engine, self.task, self.requests, False)
        self.session.call.assert_not_called()

    def test_batch_controls_return_separate_entry_points(self):
        task_id = self.task['task_id']
        with self.assertRaises(core.StopBatch) as raised:
            self.engine.plan(task_id, continue_verified_batch=True, assembly_sequence='continue',
                             connection_intent=[], completion_scope='whole_assembly', initial_translation_limit_mm=.002)
        self.assertEqual(raised.exception.code, 'CONNECTION_INTENT_INVALID')
        review = raised.exception.diagnostics
        self.assertEqual(set(review['conflicting_fields']), {'connection_intent','completion_scope',
            'initial_translation_limit_mm','continue_verified_batch','assembly_sequence'})
        same, layered = review['control_call_options']
        self.assertEqual(same['arguments'], {'task_id':task_id,'continue_verified_batch':True})
        self.assertIn('constraint_review_ready', same['instruction'])
        self.assertEqual(layered['arguments'], {'task_id':task_id,'assembly_sequence':'continue'})
        self.assertIn('新 task_id', layered['instruction'])
        self.session.call.assert_not_called()
        self.engine._submit.assert_not_called()

    def test_material_name_mismatch_keeps_exact_name_candidates_in_summary(self):
        details = {'requested_database':'base.sldmat','requested_material':'6061 Alloy',
                   'material_status':'no_exact_match','candidate_materials':['6061-T6 (SS)']}
        self.session.call.side_effect = CadError('PARAMETER_NOT_APPLICABLE', 'material mismatch', diagnostics={'details':details})
        assignment = {'part_file':'part.sldprt','configuration':'Default','database':'base.sldmat','material':'6061 Alloy'}
        self.engine.plan(self.task['task_id'], material_assignments=[assignment])
        self.assertEqual(self.task['phase'], 'constraint_review_ready')
        self.assertFalse(self.task.get('plan_token'))
        self.assertEqual(assembly_snapshot.summary(self.task)['material_input_review']['candidate_materials'],
                         ['6061-T6 (SS)'])

    def test_stale_motion_keeps_solver_observations_in_poll_and_summary(self):
        self.session.motion_candidate = {'component_id':'p','entity_id':'axis'}
        self.session.motion_candidates = [{'drive':self.session.motion_candidate,'reference':{'component_id':'q'}}]
        self.session.motion_signature = 'original'
        self.session.initial_inspection = {'components':[]}
        self.session.state = Mock()
        self.session.call.side_effect = lambda operation, **kwargs: {
            '_circular_reference_state': {'signature':'original'}, 'inspect_model': {'components':[]},
            'create_motion_study': {}, 'verify_motion_preservation': {'error_code':'RESULTS_STALE',
                'assertion':'inconclusive','solver_messages_status':'not_available_from_verified_native_interface'}}[operation]
        self.task.update(task_kind='motion', phase='awaiting_confirmation', plan_token='token', selected_index=0,
            motion_parameters={'motion':'linear','speed':1,'duration_s':1,'output_fps':30,'minimum_travel':.001},
            proposal={'reset_studies_before_drive':[],'direction_binding':{'native_reverse_direction':False},
                      'initial_state':'saved','pre_solve_constraint_review':{'reference_link_observed':False,
                          'reference_path_appears_only_with_observed_mirror_dependencies':True,
                          'driven_mate_island_size':12,'omitted_constraint_count':3}})
        with (patch.object(core, 'write'),
              patch('sw_mcp.conversation.motion_tasks.motion_direction_binding',
                    return_value={'native_reverse_direction':False,'expected_sign_about_selected_native_axis':1}),
              self.assertRaises(core.StopBatch) as raised):
            self.engine.execute(self.task['task_id'], 'token', confirmed=True, scope_confirmed=True)
        failure = raised.exception
        self.assertEqual(failure.code, 'RESULTS_STALE')
        self.assertEqual(failure.diagnostics['native_verification']['solver_messages_status'],
                         'not_available_from_verified_native_interface')
        context = failure.diagnostics['solver_context']
        self.assertFalse(context['solver_root_cause_proven'])
        self.assertFalse(context['automatic_constraint_change_allowed'])
        self.assertEqual(context['observations'], ['DRIVE_REFERENCE_MATE_PATH_NOT_OBSERVED',
            'REFERENCE_PATH_OBSERVED_ONLY_WITH_MIRROR_DEPENDENCIES'])
        self.assertEqual(context['omitted_constraint_count'], 3)
        self.task.update(phase='failed',error={'code':failure.code,'diagnostics':failure.diagnostics})
        self.assertEqual(assembly_snapshot.summary(self.task)['error']['solver_context'], context)
        self.assertEqual(task_progress.compact_status(self.task, None, 'test')['solver_context'], context)

    def test_progress_only_keeps_nonzero_native_exit_warning(self):
        self.task.update(phase='closed_with_cleanup_warning',closed=True,
            finish={'cleanup_status':'warning_nonzero_native_exit','native_exit':{
                'native_process_exited':True,'normal_zero_exit':False,'exit_code':1}})
        warning = task_progress.compact_status(self.task, None, 'test')['cleanup_warning']
        self.assertEqual(warning, {'cleanup_status':'warning_nonzero_native_exit',
            'native_process_exited':True,'normal_zero_exit':False,'exit_code':1})
