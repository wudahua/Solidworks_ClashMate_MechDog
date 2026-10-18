"""Preflight rejects environmental failures before source replacement; snapshot API scope."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.install_preflight import preflight
from scripts.upgrade import upgrade, UpgradeFailure
import test_release_feedback as release_fixtures


class UpgradePreflightTests(unittest.TestCase):
    setUp = release_fixtures.ReleaseFeedbackTests.setUp
    files = release_fixtures.ReleaseFeedbackTests.files
    write_zip = release_fixtures.ReleaseFeedbackTests.write_zip
    def test_venv_selected_in_dry_run_is_rejected_before_backup_or_lease(self):
        self.write_zip()
        selected = dict(prefix='venv', base_prefix='base', base_executable='base-python', bits=64, version=[3, 12, 0])
        with patch('scripts.install_preflight.identity', return_value=selected), patch('scripts.upgrade.idle_installation') as lease:
            with self.assertRaisesRegex(UpgradeFailure, 'must select the base Python'):
                upgrade(self.package, self.target, sys.executable, dry_run=True)
            lease.assert_not_called()
        self.assertEqual((self.target/'motion_server.py').read_bytes(), b'old source')
        self.assertFalse((self.target/'upgrade-backups').exists())

    def test_missing_sw_dlls_fail_in_dry_run_and_real_run_before_replacement(self):
        self.write_zip()
        selected = dict(prefix='base', base_prefix='base', executable='python', base_executable='python', bits=64, version=[3, 12, 0])
        # This case targets SW prerequisites, not the independent incomplete-venv check.
        with patch('scripts.install_preflight.identity', return_value=selected), patch('scripts.install_preflight.validate'), patch('pathlib.Path.exists', return_value=False):
            for dry in (True, False):
                with self.assertRaisesRegex(ValueError, 'SOLIDWORKS_BUILD_PREREQUISITES_MISSING'):
                    preflight(self.target, sys.executable, self.root/'missing-sw', check_access=False)
        self.assertFalse((self.target/'upgrade-backups').exists())

    def test_declared_crlf_bytes_are_rejected_by_lf_release_policy(self):
        import hashlib
        from scripts.verify_release import validate_manifest
        files=self.files();data=files['LICENSE'].replace(b'\n',b'\r\n');files['LICENSE']=data
        manifest=json.loads(files['发布清单.json']);manifest['text_line_endings']='LF'
        for item in manifest['files']:
            if item['path']=='LICENSE':item.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        with self.assertRaisesRegex(ValueError,'LF policy violated'):
            validate_manifest(manifest,files.__getitem__)

    def test_preflight_failure_does_not_enter_transaction_in_both_modes(self):
        self.write_zip()
        for dry in (True, False):
            with patch('scripts.upgrade.preflight', side_effect=ValueError('ENVIRONMENT_UNAVAILABLE')), patch('scripts.upgrade.idle_installation') as lease:
                with self.assertRaisesRegex(UpgradeFailure, 'ENVIRONMENT_UNAVAILABLE'):
                    upgrade(self.package, self.target, sys.executable, dry_run=dry)
                lease.assert_not_called()
        self.assertFalse((self.target/'upgrade-backups').exists())


class SnapshotPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_checkpoint_is_forwarded_without_implicit_save(self):
        import motion_server
        with patch.object(motion_server, 'enqueue', return_value='queued') as queue:
            result = await motion_server.preflight_motion('user_'+'a'*32, 'Study', True, 1, 30, 'b'*32)
            self.assertEqual(result, 'queued')
            self.assertEqual(queue.call_args.args[1]['checkpoint_id'], 'b'*32)
            self.assertNotIn('save', queue.call_args.args[1])

    async def test_checkpoint_parameter_is_rejected_for_basic_preflight(self):
        import motion_server
        with patch.object(motion_server, 'call') as request:
            with self.assertRaises(Exception):
                await motion_server.preflight_motion('user_'+'a'*32, checkpoint_id='b'*32)
            request.assert_not_called()

    def test_wait_budget_environment_is_validated(self):
        from sw_mcp.bridge import Bridge
        with patch.dict(os.environ, {'SW_MCP_LONG_OPERATION_WAIT_S': '1200'}):
            self.assertEqual(Bridge(ROOT).motion_scan_timeout, 1200)
        for value in ('nan', 'inf', '0', '3601'):
            with patch.dict(os.environ, {'SW_MCP_LONG_OPERATION_WAIT_S': value}):
                with self.assertRaises(ValueError):
                    Bridge(ROOT)


if __name__ == '__main__':
    unittest.main()
