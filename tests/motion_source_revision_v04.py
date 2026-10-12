"""An externally revised project-generated source must not block its frozen copy."""
import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sw_mcp.bridge import Bridge


def main(model_id):
    directory = ROOT/"experiments/user_assemblies"/model_id.removeprefix("user_")
    metadata = json.loads((directory/"model.json").read_text(encoding="utf-8"))
    source = next(Path(p) for p in metadata["SourceHashes"] if p.lower().endswith(".sldasm"))
    assert source.resolve().is_relative_to((ROOT/"examples/generated").resolve())
    assert not source.is_symlink()
    original = source.read_bytes()
    bridge = Bridge(ROOT)
    report = {"all_passed": False}
    try:
        checkpoint = bridge.request("create_model_checkpoint", model_id=model_id)
        # The replacement is valid CAD produced by this project. It only affects a
        # disposable generated source, and its original bytes are restored finally.
        replacement = Path(metadata["Path"]).read_bytes()
        assert replacement != original
        source.write_bytes(replacement)
        first = bridge.request("run_user_study", model_id=model_id, study="Public_rotary", duration_s=1, output_fps=30, run_id=uuid.uuid4().hex)
        assert not first["source_files_unchanged"] and first["restoration_status"] == "restored"
        restored = bridge.request("restore_model_checkpoint", model_id=model_id, checkpoint_id=checkpoint["checkpoint_id"])
        assert not restored["source_files_unchanged"] and restored["restoration_status"] == "restored"
        assert not bridge.recovery_state()["recovery_required"]
        report.update(all_passed=True, solved_imported_copy=True, restored_imported_copy=True, source_hash_difference_reported=True, restore_transform_delta=restored["maximum_transform_delta"])
    finally:
        source.write_bytes(original)
        assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(original).digest()
        report["generated_source_original_bytes_restored"] = True
        bridge.close()
        if bridge._process: bridge._process.wait(timeout=20)
        (ROOT/"runs/motion-source-revision-v04.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("EXTERNAL_GENERATED_SOURCE_REVISION PASS", flush=True)


if __name__ == "__main__": main(sys.argv[1])
