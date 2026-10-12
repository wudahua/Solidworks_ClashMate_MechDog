"""Read-only installation checks; COM is opt-in via --connect."""
import argparse
import importlib.metadata
import json
import os
import platform
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connect", action="store_true")
    args = parser.parse_args()
    result = {"python": platform.python_version(), "architecture_bits": struct.calcsize("P")*8, "windows": os.name == "nt", "mcp": importlib.metadata.version("mcp"), "executor_built": (ROOT/"executor/bin/SwExecutor.exe").is_file(), "connection_checked": args.connect}
    if args.connect:
        from sw_mcp.bridge import Bridge
        bridge = Bridge(ROOT)
        try:
            result["environment"] = bridge.request("get_environment")
        finally:
            bridge.close()
            if bridge._process:
                bridge._process.wait(timeout=20)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["architecture_bits"] == 64 and result["windows"] and result["executor_built"] and result["mcp"] == "2.3.0" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
