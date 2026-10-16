"""Failure and concurrency checks for service behavior; CAD is tested separately."""
import concurrent.futures
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
import shutil
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sw_mcp.bridge import Bridge as NativeBridge, CadError
from sw_mcp.jobs import Jobs
from transport_cleanup import drain_bridge, remove_test_root

_bridges = []
class Bridge(NativeBridge):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bridges.append(self)


@contextmanager
def temporary_workspace():
    base = Path(__file__).resolve().parents[1] / "runs" / "st"
    base.mkdir(parents=True, exist_ok=True)
    temporary = base / uuid.uuid4().hex[:8]
    temporary.mkdir()
    try:
        temporary.resolve().relative_to(base.resolve())
        yield str(temporary)
    finally:
        failures=[]
        (temporary/'release').touch()
        for bridge in list(_bridges):
            if bridge.root == temporary:
                try:
                    drain_bridge(bridge)
                except BaseException as error:
                    failures.append(error)
                finally:
                    _bridges.remove(bridge)
        if failures:
            raise RuntimeError(f"Helper cleanup failed; preserved {temporary}") from failures[0]
        remove_test_root(temporary,base)



class BlockingCad:
    cad_operation_state = "available"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def request(self, operation, **params):
        self.calls.append(operation)
        self.entered.set()
        if not self.release.wait(2):
            raise RuntimeError("test gate timed out")
        return {"operation": operation}


