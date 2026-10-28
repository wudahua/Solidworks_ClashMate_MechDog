import asyncio
import hashlib
import json
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from sw_mcp.bridge import CadError
from sw_mcp.jobs import Jobs
from sw_mcp import job_payload
from test_service import temporary_workspace
import test_alpha5 as fixtures


class FailureContractTests(unittest.TestCase):
    def test_default_history_is_verified_offline_and_does_not_rebind_current_cad(self):
        import motion_server as server
        from sw_mcp.artifacts import Artifacts
        with temporary_workspace() as directory:
            root = Path(directory); folder = root/'runs'/('b'*32); folder.mkdir(parents=True)
            csv = folder/'component-poses.csv'
            csv.write_text('frame,time_s,component_id,instance,x_m,y_m,z_m,r00,r01,r02,r10,r11,r12,r20,r21,r22\n0,0,c,part,0,0,0,1,0,0,0,1,0,0,0,1\n1,1,c,part,0.01,0,0,1,0,0,0,1,0,0,0,1\n', encoding='utf-8')
            manifest = {'run_id':'b'*32, 'result_validity':'verified', 'sampling_status':'completed', 'restoration_status':'restored', 'native_time_axis_verified':True, 'frames':2, 'components':1, 'duration_s':1, 'output_fps':1, 'poses_sha256':hashlib.sha256(csv.read_bytes()).hexdigest()}
            path = folder/'solve.json'; path.write_text(json.dumps(manifest), encoding='utf-8')
            before = path.read_bytes()
            with patch.object(server, 'artifacts', Artifacts(root)), patch.object(server.bridge, 'request') as request:
                for tool, args in [('get_motion_summary', {'run_id':'b'*32}), ('export_motion_curve', {'run_id':'b'*32, 'component_id':'c', 'quantity':'displacement'})]:
                    response = asyncio.run(server.mcp.call_tool(tool, args))
                    self.assertFalse(response.is_error, response.content)
                    result = response.structured_content['result']
                    self.assertEqual(result['current_model_validity'], 'not_checked_offline')
                    self.assertTrue(result['historical_data'])
                    self.assertFalse(result['physical_validation_claim'])
                self.assertEqual(path.read_bytes(), before)
                # A historical native result can be integral but inconclusive;
                # only explicit diagnostic reads may bypass the result conclusion.
                manifest['result_validity'] = 'inconclusive'; path.write_text(json.dumps(manifest), encoding='utf-8')
                response = asyncio.run(server.mcp.call_tool('get_motion_summary', {'run_id':'b'*32}))
                self.assertEqual(response.structured_content['error']['code'], 'RESULTS_UNVERIFIED')
                response = asyncio.run(server.mcp.call_tool('get_motion_summary', {'run_id':'b'*32, 'allow_unverified_history':True}))
                self.assertFalse(response.is_error)
                csv.write_bytes(csv.read_bytes()+b'tampered')
                response = asyncio.run(server.mcp.call_tool('export_motion_curve', {'run_id':'b'*32, 'component_id':'c', 'quantity':'displacement', 'allow_unverified_history':True}))
                self.assertEqual(response.structured_content['error']['code'], 'ARTIFACT_HASH_MISMATCH')
                request.assert_not_called()

    def test_async_failures_timeouts_and_internal_errors_have_safe_actions(self):
        for code, restoration in [('MOTION_RESULTS_INCOMPLETE', 'restored'), ('CAD_TIMEOUT', 'unknown'), ('EXECUTOR_LOST', 'unknown'), ('SERVICE_ERROR', 'unknown')]:
            class FailingBridge:
                cad_operation_state = 'unknown'
                def request(self, operation, **params):
                    if code == 'SERVICE_ERROR': raise RuntimeError('private stack detail')
                    raise CadError(code, '原生任务失败', restoration, {'next_action': 'review_saved_evidence'})
            with temporary_workspace() as directory:
                root = Path(directory); jobs = Jobs(FailingBridge(), root)
                submitted = jobs.submit('run_user_study', {'model_id': 'none'})
                jobs._pool.shutdown(wait=True)
                saved = root / 'runs/jobs' / (submitted['job_id'] + '.json')
                original = saved.read_bytes()
                error = jobs.get(submitted['job_id'])['error']
                self.assertEqual(error['code'], code)
                self.assertFalse(error['next_action']['automatic_retry'])
                self.assertEqual(error['next_action']['options'], [])
                self.assertTrue(error['diagnostics']['job_created'])
                self.assertIsNone(error['diagnostics']['cad_dispatched'])
                self.assertNotIn('private stack detail', error['message'])
                self.assertEqual(saved.read_bytes(), original)

    def test_large_error_retains_action_budget_units_and_exact_pointer_reads(self):
        from sw_mcp.errors import operational_error
        with temporary_workspace() as directory:
            root = Path(directory)
            details = {'requested_drive': {'Axis': [0, 0, 1], 'AxisLocal': [1, 0, 0]},
                       'review_items': ['a', 'b', 'c', 'fourth'], 'native_motor_snapshot': {'parameters': {'large': 'x' * 15000}}}
            job = {'job_id': 'a'*32, 'status': 'failed', 'error': operational_error('MOTION_RESULTS_INCOMPLETE', '采样不完整', 'restored', {'details': details}, job_created=True)}
            summary = job_payload.bound(root, job)
            self.assertLessEqual(job_payload.wire_size(summary), job_payload.BUDGET)
            self.assertEqual(summary['wire_budget_bytes'], 16000)
            self.assertGreater(summary['full_response_wire_bytes'], summary['full_response_bytes'])
            self.assertFalse(summary['error']['next_action']['automatic_retry'])
            self.assertGreater(summary['summary_omitted_path_count'], 0)
            self.assertEqual(summary['error']['diagnostics']['details']['requested_drive']['Axis'], [0,0,1])
            self.assertEqual(summary['error']['diagnostics']['details']['review_items'][-1], 'fourth')
            args = summary['full_response_read']['arguments']
            full = job_payload.read(root, args['job_id'], args['response_artifact_id'], 0, 2000, '/error/diagnostics/details/requested_drive/Axis')
            self.assertEqual(json.loads(full['text']), [0, 0, 1])

    def test_missing_null_boolean_string_and_enum_errors_are_structured(self):
        import motion_server as server
        cases = [('run_motion_study', {'model_id':'m','study':'s','duration_s': value}) for value in (True, '1.0', None)]
        cases += [('inspect_model', {'model_id':'m','detail_level':'bad'}), ('run_motion_study', {})]
        with patch.object(server.jobs, 'submit') as submit, patch.object(server.bridge, 'request') as request:
            for tool, args in cases:
                response = asyncio.run(server.mcp.call_tool(tool, args))
                error = response.structured_content['error']
                self.assertEqual(error['code'], 'INVALID_ARGUMENT')
                self.assertIn('field', error['diagnostics'])
                self.assertNotIn('pydantic', response.content[0].text)
                self.assertFalse(error['diagnostics']['cad_dispatched'])
            submit.assert_not_called(); request.assert_not_called()


