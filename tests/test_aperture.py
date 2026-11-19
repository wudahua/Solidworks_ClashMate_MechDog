from pathlib import Path
from types import SimpleNamespace
import asyncio
import unittest
from unittest.mock import Mock, patch

from sw_mcp.conversation import aperture, core


def sample(frame, stroke, gaps, collisions=None):
    return {'frame': frame, 'time_s': frame / 10, 'input_mm': stroke, 'gaps_mm': gaps,
            'tip_radii_mm': dict.fromkeys(('a', 'b', 'c', 'd'), gaps[0] / 2), 'interferences_mm3': collisions or {}}


class ApertureTests(unittest.TestCase):
    def setUp(self):
        self.session = SimpleNamespace(model='model', folder=Path('test-not-written'), state=Mock(), call=Mock())
        self.proposal = {'aperture_validation': {'target_openings_mm': [30, 40], 'scope': 'test'},
                         'direction_binding': {'native_reverse_direction': False, 'expected_sign_about_selected_native_axis': 1}}
        self.drive = {'component_id': 'drive', 'entity_id': 'face', 'axis_global': [0, 0, 1]}
        self.reference = {'component_id': 'support'}

    def test_targets_are_both_required_and_parameter_type_is_strict(self):
        self.assertFalse(aperture.reached(sample(20, 15, [29, 41]), [30, 40]))
        import motion_server
        engine = SimpleNamespace(tasks={'a' * 32: {}}, plan=Mock(return_value={'accepted': True}))
        with patch.object(motion_server, '_task_engine', engine):
            valid = asyncio.run(motion_server.mcp.call_tool('plan_mechanism_task', {'task_id': 'a' * 32, 'target_openings_mm': [30, 40]}))
            self.assertFalse(valid.is_error)
            self.assertEqual(engine.plan.call_args.kwargs['target_openings_mm'], [30, 40])
            engine.plan.reset_mock()
            invalid = asyncio.run(motion_server.mcp.call_tool('plan_mechanism_task', {'task_id': 'a' * 32, 'target_openings_mm': [True, 40]}))
            self.assertTrue(invalid.is_error)
            engine.plan.assert_not_called()

    def test_probe_collision_reports_safe_stroke_and_stops_expansion(self):
        initial = sample(0, 0, [70, 80])
        safe = sample(10, 2.5, [65, 75])
        collision = sample(15, 4.3, [40, 50], {'clip|rod': 6})
        inaccessible = sample(20, 5, [29, 39])
        self.session.call.return_value = {'run_id': 'b' * 32}
        with patch.object(aperture, 'samples', return_value=([initial, safe, collision, inaccessible], {})), patch.object(core, 'write'):
            result = aperture.run(self.session, self.proposal, self.drive, self.reference)
        self.assertFalse(result['declared_scope_passed'])
        self.assertEqual(result['first_sample_with_interference'], collision)
        self.assertEqual(result['last_clear_probe_sample'], safe)
        self.assertFalse(result['native_study_saved'])
        self.session.call.assert_called_once()
        self.assertEqual(self.session.call.call_args.kwargs['stroke_mm'], 5)

    def test_dense_scan_vetoes_saving_when_return_leg_hits(self):
        first = sample(0, 0, [70, 80])
        accepted = sample(20, 5, [30, 40])
        new_interference = sample(24, 4.5, [34, 44], {'guide|neighbor': 2})
        rows = [dict(first, frame=i) for i in range(41)]
        rows[20], rows[24] = accepted, new_interference
        self.session.call.side_effect = [{'run_id': 'b' * 32}, {'run_id': 'c' * 32, 'Study': 'temporary'}, {'saved': False}]
        with patch.object(aperture, 'samples', side_effect=[([first, accepted], {}), (rows, {})]), patch.object(core, 'write'):
            result = aperture.run(self.session, self.proposal, self.drive, self.reference)
        self.assertEqual(result['first_sample_with_interference'], new_interference)
        self.assertFalse(result['declared_scope_passed'])
        self.session.call.assert_called_with('_finish_aperture_cycle', model_id='model', study='temporary', keep=False)

    def test_suppressed_mates_bind_the_discard_checkpoint_before_sampling(self):
        self.session.initial_inspection = {'mates': [{'suppressed': True}]}
        checkpoint = 'd' * 32
        self.session.call.side_effect = [{'checkpoint_id': checkpoint}, {'run_id': 'b' * 32}]
        initial = sample(0, 0, [70, 80])
        collision = sample(10, 2.5, [55, 60], {'clip|rod': 6})
        with patch.object(aperture, 'samples', return_value=([initial, collision], {})), patch.object(core, 'write'):
            result = aperture.run(self.session, self.proposal, self.drive, self.reference)
        self.assertFalse(result['declared_scope_passed'])
        calls = self.session.call.call_args_list
        self.assertEqual(calls[0].args, ('create_model_checkpoint',))
        self.assertEqual(calls[1].kwargs['discard_checkpoint'], checkpoint)


if __name__ == '__main__':
    unittest.main()
