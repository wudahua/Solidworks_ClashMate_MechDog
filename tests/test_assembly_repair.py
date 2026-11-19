import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import motion_server
from sw_mcp.bridge import CadError
from sw_mcp.conversation import assembly_repair, core
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
