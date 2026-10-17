from __future__ import annotations

import concurrent.futures
import copy
import json
import threading
import time
import uuid
import re
from pathlib import Path

from .bridge import Bridge, CadError
from . import job_payload


def verification_fields(operation, result=None, error=None):
    # Only an explicit requested-motion assertion can establish this boolean.
    status = "not_requested"
    if operation == "verify_motion_preservation":
        status = (result or {}).get("verification_status", (result or {}).get("assertion", "inconclusive"))
        if error:
            status = "inconclusive"
    return {"verification_status": status, "verification_passed": {"pass": True, "fail": False}.get(status),
            "verification_scope": "explicit_requested_motion_only_not_data_integrity_or_mate_commit"}


class Jobs:
    def __init__(self, bridge: Bridge, root: Path):
        self.bridge = bridge
        self.root = root
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="cad-jobs")
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def _persist(self, job):
        folder = self.root / "runs" / "jobs"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{job['job_id']}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def submit(self, operation: str, params: dict) -> dict:
        job_id = uuid.uuid4().hex
        if operation == "import_assembly":
            params = {**params, "import_id": job_id}
        if operation in {"run_study", "run_user_study", "verify_motion_preservation", "probe_motion_compatibility"}:
            params = {**params, "run_id": job_id}
        params = {**params, "job_id": job_id}
        with self._lock:
            if sum(job["status"] in {"queued", "running"} for job in self._jobs.values()) >= 8:
                raise ValueError("任务队列已满，请等待现有任务完成。")
            job = {"job_id": job_id, "operation": operation, "status": "queued", "created_at": time.time(), "params": params,
                   "execution_succeeded": None, **verification_fields(operation)}
            self._jobs[job_id] = job
            self._persist(job)
        self._pool.submit(self._execute, job_id)
        return {"job_id": job_id, "status": "queued", "execution_succeeded": None, **verification_fields(operation)}

    def _execute(self, job_id):
        with self._lock:
            job = self._jobs[job_id]
            job.update(status="running", started_at=time.time())
            self._persist(job)
        try:
            result = self.bridge.request(job["operation"], **job["params"])
        except CadError as exc:
            update = {"status": "timed_out" if exc.code == "CAD_TIMEOUT" else "executor_lost" if exc.code == "EXECUTOR_LOST" else "failed",
                      "error": {"code": exc.code, "message": str(exc), "assertion": "inconclusive", "restoration_status": exc.restoration_status, "document_context_restoration_status": exc.document_context_restoration_status, "diagnostics": exc.diagnostics}}
        except Exception as exc:
            update = {"status": "failed", "error": {"code": "SERVICE_ERROR", "message": str(exc), "assertion": "inconclusive"}}
        else:
            update = {"status": "succeeded", "execution_status": "completed", "result": result}
        update.update(verification_fields(job["operation"], update.get("result"), update.get("error")))
        update["execution_succeeded"] = update["status"] == "succeeded"
        with self._lock:
            job.update(update, finished_at=time.time())
            job["service_timings"] = {"queue_wait_s": job["started_at"] - job["created_at"],
                                      "bridge_round_trip_s": job["finished_at"] - job["started_at"],
                                      "scope": "service_wall_clock_timestamps_includes_executor_native_and_transport_not_client_rendering"}
            progress_file = self.root / "runs" / "progress" / f"{job_id}.json"
            previous = {}
            try:
                value = json.loads(progress_file.read_text(encoding="utf-8"))
                if value.get("job_id") == job_id:
                    previous = value
            except (OSError, ValueError, AttributeError):
                pass
            terminal = {**previous, "job_id": job_id, "stage": job["status"], "terminal": True,
                        "last_native_stage": previous.get("stage"), "updated_at": time.time(),
                        "cad_operation_finished": job["status"] == "succeeded" or (
                            job["status"] == "failed" and job.get("error", {}).get("restoration_status") in {"restored", "not_required"}
                            and job["error"]["code"] != "EXECUTOR_PROTOCOL_ERROR")}
            if "checkpoint_id" in job["params"]:
                terminal["checkpoint_id"] = job["params"]["checkpoint_id"]
            if "model_id" in job["params"]:
                terminal["model_id"] = job["params"]["model_id"]
            if "run_id" in job["params"]:
                terminal["run_id"] = job["params"]["run_id"]
            if "error" in job:
                terminal["error_code"] = job["error"]["code"]
            progress_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = progress_file.with_suffix(".service.tmp")
            temporary.write_text(json.dumps(terminal, ensure_ascii=False), encoding="utf-8")
            temporary.replace(progress_file)
            job["progress"] = terminal
            self._persist(job)

    def get(self, job_id: str, response_artifact_id="", offset=0, limit=2000) -> dict:
        if response_artifact_id:
            return job_payload.read(self.root, job_id, response_artifact_id, offset, limit)
        with self._lock:
            job = copy.deepcopy(self._jobs.get(job_id))
        if job is None:
            if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
                raise ValueError("无效 job_id：须使用完整32位标识，且与提交任务使用同一安装目录；不按短前缀猜测。")
            try:
                job = json.loads((self.root / "runs/jobs" / (job_id + ".json")).read_text(encoding="utf-8"))
                if job.get("job_id") != job_id or job.get("status") not in {"queued", "running", "succeeded", "failed", "timed_out", "executor_lost"}:
                    raise ValueError("Invalid job record")
            except (OSError, ValueError, AttributeError):
                raise ValueError("未找到可读取的任务记录。") from None
            job["historical_job_read_only"] = True
            job["automatically_resumed"] = False
            if job["status"] in {"queued", "running"}:
                job["historical_execution_state"] = "unknown_not_resumed"
        job["cad_operation_state"] = self.bridge.cad_operation_state
        request_id = job.get("error", {}).get("diagnostics", {}).get("request_id")
        if not request_id:
            try:
                mapping = json.loads((self.root / "runs/jobs" / (job_id + ".request.json")).read_text(encoding="utf-8"))
                if mapping.get("job_id") == job_id and mapping.get("operation") == job["operation"]:
                    request_id = mapping.get("request_id")
            except (OSError, ValueError, AttributeError):
                pass
        if request_id and hasattr(self.bridge, "get_request_result"):
            try:
                completed = self.bridge.get_request_result(request_id)
                if completed and completed.get("params", {}).get("job_id") == job_id and completed.get("operation") == job["operation"]:
                    response = completed["response"]
                    job["late_response"] = completed
                    job["late_execution_status"] = "completed" if response.get("ok") else "failed"
                    job["original_wait_status_preserved"] = True
                    job["current_model_validity"] = "not_checked_offline"
            except CadError as exc:
                job["late_response_error"] = {"code": exc.code, "message": str(exc)}
        progress = self.root / "runs" / "progress" / f"{job_id}.json"
        try:
            value = json.loads(progress.read_text(encoding="utf-8"))
            if job["status"] in {"queued", "running"} and value.get("job_id") == job_id:
                job["progress"] = value
        except (OSError, ValueError):
            pass
        job["service_observed_at"] = time.time()
        job["service_observation_is_native_progress"] = False
        if "verification_passed" not in job:
            job.update(verification_fields(job["operation"], job.get("result"), job.get("error")))
            job["verification_fields_source"] = "derived_read_only_from_saved_explicit_assertion"
        return job_payload.bound(self.root, job)
