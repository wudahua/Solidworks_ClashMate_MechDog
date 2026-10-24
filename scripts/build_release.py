"""Create a source-only release by explicit allowlist; no CAD or local run data."""
import argparse
import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from verify_release import verify

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.4.3-alpha.8"


def build(candidate=False):
    sources = [ROOT/name for name in ("README.md", "发布说明_v0.4.3-alpha.8.md", "LICENSE", ".gitignore", ".gitattributes", ".editorconfig", "requirements.txt", "requirements.lock.txt", "motion_server.py", "mcp-config.example.json", "install.ps1", "start.ps1", "upgrade.ps1", "初始化环境.ps1", "启动MCP.ps1", "生成运动示例.ps1")]
    sources += sorted((ROOT/"executor").glob("*.cs"))
    sources += [ROOT/"executor/build.ps1"]
    sources += sorted((ROOT/"sw_mcp").glob("*.py"))
    sources += sorted(p for p in (ROOT/'sw_mcp/conversation').iterdir() if p.is_file() and p.suffix in {'.py','.ps1','.cs'})
    sources += [ROOT/'tests'/name for name in ('test_conversation_tasks.py','test_conversation_runtime.py','test_conversation_orphan.py','test_conversation_motion.py','dialogue_client.py','dialogue_native.py','dialogue_lifecycle.py','dialogue_fixture_owner.py','dialogue_fixture_frontend.py')]
    sources += [ROOT/"scripts"/name for name in ("self_check.py", "validate_runtime.py", "install_preflight.py", "build_release.py", "verify_release.py", "upgrade.py", "recover.py", "local_storage.py", "lease_access.py")]
    sources += [ROOT/"tests"/name for name in ("test_service.py", "test_reliability.py", "motion_acceptance_v04.py", "motion_protocol_v04.py", "motion_recovery_v04.py", "motion_source_revision_v04.py", "motion_reliability_v04.py", "motion_reset_recovery_v04.py", "motion_time_axis_v04.py", "candidate_geometry_v04.py", "study_history_v04.py", "motion_startup_retry_v04.py", "motion_history_v04.py", "motion_feature_evidence_v04.py", "motion_history_diagnostics_v04.py", "motion_intent_v041.py", "basic_mates_v041.py", "mate_protocol_v041.py")]
    sources += [ROOT/"tests"/name for name in ("test_installation.py", "SessionConnectionTests.cs", "session_connection_checks.py", "session_connection_native.py", "installation_powershell_checks.py")]
    sources += [ROOT/"tests"/name for name in ("relative_motion_checks.py", "test_mechanism_feedback.py", "mechanism_protocol_checks.py")]
    sources += [ROOT/"tests/test_clock_feedback.py", ROOT/"tests/test_release_feedback.py"]
    sources += [ROOT/"tests"/name for name in ("transport_cleanup.py", "test_qzc_feedback.py", "qzc_evidence_checks.py", "recovery_evidence_checks.py", "qzc_protocol_checks.py")]
    sources += [ROOT/"tests/clock_time_selection_checks.py"]
    sources += [ROOT/"tests"/name for name in ("test_alpha5.py", "alpha5_evidence_checks.py", "alpha5_native_checks.py")]
    sources += [ROOT/"tests"/name for name in ("test_kulisse_feedback.py", "kulisse_evidence_checks.py", "virtual_import_native_checks.py", "kulisse_protocol_checks.py", "virtual_import_matrix_checks.py", "checkpoint_probe_native_checks.py", "test_checkpoint_preparation.py")]
    sources += [ROOT/".github/workflows/release-validation.yml"]
    sources += [ROOT/"tests"/name for name in ("test_v042a5.py", "v042a5_policy_checks.py", "v042a5_short_native.py", "v042a5_query_native.py", "v042a5_reset_native.py", "run_offline_policies.py")]
    sources += [ROOT/"tests/test_v042a6.py", ROOT/"tests/grid_protocol_checks.py"]
    sources += [ROOT/"tests/test_v043a0.py", ROOT/"tests/v043a0_policy_checks.py", ROOT/"tests/v043a0_timing_native.py"]
    sources += [ROOT/"tests/test_v043a1.py", ROOT/"tests/test_v043a2.py", ROOT/"tests/test_v043a3.py", ROOT/"tests/v043a3_performance_native.py", ROOT/"tests/test_v043a4.py", ROOT/"tests/v043a4_pagination_native.py"]
    sources += [ROOT/"tests/test_v043a6.py", ROOT/"tests/v043a6_performance_native.py"]
    sources += [ROOT/"tests/test_v042a9.py", ROOT/"tests/test_v043a5.py", ROOT/"tests/v043a5_observation_native.py"]
    sources += [ROOT/"tests/check_entrypoints.py"]
    sources += [ROOT/"tests/test_v042a8.py", ROOT/"tests/v042a8_policy_checks.py", ROOT/"tests/v042a8_performance_native.py", ROOT/"tests/upgrade_powershell_checks.py"]
    sources += [ROOT/"tests/test_v042a7.py", ROOT/"tests/v042a7_policy_checks.py", ROOT/"tests/v042a7_performance_native.py"]
    sources += [ROOT/"tests/test_v042a4.py", ROOT/"tests/v042a4_reset_native.py", ROOT/"tests/v042a4_query_native.py", ROOT/"tests/v042a4_performance_native.py"]
    sources += [ROOT/"tests/v042a3_query_native.py", ROOT/"tests/test_v042a3.py", ROOT/"tests/v042a3_reset_native.py", ROOT/"tests/v042a3_policy_checks.py"]
    sources += [ROOT/"tests/test_v042a2.py", ROOT/"tests/v042a2_snapshot_native.py", ROOT/"tests/v042a2_policy_checks.py"]
    sources += [ROOT/"tests/test_alpha8.py", ROOT/"tests/alpha8_policy_checks.py", ROOT/"tests/alpha8_native_checks.py"]
    sources += [ROOT/"tests/alpha9_policy_checks.py", ROOT/"tests/alpha9_native_checks.py"]
    sources += [ROOT/"tests"/name for name in ("v042a1_policy_checks.py", "v042a1_checkpoint_native_checks.py", "v042a1_archived_checkpoint_native.py", "v042a1_performance_native.py")]
    sources += [ROOT/"tests"/name for name in ("test_v042.py", "v042_policy_checks.py", "v042_motor_native_checks.py", "v042_checkpoint_native_checks.py")]
    sources += [ROOT/"tests/test_alpha7.py", ROOT/"tests/alpha7_native_checks.py", ROOT/"tests/axis_convention_checks.py"]
    releases = ROOT/"releases"
    releases.mkdir(exist_ok=True)
    stage = releases/("Solidworks_ClashMate_MechDog_v"+VERSION+("_本地候选源码_" if candidate else "_源码_")+uuid.uuid4().hex[:8])
    stage.mkdir()
    manifest = []
    for source in sources:
        relative = source.relative_to(ROOT)
        assert source.is_file() and not source.is_symlink()
        data = source.read_bytes()
        if b"\r" in data: raise ValueError("Release text must use LF: "+relative.as_posix())
        normalized = data.decode("utf-8-sig").replace("\\\\", "\\").replace("\\", "/").casefold()
        for private_root in (ROOT, Path.home()):
            assert private_root.as_posix().casefold() not in normalized, relative
        target = stage/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append({"path": relative.as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    # Compatibility alias for clients accustomed to server.py; public tools only.
    alias = b'from motion_server import main\n\nif __name__ == "__main__":\n    main()\n'
    (stage/"server.py").write_bytes(alias)
    previous_alias=ROOT/"server.py"
    if previous_alias.exists() and previous_alias.read_bytes()!=alias:
        backup=ROOT/"runs"/("server-before-alpha5-"+hashlib.sha256(previous_alias.read_bytes()).hexdigest()[:12]+".py")
        backup.parent.mkdir(exist_ok=True)
        if not backup.exists(): backup.write_bytes(previous_alias.read_bytes())
    previous_alias.write_bytes(alias)
    manifest.append({"path": "server.py", "bytes": len(alias), "sha256": hashlib.sha256(alias).hexdigest()})
    (stage/"发布清单.json").write_text(json.dumps({"version": VERSION, "kind": "source_only", "text_line_endings": "LF", "includes_user_cad": False, "includes_runtime_data": False, "includes_solidworks_binaries": False, "files": manifest, "distribution_status": "local_candidate" if candidate else "release_package"}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    verify(stage)
    (ROOT/"发布清单.json").write_bytes((stage/"发布清单.json").read_bytes())
    archive = releases/("Solidworks_ClashMate_MechDog_v"+VERSION+("_本地候选包_"+stage.name.rsplit('_',1)[-1]+".zip" if candidate else "_source.zip"))
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for file in sorted(stage.rglob("*")):
            if file.is_file(): z.write(file, (Path("Solidworks_ClashMate_MechDog")/file.relative_to(stage)).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest+"  "+archive.name+"\n", encoding="utf-8", newline="\n")
    result = {"version": VERSION, "directory": str(stage), "archive": str(archive), "sha256": digest, "source_files": len(manifest), "zip_members": len(manifest)+1, "bytes": archive.stat().st_size}
    if candidate: result.update(published=False, distribution_status="local_candidate")
    metadata = releases/("本地候选包信息_v"+VERSION+".json" if candidate else "最新发布包.json")
    metadata.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--candidate",action="store_true",help="Build a local candidate without replacing the latest release pointer");args=parser.parse_args();build(candidate=args.candidate)
