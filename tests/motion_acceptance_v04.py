"""Real SOLIDWORKS tests against project-generated examples; never user CAD assets."""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sw_mcp.bridge import Bridge, CadError


def main(manifest):
    sources = json.loads(Path(manifest).read_text(encoding="utf-8-sig"))
    if "assemblies" in sources:
        sources = sources["assemblies"]
    report = {"cases": [], "all_passed": False}
    output = ROOT / "runs" / "motion-acceptance-v04.json"
    bridge = Bridge(ROOT)

    def record(name, data):
        report["cases"].append({"name": name, "passed": True, "evidence": data})
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(name, "PASS", flush=True)

    try:
        for kind in ("rotary", "linear"):
            model = bridge.request("import_assembly", path=sources[kind])
            assert model["preflight"]["ready"]
            record(kind + "_import", model)
            identifier = model["model_id"]
            candidates = bridge.request("list_drive_candidates", model_id=identifier)
            candidate = next(c for c in candidates["entities"] if c["suggested_motor"] == kind and (kind == "rotary" or abs(c["axis_global"][0]) > .99))
            created = bridge.request("create_motion_study", model_id=identifier, study="Public_"+kind, component_id=candidate["component_id"], entity_id=candidate["entity_id"], motor_type=kind, speed=12 if kind == "rotary" else 10, reverse_direction=False)
            record(kind + "_create", created)
            solved = bridge.request("run_user_study", model_id=identifier, study=created["study"], duration_s=1, output_fps=30, run_id=uuid.uuid4().hex)
            assert solved["frames"] == 31 and solved["drive_validation"]["absolute_magnitude_error"] < .001
            record(kind + "_solve", solved)
            curve = bridge.request("export_motion_curve", run_id=solved["run_id"], component_id=candidate["component_id"], quantity="angular_velocity" if kind == "rotary" else "linear_velocity", axis="magnitude")
            expected = 12*2*3.141592653589793/60 if kind == "rotary" else .01
            assert abs(curve["min"]-expected) < 1e-5 and abs(curve["max"]-expected) < 1e-5, curve
            record(kind + "_curve", curve)
            record(kind + "_replay", bridge.request("replay_motion_frame", run_id=solved["run_id"], frame=15))
            checkpoint = bridge.request("create_model_checkpoint", model_id=identifier)
            restored = bridge.request("restore_model_checkpoint", model_id=identifier, checkpoint_id=checkpoint["checkpoint_id"])
            assert restored["maximum_transform_delta"] < 1e-7
            record(kind + "_checkpoint", restored)
            try:
                bridge.request("get_motion_summary", run_id=solved["run_id"])
                raise AssertionError("stale run accepted")
            except CadError as exc:
                assert exc.code == "MODEL_REVISION_CHANGED", exc.code
                record(kind + "_stale_rejected", {"code": exc.code})
            reopened = bridge.request("run_user_study", model_id=identifier, study=created["study"], duration_s=1, output_fps=30, run_id=uuid.uuid4().hex)
            assert reopened["drive_validation"]["absolute_magnitude_error"] < .001
            record(kind + "_reopened_solve", reopened)
        fixed = bridge.request("import_assembly", path=sources["fixed"])
        assert not fixed["preflight"]["ready"] and "ALL_COMPONENTS_FIXED" in fixed["preflight"]["blockers"]
        record("all_fixed_rejected", fixed)
        report["all_passed"] = True
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "code": getattr(exc, "code", ""), "message": str(exc)}
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        bridge.close()
        if bridge._process:
            bridge._process.wait(timeout=20)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1])
