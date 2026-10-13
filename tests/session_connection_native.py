"""Opt-in idle-desktop COM/MCP regression, with a fresh root and an owned SW instance.

Never starts if SolidWorks/executors already exist. Cleanup closes only its exact
owned PID with no documents; any unknown state is preserved for manual review.
"""
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_release import VERSION


def processes():
    completed = subprocess.run(["powershell", "-NoProfile", "-Command",
        "$nativeTestProcesses=@(Get-Process SLDWORKS,SwExecutor -ErrorAction SilentlyContinue | Select-Object Id,ProcessName); ConvertTo-Json -InputObject $nativeTestProcesses -Compress"],
        capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(completed.stdout)


def journal_hash():
    path = ROOT / "runs/executor-state.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


async def main():
    before = processes()
    if before:
        raise RuntimeError("Desktop is not idle; this test will not stop existing processes: " + repr(before))
    preserved = journal_hash()
    folder = ROOT / "runs" / "quanzhou-native" / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    for name in ("sw_mcp", "scripts"):
        shutil.copytree(ROOT / name, folder / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "motion_server.py", folder / "motion_server.py")
    shutil.copytree(ROOT / "executor/bin", folder / "executor/bin")
    report = {"all_passed": False, "test_root": str(folder), "protected_journal_sha256_before": preserved,
              "initial_processes": before, "owned_solidworks_pid": None,
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                  ("executor/Cad.cs", "executor/SessionConnection.cs", "executor/Program.cs", "executor/UserMotion.cs", "sw_mcp/bridge.py", "sw_mcp/startup.py", "scripts/self_check.py", "motion_server.py")}}
    output = ROOT / "runs/quanzhou-fix-native.json"
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    executable = Path(os.environ.get("SW_INSTALL_DIR", r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS")) / "SLDWORKS.exe"
    startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
    if processes():
        raise RuntimeError("A user process started during preparation; abort")
    owned = subprocess.Popen([str(executable)], startupinfo=startup)
    report["owned_solidworks_pid"] = owned.pid
    report["owned_started_at_utc"] = datetime.now(timezone.utc).isoformat()
    save(); print("OWNED_SOLIDWORKS_STARTED", owned.pid, flush=True)
    env = {**os.environ, "SW_MCP_PROCESS_ID": str(owned.pid), "PYTHONIOENCODING": "utf-8"}
    try:
        deadline = time.monotonic() + 180
        attempts = []
        while True:
            if owned.poll() is not None:
                raise RuntimeError("Owned SolidWorks exited during startup")
            connected = subprocess.run([str(folder / "executor/bin/SwExecutor.exe"), "check-connection"],
                                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=25)
            response = json.loads(connected.stdout)
            if response.get("ready"):
                assert response["process_id"] == owned.pid
                report["read_only_connection"] = response
                break
            code = response["error"]["code"]; attempts.append(code)
            report["startup_errors"] = attempts
            report["last_startup_error"] = response
            save()
            assert code in {"COM_SESSION_NOT_FOUND", "COM_SESSION_UNAVAILABLE"}, response
            if time.monotonic() >= deadline:
                raise TimeoutError("COM startup deadline exceeded")
            await asyncio.sleep(2)
        report["startup_errors"] = attempts
        report.pop("last_startup_error", None)
        subprocess.run([sys.executable, str(ROOT / "tests/session_connection_checks.py"), "--solidworks-pid", str(owned.pid)], check=True, timeout=55)
        report["native_policy_probe"] = json.loads((ROOT / "runs/session-connection-native.json").read_text(encoding="utf-8"))
        assert report["native_policy_probe"]["all_passed"]
        save(); print("NATIVE_PID_AND_ACTIVEOBJECT_POLICY_PASS", flush=True)
        check = subprocess.run([sys.executable, str(folder / "scripts/self_check.py"), "--connect"],
                               env=env, capture_output=True, text=True, encoding="utf-8", timeout=55)
        report["self_check"] = json.loads(check.stdout)
        assert check.returncode == 0 and report["self_check"]["connection_checked"]
        assert report["self_check"]["environment"]["solidworks_process_id"] == owned.pid
        assert report["self_check"]["environment"]["version"] == VERSION
        async with Client(StdioServerParameters(command=sys.executable, args=[str(folder / "motion_server.py")], cwd=folder,
                    env={"SW_MCP_PROCESS_ID": str(owned.pid), "PYTHONIOENCODING": "utf-8"})) as client:
            tools = await client.list_tools(); assert len(tools.tools) == 24
            assert client.server_info.name == "SolidWorks ClashMate MechDog" and client.server_info.version == VERSION
            response = await client.call_tool("get_environment", {})
            assert not response.is_error and response.structured_content["result"]["solidworks_process_id"] == owned.pid, response
            assert response.structured_content["result"]["version"] == VERSION
            report["mcp"] = {"tool_count": len(tools.tools), "serverInfo": client.server_info.model_dump(by_alias=True, exclude_none=True), "environment": response.structured_content}
        state = folder / "runs/executor-state.json"
        unchanged = state.read_bytes()
        async with Client(StdioServerParameters(command=sys.executable, args=[str(folder / "motion_server.py")], cwd=folder,
                    env={"SW_MCP_PROCESS_ID": str(owned.pid + 1), "PYTHONIOENCODING": "utf-8"})) as client:
            response = await client.call_tool("get_environment", {})
            assert response.is_error and response.structured_content["error"]["code"] == "COM_SESSION_ID_MISMATCH", response
            report["wrong_pid_mcp"] = response.structured_content
        assert state.read_bytes() == unchanged
        report["wrong_pid_no_request_dispatch"] = True
        assert journal_hash() == preserved
        report["protected_journal_sha256_after"] = journal_hash()
        assert owned.poll() is None
        print("SELF_CHECK_AND_REAL_MCP_PASS", flush=True)
        probe = Path(report["native_policy_probe"]["test_executable"])
        close = subprocess.run([str(probe), "--close-owned", str(owned.pid)], capture_output=True, text=True, encoding="utf-8", timeout=25, check=True)
        report["owned_cleanup"] = close.stdout.strip()
        owned.wait(timeout=35)
        report["owned_solidworks_exit_code"] = owned.returncode
        assert journal_hash() == preserved
        report["all_passed"] = True
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        report["owned_process_still_alive"] = owned.poll() is None
        raise
    finally:
        save()
    print("NATIVE_CONNECTION_ACCEPTANCE_PASS", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