class ServiceTests(unittest.TestCase):
    def test_generic_recovery_cannot_unlock_a_different_model(self):
        with temporary_workspace() as directory:
            bridge = Bridge(Path(directory))
            model = "user_" + "a" * 32
            bridge._journal({"status": "unknown", "executor_pid": 12, "solidworks_pid": 22, "model_id": model})
            for operation, params in [("restore_model_checkpoint", {"model_id": "user_" + "b"*32, "checkpoint_id": "c"*32}), ("restore_checkpoint", {"checkpoint_id": "c"*32})]:
                with self.assertRaises(CadError) as error:
                    bridge.request(operation, **params)
                self.assertEqual(error.exception.code, "RECOVERY_MODEL_MISMATCH")
                self.assertTrue(bridge.recovery_state()["recovery_required"])

    def test_generic_motion_jobs_allocate_a_run_id(self):
        class CaptureCad:
            cad_operation_state = "available"
            def request(self, operation, **params):
                return {"operation": operation, "run_id": params["run_id"]}
        with temporary_workspace() as directory:
            jobs = Jobs(CaptureCad(), Path(directory))
            submitted = jobs.submit("run_user_study", {"model_id": "user_"+"a"*32})
            jobs._pool.shutdown(wait=True)
            job = jobs.get(submitted["job_id"])
            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(job["result"]["run_id"], submitted["job_id"])

    def test_poll_remains_available_and_second_job_stays_queued(self):
        with temporary_workspace() as directory:
            cad = BlockingCad()
            jobs = Jobs(cad, Path(directory))
            first = jobs.submit("run_study", {})
            self.assertTrue(cad.entered.wait(1))
            second = jobs.submit("check_interference_during_motion", {})
            started = time.monotonic()
            self.assertEqual(jobs.get(first["job_id"])["status"], "running")
            self.assertEqual(jobs.get(second["job_id"])["status"], "queued")
            self.assertLess(time.monotonic() - started, .1)
            self.assertEqual(cad.calls, ["run_study"])
            cad.release.set()
            jobs._pool.shutdown(wait=True)
            self.assertEqual(jobs.get(second["job_id"])["status"], "succeeded")

    def test_solver_error_never_becomes_pass(self):
        class FailingCad:
            cad_operation_state = "available"

            def request(self, *args, **kwargs):
                raise CadError("SOLVER_FAILED", "solver failed")

        with temporary_workspace() as directory:
            jobs = Jobs(FailingCad(), Path(directory))
            submitted = jobs.submit("run_study", {})
            jobs._pool.shutdown(wait=True)
            job = jobs.get(submitted["job_id"])
            self.assertEqual(job["status"], "failed")
            self.assertEqual(job["error"]["assertion"], "inconclusive")
            self.assertNotIn("result", job)

    def test_timeout_blocks_new_cad_calls_until_actual_late_reply(self):
        # Real subprocess transport, simulated slow CAD operation.
        with temporary_workspace() as directory:
            root = Path(directory)
            binary = root / "executor" / "bin"
            binary.mkdir(parents=True)
            (binary / "SwExecutor.exe").touch()
            helper = root / "slow_executor.py"
            helper.write_text(
                "import json,sys,time\nfrom pathlib import Path\ngate=Path(__file__).with_name('release')\n"
                "print(json.dumps({'ready':True,'protocol_version':1,'process_id':22}),flush=True)\n"
                "for line in sys.stdin:\n"
                " r=json.loads(line)\n"
                " if r['op']=='slow':\n"
                "  end=time.monotonic()+20\n"
                "  while not gate.exists():\n"
                "   if time.monotonic()>end: raise RuntimeError('gate expired')\n"
                "   time.sleep(.01)\n"
                " print(json.dumps({'id':r['id'],'ok':True,'result':r['op']}),flush=True)\n",
                encoding="utf-8",
            )
            original_popen = subprocess.Popen

            def spawn(command, **kwargs):
                return original_popen([sys.executable, str(helper)], **kwargs)

            bridge = Bridge(root, timeout=.5)
            try:
                with patch("sw_mcp.bridge.subprocess.Popen", side_effect=spawn):
                    with self.assertRaises(CadError) as first:
                        bridge.request("slow")
                    self.assertEqual(first.exception.code, "CAD_TIMEOUT")
                    self.assertEqual(first.exception.diagnostics["next_tools"], ["get_recovery_state"])
                    self.assertEqual(first.exception.diagnostics["next_call"]["arguments"]["request_id"], first.exception.diagnostics["request_id"])
                    self.assertEqual(bridge.cad_operation_state, "unknown_after_timeout")
                    with self.assertRaises(CadError) as second:
                        bridge.request("next")
                    self.assertEqual(second.exception.code, "CAD_BUSY_AFTER_TIMEOUT")
                    (root/"release").touch()
                    bridge.timeout=5
                    deadline = time.monotonic() + 10
                    while bridge.cad_operation_state != "available" and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertEqual(bridge.request("next"), "next")
            finally:
                (root/'release').touch()
                drain_bridge(bridge)


    def test_restart_refuses_unfinished_request_and_live_previous_executor(self):
        with temporary_workspace() as directory:
            root = Path(directory)
            b = Bridge(root)
            b._journal({"status": "active", "request_id": "old", "executor_pid": 12, "solidworks_pid": 22})
            restarted = Bridge(root)
            with self.assertRaises(CadError) as error:
                restarted.request("run_study")
            self.assertEqual(error.exception.code, "RECOVERY_REQUIRED")
            with patch.object(restarted, "_pid_alive", return_value=True):
                with self.assertRaises(CadError) as error:
                    restarted.request("restore_checkpoint", checkpoint_id="a" * 32)
                self.assertEqual(error.exception.code, "PREVIOUS_EXECUTOR_ALIVE")

    def test_unreadable_journal_never_allows_a_new_operation(self):
        with temporary_workspace() as directory:
            root = Path(directory)
            (root / "runs").mkdir()
            (root / "runs" / "executor-state.json").write_text("broken", encoding="utf-8")
            b = Bridge(root)
            with self.assertRaises(CadError) as error:
                b.request("get_capabilities")
            self.assertEqual(error.exception.code, "RECOVERY_REQUIRED")

    def test_progress_poll_ignores_a_different_job_identity(self):
        with temporary_workspace() as directory:
            root = Path(directory)
            cad = BlockingCad()
            jobs = Jobs(cad, root)
            first = jobs.submit("run_study", {})
            self.assertTrue(cad.entered.wait(1))
            progress = root / "runs" / "progress"
            progress.mkdir()
            path = progress / (first["job_id"] + ".json")
            path.write_text(json.dumps({"job_id": "another", "completed": 9}), encoding="utf-8")
            self.assertNotIn("progress", jobs.get(first["job_id"]))
            path.write_text(json.dumps({"job_id": first["job_id"], "completed": 3}), encoding="utf-8")
            self.assertEqual(jobs.get(first["job_id"])["progress"]["completed"], 3)
            cad.release.set()
            jobs._pool.shutdown(wait=True)


    def test_failed_recovery_cannot_clear_an_unfinished_journal(self):
        with temporary_workspace() as directory:
            root = Path(directory)
            binary = root / "executor" / "bin"
            binary.mkdir(parents=True)
            (binary / "SwExecutor.exe").touch()
            helper = root / "reject_recovery.py"
            helper.write_text(
                "import json,sys\n"
                "print(json.dumps({'ready':True,'protocol_version':1,'process_id':22}),flush=True)\n"
                "for line in sys.stdin:\n"
                " r=json.loads(line)\n"
                " print(json.dumps({'id':r['id'],'ok':False,'error':{'code':'BAD_CHECKPOINT','message':'bad','restoration_status':'not_required'}}),flush=True)\n",
                encoding="utf-8")
            bridge = Bridge(root)
            bridge._journal({"status": "active", "executor_pid": 12, "solidworks_pid": 22})
            original_popen = subprocess.Popen
            try:
                with patch("sw_mcp.bridge.subprocess.Popen", side_effect=lambda command, **kwargs: original_popen([sys.executable, str(helper)], **kwargs)), patch.object(bridge, "_pid_alive", return_value=False):
                    with self.assertRaises(CadError) as error:
                        bridge.request("restore_checkpoint", checkpoint_id="bad")
                    self.assertEqual(error.exception.code, "BAD_CHECKPOINT")
                    self.assertTrue(bridge.recovery_state()["recovery_required"])
                    with self.assertRaises(CadError) as error:
                        bridge.request("run_study")
                    self.assertEqual(error.exception.code, "RECOVERY_REQUIRED")
            finally:
                drain_bridge(bridge)


    def test_replacement_session_requires_explicit_flag_and_dead_old_solidworks(self):
        from types import SimpleNamespace
        from io import StringIO
        with temporary_workspace() as directory:
            root = Path(directory)
            bridge = Bridge(root)
            bridge._journal({"status": "active", "executor_pid": 12, "solidworks_pid": 22})
            bridge._process = SimpleNamespace(pid=999, poll=lambda: None, stdin=StringIO())
            bridge._startup.set_result({"ready": True, "protocol_version": 1, "process_id": 23})
            with patch.object(bridge, "_start"), patch.object(bridge, "_pid_alive", side_effect=lambda pid: pid == 22):
                with self.assertRaises(CadError) as error:
                    bridge.request("restore_checkpoint", checkpoint_id="a" * 32)
                self.assertEqual(error.exception.code, "RECOVERY_SESSION_MISMATCH")
                self.assertEqual(error.exception.diagnostics["required_param"], "allow_replacement_session")
                with self.assertRaises(CadError) as error:
                    bridge.request("restore_checkpoint", checkpoint_id="a" * 32, allow_replacement_session=True)
                self.assertEqual(error.exception.code, "PREVIOUS_SOLIDWORKS_ALIVE")
                self.assertTrue(bridge.recovery_state()["recovery_required"])


if __name__ == "__main__":
    unittest.main()
