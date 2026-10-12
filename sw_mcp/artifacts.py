"""Bounded, read-only access to saved motion data, including quarantined runs."""
from __future__ import annotations
import base64
import csv
import hashlib
import json
import math
import re
from pathlib import Path


class ArtifactError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class Artifacts:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self._csv_cache = {}

    def _paths(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("run_id 必须是 32 位十六进制任务标识。")
        directory = self.root / "runs" / run_id
        if not directory.resolve().is_relative_to(self.root / "runs") or directory.is_symlink():
            raise ValueError("结果目录越出了本项目运行目录。")
        if not directory.is_dir():
            raise ArtifactError("RUN_NOT_FOUND", "任务目录不存在；请核对本安装目录的 run_id。")
        paths = [directory / "solve.json", directory / "component-poses.csv"]
        if any(p.is_symlink() or not p.resolve().is_relative_to(directory.resolve()) for p in paths):
            raise ValueError("结果文件不在登记的任务目录内。")
        return paths

    def _load(self, run_id):
        manifest, poses = self._paths(run_id)
        if not manifest.is_file():
            if not poses.is_file():
                raise ArtifactError("MANIFEST_MISSING", "任务目录存在，但结果清单和姿态 CSV 均缺失。")
            return {"run_id": run_id, "manifest_status": "absent", "result_validity": "inconclusive", "restoration_status": "unknown", "legacy_without_manifest": True}, manifest, poses
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except OSError as exc:
            raise ArtifactError("ARTIFACT_ACCESS_FAILED", "无法读取结果清单；请检查文件占用和访问权限。") from exc
        except (ValueError, UnicodeError) as exc:
            raise ArtifactError("MANIFEST_INVALID", "结果清单损坏；保留原文件，不自动生成替代清单。") from exc
        if not isinstance(data, dict) or data.get("run_id") != run_id:
            raise ArtifactError("MANIFEST_INVALID", "结果清单的格式或 run_id 不匹配。")
        data["manifest_status"] = "present"
        return data, manifest, poses

    def _csv_info(self, data, path):
        if not path.is_file():
            raise ArtifactError("POSES_MISSING", "任务清单存在，但没有保存完整姿态 CSV。")
        try:
            if path.stat().st_size > 100_000_000:
                raise ArtifactError("ARTIFACT_BUDGET_EXCEEDED", "姿态 CSV 超过100 MB读取预算。")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            recorded_value = data.get("poses_sha256", "")
            if not isinstance(recorded_value, str):
                raise ArtifactError("MANIFEST_INVALID", "结果清单的姿态哈希格式无效。")
            recorded = recorded_value.replace("-", "").lower()
            if recorded and recorded != digest:
                raise ArtifactError("ARTIFACT_HASH_MISMATCH", "姿态 CSV 的 SHA-256 与清单不符，不返回该文件的数据。")
            key = (str(path), digest)
            if key not in self._csv_cache:
                fields = ['frame','time_s','component_id','instance','x_m','y_m','z_m','r00','r01','r02','r10','r11','r12','r20','r21','r22']
                previous, frames, rows = {}, set(), 0
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if reader.fieldnames != fields:
                        raise ValueError("header")
                    for row in reader:
                        rows += 1
                        if rows > 100_000:
                            raise ArtifactError("ARTIFACT_BUDGET_EXCEEDED", "姿态行数超过10万条读取预算。")
                        item = self._pose_row(row)
                        identifier = item['component_id']
                        if identifier in previous and (item['frame'] <= previous[identifier][0] or item['time_s'] <= previous[identifier][1]):
                            raise ValueError("time order")
                        previous[identifier] = (item['frame'], item['time_s'])
                        frames.add(item['frame'])
                if not rows:
                    raise ValueError("empty")
                if len(self._csv_cache) >= 16:
                    self._csv_cache.clear()
                self._csv_cache[key] = {"pose_rows": rows, "frames": len(frames), "components": len(previous)}
            return {**self._csv_cache[key], "observed_poses_sha256": digest, "artifact_integrity": "verified" if recorded else "hash_not_recorded"}
        except OSError as exc:
            raise ArtifactError("ARTIFACT_ACCESS_FAILED", "无法读取姿态 CSV；请检查文件占用和访问权限。") from exc
        except ArtifactError:
            raise
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ArtifactError("POSES_INVALID", "姿态 CSV 格式、数值或时间顺序无效，不返回该文件的数据。") from exc

    @staticmethod
    def _pose_row(row):
        item = {k: v if k in {"component_id", "instance"} else int(v) if k == "frame" else float(v) for k, v in row.items()}
        if any(isinstance(v, float) and not math.isfinite(v) for v in item.values()) or item['frame'] < 0 or item['time_s'] < 0:
            raise ValueError("nonfinite or negative")
        if not item['component_id'] or not item['instance'] or len(item['component_id']) > 128 or len(item['instance']) > 512:
            raise ValueError("identity")
        return item

    def summary(self, run_id):
        data, manifest, poses = self._load(run_id)
        keys = ("run_id", "model_id", "study", "solver_status", "calculate_returned_success", "physics_validation_status", "result_validity_scope", "sampling_status", "restoration_status", "result_validity", "duration_s", "output_fps", "frames", "components", "motion_detected", "maximum_translation_from_frame0_m", "maximum_rotation_coefficient_delta_from_frame0", "input_pose_to_frame0_difference", "failure", "failure_diagnostics", "restoration_failure", "drive_validation", "validation_scope")
        info = self._csv_info(data, poses) if poses.is_file() else {}
        return {**{k: data[k] for k in keys if k in data}, **info, "manifest_status": data['manifest_status'], "legacy_without_manifest": data.get('legacy_without_manifest', False), "access": "saved_artifacts_without_COM", "current_model_validity": "not_checked_offline", "manifest_path": str(manifest) if manifest.is_file() else None, "poses_available": poses.is_file(), "poses_csv": str(poses) if poses.is_file() else None}

    def poses(self, run_id, component_id="", frame_start=0, limit=20, cursor=""):
        if type(limit) is not int or not 1 <= limit <= 50 or type(frame_start) is not int or frame_start < 0:
            raise ValueError("limit 须在 1–50，frame_start 须为非负整数。")
        data, _, path = self._load(run_id)
        info = self._csv_info(data, path)
        digest = info['observed_poses_sha256']
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
                item = self._pose_row(row)
                if len(rows) == limit or rows and len(json.dumps(rows + [item], ensure_ascii=False).encode("utf-8")) > 15000:
                    more = True
                    break
                rows.append(item)
        next_cursor = base64.b64encode(json.dumps({**identity, "offset": offset+len(rows)}).encode()).decode() if more else None
        return {"run_id": run_id, "result_validity": data.get("result_validity", "inconclusive"), "restoration_status": data.get("restoration_status", "unknown"), "manifest_status": data['manifest_status'], "legacy_without_manifest": data.get('legacy_without_manifest', False), "current_model_validity": "not_checked_offline", **info, "rows": rows, "returned": len(rows), "next_cursor": next_cursor, "access": "saved_artifacts_without_COM"}
