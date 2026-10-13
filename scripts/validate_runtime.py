"""Validate an existing venv without modifying or deleting it."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

PROBE = "import json,sys,struct; print(json.dumps(dict(executable=sys.executable,base_executable=getattr(sys,'_base_executable',sys.executable),prefix=sys.prefix,base_prefix=sys.base_prefix,version=list(sys.version_info[:3]),bits=struct.calcsize('P')*8)))"


def identity(executable: str) -> dict:
    output = subprocess.run([executable, "-I", "-c", PROBE], capture_output=True, text=True,
                            check=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return json.loads(output.stdout)


def validate(selected: dict, actual: dict, venv: Path) -> None:
    for runtime in (selected, actual):
        if runtime["bits"] != 64 or tuple(runtime["version"]) < (3, 11):
            raise ValueError("64-bit Python 3.11+ required")
    if Path(actual["prefix"]).resolve() != venv.resolve() or actual["prefix"] == actual["base_prefix"]:
        raise ValueError("Project Python is not the expected virtual environment")
    if (tuple(selected["version"]) != tuple(actual["version"])
            or Path(selected["base_executable"]).resolve() != Path(actual["base_executable"]).resolve()):
        raise ValueError("Existing .venv does not match -PythonPath; select its base Python, or move .venv aside explicitly before reinstalling. No files were changed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--venv", type=Path)
    args = parser.parse_args()
    result = {"ok": False}
    try:
        result["selected"] = identity(args.python)
        if result["selected"]["bits"] != 64 or tuple(result["selected"]["version"]) < (3, 11):
            raise ValueError("64-bit Python 3.11+ required")
        if result["selected"]["prefix"] != result["selected"]["base_prefix"]:
            raise ValueError("-PythonPath must select the base Python, not another virtual environment")
        if args.venv is not None:
            result["venv"] = identity(str(args.venv / "Scripts" / "python.exe"))
            validate(result["selected"], result["venv"], args.venv)
        result["ok"] = True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result["error"] = {"code": "PYTHON_RUNTIME_MISMATCH", "message": str(exc)}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
