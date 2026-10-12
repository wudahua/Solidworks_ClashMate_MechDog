"""Bounded, read-only access to saved motion data, including quarantined runs."""
from __future__ import annotations
import base64
import csv
import hashlib
import json
import math
import re
from pathlib import Path


class Artifacts:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _paths(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("run_id 必须是 32 位十六进制任务标识。")
        directory = self.root / "runs" / run_id
        if not directory.resolve().is_relative_to(self.root / "runs") or directory.is_symlink():
            raise ValueError("结果目录越出了本项目运行目录。")
        paths = [directory / "solve.json", directory / "component-poses.csv"]
        if any(p.is_symlink() or not p.resolve().is_relative_to(directory.resolve()) for p in paths):
            raise ValueError("结果文件不在登记的任务目录内。")
        return paths

    def _load(self, run_id):
        manifest, poses = self._paths(run_id)
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if data.get("run_id") != run_id:
            raise ValueError("结果清单的 run_id 不匹配。")
        return data, manifest, poses

    def summary(self, run_id):
        data, manifest, poses = self._load(run_id)
        keys = ("run_id", "model_id", "study", "solver_status", "sampling_status", "restoration_status", "result_validity", "duration_s", "output_fps", "frames", "components", "motion_detected", "maximum_translation_from_frame0_m", "maximum_rotation_coefficient_delta_from_frame0", "input_pose_to_frame0_difference", "failure", "restoration_failure", "drive_validation", "validation_scope")
        return {**{k: data[k] for k in keys if k in data}, "access": "saved_artifacts_without_COM", "current_model_validity": "not_checked_offline", "manifest_path": str(manifest), "poses_available": poses.is_file(), "poses_csv": str(poses) if poses.is_file() else None}

    def poses(self, run_id, component_id="", frame_start=0, limit=20, cursor=""):
        if type(limit) is not int or not 1 <= limit <= 50 or type(frame_start) is not int or frame_start < 0:
            raise ValueError("limit 须在 1–50，frame_start 须为非负整数。")
        data, _, path = self._load(run_id)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        recorded = data.get("poses_sha256", "").replace("-", "").lower()
        if recorded and recorded != digest:
            raise ValueError("姿态 CSV 的 SHA-256 与清单不符，不返回该文件的数据。")
        offset = 0
        identity = {"run_id": run_id, "component_id": component_id, "frame_start": frame_start, "sha256": digest}
        if cursor:
            try:
                token = json.loads(base64.b64decode(cursor, validate=True))
                if any(token.get(k) != v for k, v in identity.items()):
                    raise ValueError()
                offset = token["offset"]
                if type(offset) is not int or offset < 0:
                    raise ValueError()
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("游标已过期或过滤条件改变，请从第一页读取。") from exc
        rows, seen, more = [], 0, False
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if int(row["frame"]) < frame_start or component_id and row["component_id"] != component_id:
                    continue
                seen += 1
                if seen <= offset:
                    continue
                item = {k: v if k in {"component_id", "instance"} else int(v) if k == "frame" else float(v) for k, v in row.items()}
                if any(isinstance(v, float) and not math.isfinite(v) for v in item.values()):
                    raise ValueError("保存的姿态包含非有限数值。")
                if len(rows) == limit or rows and len(json.dumps(rows + [item], ensure_ascii=False).encode("utf-8")) > 15000:
                    more = True
                    break
                rows.append(item)
        next_cursor = base64.b64encode(json.dumps({**identity, "offset": offset+len(rows)}).encode()).decode() if more else None
        return {"run_id": run_id, "result_validity": data.get("result_validity", "inconclusive"), "restoration_status": data.get("restoration_status", "unknown"), "current_model_validity": "not_checked_offline", "artifact_integrity": "verified" if recorded else "hash_not_recorded", "rows": rows, "returned": len(rows), "next_cursor": next_cursor, "access": "saved_artifacts_without_COM"}
