"""Compile and exercise production COM selection policy; native probe is opt-in."""
import argparse
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--solidworks-pid", type=int)
    args = parser.parse_args()
    folder = ROOT / "runs" / "session-connection-tests" / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    redist = Path(os.environ.get("SW_INSTALL_DIR", r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS")) / "api" / "redist"
    interop = folder / "SolidWorks.Interop.sldworks.dll"
    shutil.copy2(redist / interop.name, interop)
    exe = folder / "ConnectionTests.exe"
    subprocess.run([str(Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"),
                    "/nologo", "/platform:x64", "/reference:System.Web.Extensions.dll", "/reference:" + str(interop),
                    "/out:" + str(exe), str(ROOT / "executor/CadFault.cs"), str(ROOT / "executor/SessionConnection.cs"),
                    str(ROOT / "tests/SessionConnectionTests.cs")], check=True)
    command = [str(exe)]
    if args.solidworks_pid is not None:
        if args.solidworks_pid <= 0:
            raise ValueError("Positive SolidWorks PID required")
        command += ["--live", str(args.solidworks_pid)]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=45, check=True)
    report = json.loads(completed.stdout)
    report["cad_connection_used"] = args.solidworks_pid is not None
    report["test_executable"] = str(exe)
    output = ROOT / "runs" / ("session-connection-native.json" if args.solidworks_pid else "session-connection-offline.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
