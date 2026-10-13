"""Installation failures never dispatch CAD requests or discard recovery state."""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sw_mcp.bridge import Bridge, CadError
from sw_mcp.startup import executor_diagnostics
from scripts.validate_runtime import validate


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.base = ROOT / "runs" / "installation-tests"
        self.root = self.base / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.exe = self.root / "executor/bin/SwExecutor.exe"
        self.exe.parent.mkdir(parents=True)
        self.exe.write_bytes(b"test executable never launched")
        self.bridge = Bridge(self.root)

    def tearDown(self):
        self.bridge.close()
        self.root.resolve().relative_to(self.base.resolve())
        if self.root.is_symlink():
            raise RuntimeError("Unexpected linked test directory")
        shutil.rmtree(self.root)

    def failure(self, exc, code):
        with patch("sw_mcp.bridge.subprocess.Popen", side_effect=exc) as launch:
            with self.assertRaises(CadError) as error:
                self.bridge.request("get_environment")
        self.assertEqual(error.exception.code, code)
        self.assertEqual(error.exception.restoration_status, "not_required")
        self.assertEqual(error.exception.diagnostics["stage"], "launch")
        self.assertEqual(launch.call_count, 1)
        self.assertIsNone(self.bridge._process)
        self.assertIsNone(self.bridge._log)
        self.assertFalse(self.bridge._ever_dispatched)
        self.assertFalse(self.bridge._journal_path.exists())
        return error.exception

    def test_access_denied_preserves_system_error_and_build_identity(self):
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        self.exe.with_name("build-manifest.json").write_text(json.dumps({"executor_sha256": digest}), encoding="utf-8-sig")
        error = self.failure(PermissionError(13, "host rejected executable"), "EXECUTOR_ACCESS_DENIED")
        self.assertTrue(error.diagnostics["matches_build_record"])
        self.assertEqual(error.diagnostics["errno"], 13)
        self.assertEqual(error.diagnostics["executor_sha256"], digest)

    def test_missing_executable_between_inspection_and_launch(self):
        self.failure(FileNotFoundError(2, "file disappeared"), "EXECUTOR_NOT_BUILT")

    def test_invalid_executable_has_distinct_startup_error(self):
        self.failure(OSError(8, "bad executable format"), "EXECUTOR_START_FAILED")

    def test_missing_executable_never_launches(self):
        self.exe.unlink()
        with patch("sw_mcp.bridge.subprocess.Popen") as launch:
            with self.assertRaises(CadError) as error:
                self.bridge.request("get_environment")
        self.assertEqual(error.exception.code, "EXECUTOR_NOT_BUILT")
        launch.assert_not_called()
        self.assertFalse(self.bridge._journal_path.exists())

    def test_directory_at_executor_path_is_rejected(self):
        self.exe.unlink(); self.exe.mkdir()
        with self.assertRaises(CadError) as error:
            self.bridge.request("get_environment")
        self.assertEqual(error.exception.code, "EXECUTOR_NOT_BUILT")

    def test_lock_file_access_denied_has_structured_error(self):
        with patch.object(Path, "mkdir", side_effect=PermissionError(13, "cannot write runs")):
            with self.assertRaises(CadError) as error:
                self.bridge.request("get_environment")
        self.assertEqual(error.exception.code, "MCP_LEASE_UNAVAILABLE")
        self.assertEqual(error.exception.diagnostics["stage"], "open_lease")
        self.assertIsNone(self.bridge._lease)

    def test_log_access_denied_does_not_launch_or_create_journal(self):
        original = Path.open
        def checked(path, *args, **kwargs):
            if path.name == "executor.log": raise PermissionError(13, "log access denied")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", checked), patch("sw_mcp.bridge.subprocess.Popen") as launch:
            with self.assertRaises(CadError) as error:
                self.bridge.request("get_environment")
        self.assertEqual(error.exception.code, "EXECUTOR_LOG_UNAVAILABLE")
        self.assertFalse(self.bridge._journal_path.exists())
        launch.assert_not_called()

    def test_preexisting_unknown_state_is_never_overwritten_by_installation_failure(self):
        self.bridge._journal({"status": "unknown", "request_id": "preserve", "solidworks_pid": 22})
        before = self.bridge._journal_path.read_bytes()
        with patch("sw_mcp.bridge.subprocess.Popen") as launch:
            with self.assertRaises(CadError) as error:
                self.bridge.request("get_environment")
        self.assertEqual(error.exception.code, "RECOVERY_REQUIRED")
        self.assertEqual(before, self.bridge._journal_path.read_bytes())
        launch.assert_not_called()

    def test_repeated_launch_failure_uses_same_owner_without_leaking_log(self):
        self.failure(PermissionError(13, "denied"), "EXECUTOR_ACCESS_DENIED")
        # Another launch failure is allowed before any dispatch; it cannot become EXECUTOR_LOST.
        self.failure(FileNotFoundError(2, "missing"), "EXECUTOR_NOT_BUILT")

    def test_corrupt_and_mismatched_build_records_do_not_hide_launch_error(self):
        manifest = self.exe.with_name("build-manifest.json")
        manifest.write_text("{bad", encoding="utf-8")
        self.assertEqual(executor_diagnostics(self.exe, stage="test")["build_record_status"], "unreadable")
        manifest.write_text(json.dumps({"executor_sha256": "changed"}), encoding="utf-8")
        self.assertFalse(executor_diagnostics(self.exe, stage="test")["matches_build_record"])

    def runtime(self):
        selected = {"version": [3, 12, 14], "bits": 64, "base_executable": str(self.root / "python.exe")}
        venv = self.root / ".venv"
        actual = {**selected, "prefix": str(venv), "base_prefix": str(self.root)}
        return selected, actual, venv

    def test_matching_venv_is_accepted(self):
        validate(*self.runtime())

    def test_venv_python_version_mismatch_is_rejected(self):
        selected, actual, venv = self.runtime(); actual["version"] = [3, 13, 14]
        with self.assertRaises(ValueError): validate(selected, actual, venv)

    def test_same_version_different_python_is_rejected(self):
        selected, actual, venv = self.runtime(); actual["base_executable"] = str(self.root / "other/python.exe")
        with self.assertRaises(ValueError): validate(selected, actual, venv)

    def test_wrong_bitness_old_python_and_wrong_venv_are_rejected(self):
        for update in ({"bits": 32}, {"version": [3, 10, 9]}, {"prefix": str(self.root / "other")}):
            selected, actual, venv = self.runtime(); actual.update(update)
            with self.assertRaises(ValueError): validate(selected, actual, venv)

    def test_self_check_reports_connection_failure_as_json_and_nonzero_exit(self):
        spec = importlib.util.spec_from_file_location("installation_self_check", ROOT / "scripts/self_check.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        output = StringIO()
        with patch.object(module, "ROOT", self.root), patch.object(sys, "argv", ["self_check", "--connect"]), patch("sw_mcp.bridge.Bridge.request", side_effect=CadError("COM_SESSION_ID_MISMATCH", "wrong PID", diagnostics={"actual_pid": 22})), redirect_stdout(output):
            code = module.main()
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["connection_requested"])
        self.assertFalse(result["connection_checked"])
        self.assertEqual(result["error"]["code"], "COM_SESSION_ID_MISMATCH")
        self.assertEqual(result["error"]["diagnostics"]["actual_pid"], 22)


if __name__ == "__main__":
    unittest.main()
