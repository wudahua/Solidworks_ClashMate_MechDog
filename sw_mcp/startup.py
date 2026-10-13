"""Local executor diagnostics; inspecting an executable never starts CAD."""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


def executor_diagnostics(exe: Path, *, stage: str, error: OSError | None = None) -> dict:
    result = {"stage": stage, "executor_path": str(exe), "python_executable": sys.executable,
              "host_pid": os.getpid(), "parent_pid": os.getppid(), "working_directory": str(exe.parents[2])}
    if error is not None:
        result.update(error_type=type(error).__name__, native_message=str(error),
                      errno=error.errno, winerror=getattr(error, "winerror", None))
    try:
        info = exe.stat()
        result.update(executor_exists=True, executor_is_file=stat.S_ISREG(info.st_mode),
                      executor_bytes=info.st_size, executor_modified_at_ns=info.st_mtime_ns)
        if result["executor_is_file"]:
            with exe.open("rb") as stream:
                result["executor_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        result["executor_exists"] = False if isinstance(exc, FileNotFoundError) else None
        result["inspection_error"] = {"type": type(exc).__name__, "errno": exc.errno,
                                      "winerror": getattr(exc, "winerror", None)}
    manifest = exe.with_name("build-manifest.json")
    try:
        if manifest.stat().st_size > 65536:
            raise ValueError("Build manifest exceeds size limit")
        recorded = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if not isinstance(recorded, dict):
            raise ValueError("Invalid build manifest")
        result["build_record"] = recorded
        result["matches_build_record"] = (result.get("executor_sha256") == recorded.get("executor_sha256")) if result.get("executor_sha256") else None
    except FileNotFoundError:
        result["build_record_status"] = "absent"
    except (OSError, ValueError):
        result["build_record_status"] = "unreadable"
    return result
