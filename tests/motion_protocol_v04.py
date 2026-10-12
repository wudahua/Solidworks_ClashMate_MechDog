"""MCP SDK wire protocol smoke test; real COM when --model-id is provided."""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def main(model_id):
    env = {key: os.environ[key] for key in ("SW_MCP_PROCESS_ID",) if key in os.environ}
    report = {}
    async with Client(StdioServerParameters(command=sys.executable, args=[str(ROOT/"motion_server.py")], cwd=ROOT, env=env)) as client:
        tool_response = await client.list_tools()
        names = {t.name for t in tool_response.tools}
        assert len(names) == 20 and {"import_assembly", "run_motion_study", "reset_study_time", "get_run_artifacts", "read_run_poses"} <= names
        report["tools"] = sorted(names)
        for name, params in [("run_motion_study", {"model_id": "none", "study": "none", "duration_s": -1}), ("import_assembly", {"path": "relative.sldasm"}), ("create_motion_study", {"model_id": "none", "study": "none", "component_id": "none", "entity_id": "none", "motor_type": "linear", "speed": -1})]:
            error = await client.call_tool(name, params)
            assert error.is_error
        report["invalid_requests_rejected"] = 3
        for name in ("get_run_artifacts", "read_run_poses"):
            response = await client.call_tool(name, {"run_id": "0"*32})
            assert response.is_error and response.structured_content["error"]["code"] == "RUN_NOT_FOUND"
            assert str(ROOT) not in response.structured_content["error"]["message"]
        report["offline_missing_run_errors_verified"] = True
        if model_id:
            environment = await client.call_tool("get_environment", {})
            assert not environment.is_error
            report["environment"] = environment.structured_content["result"]
            result = await client.call_tool("run_motion_study", {"model_id": model_id, "study": "Public_rotary", "duration_s": 1, "output_fps": 30})
            assert not result.is_error
            job_id = result.structured_content["job_id"]
            started = time.monotonic()
            while True:
                response = await client.call_tool("get_job", {"job_id": job_id})
                job = response.structured_content
                if job["status"] not in ("running", "queued"):
                    break
                assert time.monotonic()-started < 90
                await asyncio.sleep(.2)
            assert job["status"] == "succeeded", job
            assert job["progress"]["terminal"] and job["progress"]["stage"] == "succeeded"
            assert job["progress"]["cad_operation_finished"]
            assert job["result"]["run_id"] == job_id
            summary = await client.call_tool("get_motion_summary", {"run_id": job_id})
            assert not summary.is_error
            report["job"] = job
            try:
                import ctypes
                from mcp.os.win32.utilities import _process_jobs
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.OpenProcess(0x1000, False, report["environment"]["solidworks_process_id"])
                memberships = []
                try:
                    for job_handle in _process_jobs.values():
                        belongs = ctypes.c_int()
                        if kernel.IsProcessInJob(handle, int(job_handle), ctypes.byref(belongs)):
                            memberships.append(bool(belongs.value))
                finally:
                    kernel.CloseHandle(handle)
                report["solidworks_membership_in_client_jobs"] = memberships
            except ImportError:
                report["solidworks_membership_in_client_jobs"] = "not_available"
    if model_id:
        sys.path.insert(0, str(ROOT))
        from sw_mcp.bridge import Bridge
        report["solidworks_alive_after_disconnect"] = Bridge._pid_alive(report["environment"]["solidworks_process_id"])
        assert report["solidworks_alive_after_disconnect"], "SOLIDWORKS exited after disconnect"
    report["all_passed"] = True
    (ROOT/"runs").mkdir(exist_ok=True)
    (ROOT/"runs/motion-protocol-v04.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"all_passed": True, "tools": len(names), "real_com": bool(model_id)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default="")
    asyncio.run(main(parser.parse_args().model_id))
