"""Create a source-only release by explicit allowlist; no CAD or local run data."""
import hashlib
import json
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.1-alpha.2"


def build():
    sources = [ROOT/name for name in ("README.md", "发布说明_v0.4.1-alpha.2.md", "LICENSE", ".gitignore", "requirements.txt", "requirements.lock.txt", "motion_server.py", "mcp-config.example.json", "install.ps1", "start.ps1", "初始化环境.ps1", "启动MCP.ps1", "生成运动示例.ps1")]
    sources += sorted((ROOT/"executor").glob("*.cs"))
    sources += [ROOT/"executor/build.ps1"]
    sources += sorted((ROOT/"sw_mcp").glob("*.py"))
    sources += [ROOT/"scripts"/name for name in ("self_check.py", "validate_runtime.py", "build_release.py", "recover.py")]
    sources += [ROOT/"tests"/name for name in ("test_service.py", "test_reliability.py", "motion_acceptance_v04.py", "motion_protocol_v04.py", "motion_recovery_v04.py", "motion_source_revision_v04.py", "motion_reliability_v04.py", "motion_reset_recovery_v04.py", "motion_time_axis_v04.py", "candidate_geometry_v04.py", "study_history_v04.py", "motion_startup_retry_v04.py", "motion_history_v04.py", "motion_feature_evidence_v04.py", "motion_history_diagnostics_v04.py", "motion_intent_v041.py", "basic_mates_v041.py", "mate_protocol_v041.py")]
    sources += [ROOT/"tests"/name for name in ("test_installation.py", "SessionConnectionTests.cs", "session_connection_checks.py", "session_connection_native.py", "installation_powershell_checks.py")]
    releases = ROOT/"releases"
    releases.mkdir(exist_ok=True)
    stage = releases/("SolidWorks运动仿真MCP_v"+VERSION+"_源码_"+uuid.uuid4().hex[:8])
    stage.mkdir()
    manifest = []
    for source in sources:
        relative = source.relative_to(ROOT)
        assert source.is_file() and not source.is_symlink()
        data = source.read_bytes()
        assert b"C:\\Users\\Administrator" not in data and b"E:\\Codex Space" not in data
        target = stage/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append({"path": relative.as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    # Compatibility alias for clients accustomed to server.py; public tools only.
    alias = b'from motion_server import mcp\n\nif __name__ == "__main__":\n    mcp.run(transport="stdio")\n'
    (stage/"server.py").write_bytes(alias)
    manifest.append({"path": "server.py", "bytes": len(alias), "sha256": hashlib.sha256(alias).hexdigest()})
    (stage/"发布清单.json").write_text(json.dumps({"version": VERSION, "kind": "source_only", "includes_user_cad": False, "includes_runtime_data": False, "includes_solidworks_binaries": False, "files": manifest}, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = releases/("SolidWorks运动仿真MCP_v"+VERSION+"_发布包.zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for file in sorted(stage.rglob("*")):
            if file.is_file(): z.write(file, (Path("SolidWorksMotionMCP")/file.relative_to(stage)).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest+"  "+archive.name+"\n", encoding="utf-8")
    result = {"version": VERSION, "directory": str(stage), "archive": str(archive), "sha256": digest, "source_files": len(manifest), "zip_members": len(manifest)+1, "bytes": archive.stat().st_size}
    (releases/"最新发布包.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": build()