class UpgradeReceiptTests(unittest.TestCase):
    def test_windows_powershell_capture_and_native_exit_code(self):
        from upgrade_powershell_checks import check
        self.assertTrue(check()['all_passed'])

    def test_catchable_keyboard_interrupt_verifies_rollback_and_receipt(self):
        from scripts.upgrade import UpgradeFailure
        fixture = fixtures.ReleaseUpgradeTests(); fixture.setUp()
        try:
            fixture.write_zip()
            with patch('scripts.upgrade.idle_installation', return_value=nullcontext()), patch('scripts.upgrade.verify', side_effect=KeyboardInterrupt):
                with self.assertRaises(UpgradeFailure) as caught:
                    fixtures.upgrade(fixture.package, fixture.target, sys.executable, install=False)
            receipt = json.loads(next((fixture.target/'upgrade-backups').glob('*/receipt.json')).read_text(encoding='utf-8'))
            self.assertEqual(caught.exception.code,'UPGRADE_FAILED_ROLLBACK_VERIFIED')
            self.assertEqual(receipt['stage'], 'failed_rollback_verified')
            self.assertFalse(receipt['committed'])
            self.assertTrue(receipt['rollback_verified'])
            self.assertEqual(receipt['original_failure']['type'],'KeyboardInterrupt')
            self.assertEqual((fixture.target/'motion_server.py').read_bytes(),b'old source')
        finally: fixture.doCleanups()


if __name__ == '__main__': unittest.main()
