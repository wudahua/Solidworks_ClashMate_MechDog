import asyncio
import errno
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from grid_protocol_checks import check
from sw_mcp.native_grid import GridAdmissionError, require_grid
from test_service import temporary_workspace
from transport_cleanup import remove_test_root


class GridTransportTests(unittest.TestCase):
    def test_real_stdio_four_tools_refuse_with_diagnostics_and_forward_valid_arguments(self):
        _, report = asyncio.run(check())
        self.assertTrue(report['all_passed'])

    def test_alternatives_are_feasible_even_when_fixed_duration_cannot_be_supported(self):
        for duration, fps in ((.001, 30), (5e-324, 30), (.2, 30), (.3, 30)):
            with self.subTest(duration=duration):
                with self.assertRaises(GridAdmissionError) as caught:
                    require_grid(duration, fps)
                error = caught.exception
                # Tiny positive input must still produce serializable evidence,
                # never OverflowError or an Infinity JSON token.
                json.dumps(error.diagnostics, allow_nan=False)
                for d, f in error.alternatives:
                    require_grid(d, f)
                    self.assertLessEqual(abs(d * f - round(d * f)), 1e-8)
                    self.assertTrue(5 <= f <= 120)
                if duration < .01:
                    self.assertFalse(error.diagnostics['minimum_fps_within_supported_range'])

    def test_expected_refusal_covers_sync_creation_and_preserves_user_arguments(self):
        import motion_server
        with patch('motion_server.enqueue') as enqueue, patch('motion_server.bridge.request') as request:
            response = asyncio.run(motion_server.create_motion_study('m', 's', 'c', 'e', 'rotary', 10, reverse_direction=True, reference_component_id='ref', duration_s=.2, wait_for_completion=True))
            options = response.structured_content['error']['next_action']['options']
            for option in options:
                args = option['arguments']
                self.assertTrue(args['reverse_direction'])
                self.assertEqual(args['reference_component_id'], 'ref')
                self.assertTrue(args['wait_for_completion'])
            request.assert_not_called(); enqueue.assert_not_called()


class CleanupTests(unittest.TestCase):
    def test_transient_permission_error_retries_then_deletes(self):
        with temporary_workspace() as directory:
            root = Path(directory) / 'disposable'; root.mkdir()
            import shutil
            original = shutil.rmtree
            errors = [PermissionError(errno.EACCES, 'temporary lock'), None]
            def remove(path):
                error = errors.pop(0)
                if error: raise error
                return original(path)
            with patch('transport_cleanup.shutil.rmtree', side_effect=remove), patch('transport_cleanup.time.sleep') as sleep:
                remove_test_root(root, Path(directory))
                self.assertFalse(root.exists()); sleep.assert_called_once()

    def test_persistent_denial_remains_failure_with_original_cause(self):
        with temporary_workspace() as directory:
            root = Path(directory) / 'disposable'; root.mkdir()
            error = PermissionError(errno.EACCES, 'host denied')
            with patch('transport_cleanup.shutil.rmtree', side_effect=error) as remove, patch('transport_cleanup.time.sleep'):
                with self.assertRaises(RuntimeError) as caught:
                    remove_test_root(root, Path(directory))
                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(remove.call_count, 3); self.assertTrue(root.exists())

    def test_unsafe_paths_and_nontransient_errors_are_not_retried(self):
        with temporary_workspace() as directory:
            base = Path(directory)
            with patch('transport_cleanup.shutil.rmtree') as remove:
                with self.assertRaises(RuntimeError): remove_test_root(base, base)
                with self.assertRaises(ValueError): remove_test_root(base.parent, base)
                remove.assert_not_called()
            root = base / 'disposable'; root.mkdir()
            with patch('transport_cleanup.shutil.rmtree', side_effect=OSError(errno.EINVAL, 'invalid')) as remove:
                with self.assertRaises(RuntimeError): remove_test_root(root, base)
                self.assertEqual(remove.call_count, 1)


if __name__ == '__main__': unittest.main()
