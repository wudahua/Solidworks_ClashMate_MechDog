"""Exercise real Windows PowerShell installer entry points without network/CAD.

Fresh venv uses a test pip module that records arguments instead of installing.
The production installer and runtime validator are used without modification.
"""
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(folder):
    folder.mkdir(parents=True)
    for name in ("install.ps1", "初始化环境.ps1", "requirements.lock.txt"):
        shutil.copy2(ROOT / name, folder / name)
    (folder / "scripts").mkdir()
    for name in ('validate_runtime.py','install_preflight.py'):
        shutil.copy2(ROOT / 'scripts' / name, folder / 'scripts' / name)
    redist=folder/'test-sw/api/redist';redist.mkdir(parents=True)
    for name in ('sldworks','swconst','swmotionstudy'):
        (redist/('SolidWorks.Interop.'+name+'.dll')).write_bytes(b'fixture only; fake build never reads DLL')
    (folder / "executor").mkdir()
    (folder / "executor/build.ps1").write_text("Add-Content -LiteralPath (Join-Path $PSScriptRoot '../build-called.txt') -Value 'called'\n", encoding="ascii")


def invoke(folder, entry, index):
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(folder / entry),
                           "-PythonPath", sys._base_executable, "-PipIndexUrl", index,"-SolidWorksInstallDir",str(folder/"test-sw")],
                          capture_output=True, text=True, errors="replace", timeout=40)


def main():
    folder = ROOT / "runs/powershell-install-tests" / uuid.uuid4().hex[:8]
    prepare(folder)
    subprocess.run([sys._base_executable, "-m", "venv", "--without-pip", str(folder / ".venv")], check=True, timeout=30)
    fake = folder / ".venv/Lib/site-packages/pip"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("", encoding="ascii")
    (fake / "__main__.py").write_text("import json,sys\nfrom pathlib import Path\nwith (Path(sys.prefix).parent/'pip-calls.jsonl').open('a',encoding='utf-8') as out: out.write(json.dumps(sys.argv[1:])+'\\n')\n", encoding="ascii")
    report = {"all_passed": False, "test_root": str(folder), "network_used": False, "cad_connection_used": False, "cases": []}
    blocked = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Restricted", "-Command", "& '" + str(folder / "install.ps1") + "'"], capture_output=True, text=True, errors="replace", timeout=20)
    assert blocked.returncode != 0 and not (folder / "pip-calls.jsonl").exists()
    report["cases"].append("Restricted blocks direct script invocation")
    mirror = "https://example.invalid/simple"
    successful = invoke(folder, "install.ps1", mirror)
    assert successful.returncode == 0, successful.stdout + successful.stderr
    calls = [json.loads(line) for line in (folder / "pip-calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 1 and calls[0][:4] == ["--isolated", "install", "--index-url", mirror]
    assert "--trusted-host" not in calls[0] and "-r" in calls[0]
    report["cases"].append("Process Bypass installer passes locked requirements and selected HTTPS mirror to pip")
    wrapper = invoke(folder, "初始化环境.ps1", "https://pypi.org/simple")
    assert wrapper.returncode == 0, wrapper.stdout + wrapper.stderr
    calls = [json.loads(line) for line in (folder / "pip-calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 2 and calls[1][3] == "https://pypi.org/simple"
    report["cases"].append("Chinese compatibility entry forwards parameters in Windows PowerShell 5.1")
    before = (folder / "pip-calls.jsonl").read_bytes()
    for index in ("http://example.invalid/simple", "https://name:password@example.invalid/simple", "not-a-url", "https://example.invalid/simple?token=secret"):
        denied = invoke(folder, "install.ps1", index)
        assert denied.returncode != 0 and (folder / "pip-calls.jsonl").read_bytes() == before
    report["cases"].append("Invalid or credential-bearing index rejected before pip")
    incomplete = folder / "incomplete"
    prepare(incomplete); (incomplete / ".venv").mkdir()
    sentinel = incomplete / ".venv/preserve.txt"; sentinel.write_bytes(b"keep existing files")
    denied = invoke(incomplete, "install.ps1", "https://pypi.org/simple")
    assert denied.returncode != 0 and sentinel.read_bytes() == b"keep existing files"
    assert not (incomplete / "build-called.txt").exists()
    report["cases"].append("Incomplete venv stops installation without deleting or overwriting files")
    report["all_passed"] = True
    report["checks"] = len(report["cases"])
    (ROOT / "runs/quanzhou-fix-powershell.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
