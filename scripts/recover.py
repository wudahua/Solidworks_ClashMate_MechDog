"""Official recovery CLI; never clears an unknown journal without restoring a checkpoint."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sw_mcp.bridge import Bridge, CadError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("inspect", "restore", "reconcile-missing-identity"))
    parser.add_argument("--model-id", default="")
    parser.add_argument("--checkpoint-id", default="")
    parser.add_argument("--solidworks-pid", type=int)
    parser.add_argument("--allow-replacement-session", action="store_true")
    parser.add_argument("--journal-sha256", default="")
    parser.add_argument("--confirm-operation-ended", action="store_true", help="Human operator has checked that CAD is idle and the old operation ended; a timeout is insufficient.")
    args = parser.parse_args()
    bridge = Bridge(ROOT)
    try:
        if args.action == "inspect":
            path = ROOT / "runs/executor-state.json"
            result = {"state": bridge.recovery_state(), "journal_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None, "diagnosis_only_no_COM": True}
        else:
            if not args.model_id or not args.checkpoint_id:
                parser.error("--model-id and --checkpoint-id are required")
            if args.solidworks_pid:
                os.environ["SW_MCP_PROCESS_ID"] = str(args.solidworks_pid)
            if args.action == "restore":
                result = bridge.request("restore_model_checkpoint", model_id=args.model_id, checkpoint_id=args.checkpoint_id, allow_replacement_session=args.allow_replacement_session)
            else:
                if not args.solidworks_pid or not args.journal_sha256 or not args.confirm_operation_ended:
                    parser.error("Manual reconciliation requires --solidworks-pid, --journal-sha256 and --confirm-operation-ended")
                result = bridge.reconcile_missing_identity(model_id=args.model_id, checkpoint_id=args.checkpoint_id, solidworks_pid=args.solidworks_pid, journal_sha256=args.journal_sha256, operation_ended_confirmed=args.confirm_operation_ended)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (CadError, ValueError, OSError) as exc:
        print(json.dumps({"ok": False, "code": getattr(exc, "code", "RECOVERY_INPUT_ERROR"), "message": str(exc), "restoration_status": getattr(exc, "restoration_status", "unknown"), "diagnostics": getattr(exc, "diagnostics", {})}, ensure_ascii=False, indent=2))
        return 1
    finally:
        bridge.close()
        if bridge._process:
            try:
                bridge._process.wait(timeout=20)
            except Exception:
                pass  # Never terminate CAD or a potentially busy executor.
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
