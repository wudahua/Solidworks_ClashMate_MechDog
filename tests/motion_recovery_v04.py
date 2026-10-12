"""Terminate only the owned executor after a verified pose boundary, then restore."""
import concurrent.futures
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sw_mcp.bridge import Bridge, CadError


def close(bridge):
    bridge.close()
    if bridge._process:
        bridge._process.wait(timeout=20)


def main(model_id):
    os.environ["SW_MCP_FAULT_TESTS"] = "1"
    bridge = Bridge(ROOT)
    report = {"all_passed": False}
    recovered = None
    try:
        environment = bridge.request("get_environment")
        checkpoint = bridge.request("create_model_checkpoint", model_id=model_id)
        solved = bridge.request("run_user_study", model_id=model_id, study="Public_rotary", duration_s=1, output_fps=30, run_id=uuid.uuid4().hex)
        armed = ROOT/"runs"/solved["run_id"]/"executor-loss-armed.json"
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(bridge.request, "_test_executor_loss", run_id=solved["run_id"])
            until = time.monotonic()+20
            while not armed.exists():
                if future.done(): future.result()
                assert time.monotonic() < until
                time.sleep(.05)
            evidence = json.loads(armed.read_text(encoding="utf-8"))
            assert evidence["executor_pid"] == bridge._process.pid
            assert evidence["solidworks_pid"] == environment["solidworks_process_id"]
            assert Path(evidence["model_path"]).resolve().is_relative_to((ROOT/"experiments/user_assemblies").resolve())
            bridge._process.terminate()
            bridge._process.wait(timeout=10)
            try: future.result(timeout=10)
            except CadError as exc: assert exc.code == "EXECUTOR_LOST"
            else: raise AssertionError("lost executor returned success")
        close(bridge)
        recovered = Bridge(ROOT)
        assert recovered.recovery_state()["model_id"] == model_id
        for op, params, expected in [("get_environment", {}, "RECOVERY_REQUIRED"), ("restore_model_checkpoint", {"model_id": "user_"+"0"*32, "checkpoint_id": checkpoint["checkpoint_id"]}, "RECOVERY_MODEL_MISMATCH")]:
            try: recovered.request(op, **params)
            except CadError as exc: assert exc.code == expected
            else: raise AssertionError("unsafe operation accepted")
        restored = recovered.request("restore_model_checkpoint", model_id=model_id, checkpoint_id=checkpoint["checkpoint_id"])
        assert restored["maximum_transform_delta"] < 1e-7 and not recovered.recovery_state()["recovery_required"]
        current = recovered.request("get_environment")
        assert current["solidworks_process_id"] == environment["solidworks_process_id"]
        recomputed = recovered.request("run_user_study", model_id=model_id, study="Public_rotary", duration_s=1, output_fps=30, run_id=uuid.uuid4().hex)
        assert recomputed["drive_validation"]["absolute_magnitude_error"] < .001
        report.update(all_passed=True, fault_boundary=evidence, restored=restored, recomputed=recomputed, same_solidworks_process=True, wrong_model_recovery_rejected=True)
    finally:
        if recovered: close(recovered)
        if bridge._process and bridge._process.poll() is None: close(bridge)
        (ROOT/"runs/motion-recovery-v04.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("GENERIC_EXECUTOR_LOSS_RECOVERY PASS", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1])
