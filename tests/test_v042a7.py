import asyncio
import unittest
from unittest.mock import patch

from sw_mcp.native_grid import GridAdmissionError, require_grid
from sw_mcp.validation import StrictMCPServer
from mcp.server.mcpserver.exceptions import UnexpectedToolError


class AdmissionContractTests(unittest.TestCase):
    def test_aligned_minimum_matches_real_admission_for_all_supported_fps(self):
        for duration in (.001, .01, .05, .09, .1, .11, .14, .19, .2, .3, 1/3, .4, .5, .9, 1, 1.01, 2):
            possible = [f for f in range(5, 121) if duration*f >= 10-1e-8 and abs(duration*f-round(duration*f)) <= 1e-8]
            error = GridAdmissionError(duration, 30)
            diag = error.diagnostics
            self.assertEqual(diag['minimum_fps_at_requested_duration'], min(possible) if possible else None)
            self.assertEqual(diag['minimum_fps_within_supported_range'], bool(possible))
            for d, f in error.alternatives:
                require_grid(d, f)
            if possible: require_grid(duration, diag['minimum_fps_at_requested_duration'])

    def test_expected_local_errors_share_the_same_machine_readable_envelope(self):
        import motion_server as server
        create = dict(model_id='m', study='s', component_id='c', entity_id='e', motor_type='rotary', speed=10)
        cases = [
            ('create_motion_study', {**create, 'speed': 0}, 'SPEED_OUT_OF_RANGE'),
            ('create_motion_study', {**create, 'duration_s': 40}, 'DURATION_OR_FPS_OUT_OF_RANGE'),
            ('create_motion_study', {**create, 'output_fps': 200}, 'DURATION_OR_FPS_OUT_OF_RANGE'),
            ('create_motion_study', {**create, 'duration_s': .09, 'output_fps': 112}, 'OUTPUT_GRID_NOT_FRAME_ALIGNED'),
            ('verify_motion_preservation', dict(model_id='m', study='s', component_id='c', entity_id='e', expected_motion='rotary', minimum_travel=0), 'MINIMUM_TRAVEL_OUT_OF_RANGE'),
            ('preflight_motion', dict(model_id='m', checkpoint_id='x'), 'CHECKPOINT_ID_MISUSED'),
            ('apply_mate', dict(plan_id='a'*32, confirmed=False), 'CONFIRMATION_REQUIRED'),
            ('reset_study_time', dict(model_id='m', study='s', checkpoint_id='x'), 'CHECKPOINT_ID_MISUSED'),
            ('list_mate_references', dict(model_id='m', limit=999), 'LIMIT_OUT_OF_RANGE'),
            ('get_run_artifacts', dict(run_id='a'*32, model_id='m'), 'INVALID_ARGUMENT'),
            ('run_motion_study', dict(model_id='m', study='s', output_fps='wrong'), 'INVALID_ARGUMENT'),
        ]
        with patch.object(server.jobs, 'submit') as submit, patch.object(server.bridge, 'request') as request:
            for name, args, code in cases:
                with self.subTest(tool=name, code=code):
                    response = asyncio.run(server.mcp.call_tool(name, args))
                    self.assertTrue(response.is_error)
                    error = response.structured_content['error']
                    self.assertEqual(error['code'], code)
                    self.assertTrue(error['message'])
                    self.assertEqual(error['assertion'], 'not_applicable')
                    self.assertEqual(error['restoration_status'], 'not_required')
                    self.assertFalse(error['diagnostics']['cad_dispatched'])
                    self.assertFalse(error['diagnostics']['job_created'])
                    self.assertFalse(error['next_action']['automatic_retry'])
            request.assert_not_called(); submit.assert_not_called()

    def test_unexpected_errors_keep_sdk_redaction(self):
        server = StrictMCPServer('contract')
        @server.tool()
        async def broken() -> str:
            raise RuntimeError('private implementation detail')
        with self.assertRaises(UnexpectedToolError) as caught:
            asyncio.run(server.call_tool('broken', {}))
        self.assertNotIn('private implementation detail', str(caught.exception))


if __name__ == '__main__': unittest.main()
