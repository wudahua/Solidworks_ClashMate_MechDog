from __future__ import annotations

import concurrent.futures
import copy
import json
import threading
import time
import uuid
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
        if operation in {"run_study", "run_user_study"}:
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
                      "error": {"code": exc.code, "message": str(exc), "assertion": "inconclusive", "restoration_status": exc.restoration_status, "diagnostics": exc.diagnostics}}
        except Exception as exc:
            update = {"status": "failed", "error": {"code": "SERVICE_ERROR", "message": str(exc), "assertion": "inconclusive"}}
        else:
            update = {"status": "succeeded", "result": result}
        with self._lock:
            job.update(update, finished_at=time.time())
            self._persist(job)

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = copy.deepcopy(self._jobs.get(job_id))
        if job is None:
            raise ValueError("本会话不存在该 job_id；执行器运行记录不会跨重启自动恢复。")
        job["cad_operation_state"] = self.bridge.cad_operation_state
        progress = self.root / "runs" / "progress" / f"{job_id}.json"
        try:
            value = json.loads(progress.read_text(encoding="utf-8"))
            if value.get("job_id") == job_id:
                job["progress"] = value
        except (OSError, ValueError):
            pass
        return job
