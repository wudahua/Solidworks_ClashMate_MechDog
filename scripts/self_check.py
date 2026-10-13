"""Read-only installation checks; COM is opt-in via --connect."""
import argparse
import importlib.metadata
import json
import os
import platform
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connect", action="store_true")
    args = parser.parse_args()
    from sw_mcp.bridge import Bridge, CadError
    from sw_mcp.startup import executor_diagnostics
    try:
        mcp_version = importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        mcp_version = None
    result = {"python": platform.python_version(), "python_executable": sys.executable,
              "base_python_executable": getattr(sys, "_base_executable", sys.executable),
              "architecture_bits": struct.calcsize("P")*8, "windows": os.name == "nt", "mcp": mcp_version,
              "executor_built": (ROOT/"executor/bin/SwExecutor.exe").is_file(),
              "connection_requested": args.connect, "connection_checked": False,
              "executor": executor_diagnostics(ROOT/"executor/bin/SwExecutor.exe", stage="self_check")}
    if args.connect:
        bridge = Bridge(ROOT)
        try:
            result["environment"] = bridge.request("get_environment")
            result["connection_checked"] = True
            result["connection"] = bridge._startup.result().get("connection")
        except CadError as exc:
            result["error"] = {"code": exc.code, "message": str(exc), "diagnostics": exc.diagnostics}
        except OSError as exc:
            result["error"] = {"code": "INSTALLATION_ACCESS_FAILED", "message": str(exc),
                               "diagnostics": {"errno": exc.errno, "winerror": getattr(exc, "winerror", None)}}
        finally:
            bridge.close()
            if bridge._process:
                try:
                    bridge._process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    result["executor_shutdown_pending"] = True
                    result.setdefault("error", {"code": "EXECUTOR_SHUTDOWN_PENDING", "message": "执行器尚未退出，请保留日志并核对状态；没有强制终止。"})
    result["ok"] = bool(result["architecture_bits"] == 64 and result["windows"] and result["executor_built"] and result["mcp"] == "2.3.0" and "error" not in result and (not args.connect or result["connection_checked"]))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
