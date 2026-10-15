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
            job = {"job_id": job_id, "operation": operation, "status": "queued", "created_at": time.time(), "params": params}
            self._jobs[job_id] = job
            self._persist(job)
        self._pool.submit(self._execute, job_id)
        return {"job_id": job_id, "status": "queued"}

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
            if job["operation"] == "verify_motion_preservation":
                update["verification_status"] = result.get("verification_status", result.get("assertion", "inconclusive"))
        with self._lock:
            job.update(update, finished_at=time.time())
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

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = copy.deepcopy(self._jobs.get(job_id))
        if job is None:
            if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
                raise ValueError("无效 job_id。")
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
        return job
