from __future__ import annotations

import concurrent.futures
import json
import subprocess
import threading
import uuid
import os
import time
import ctypes
import re
from pathlib import Path


class CadError(RuntimeError):
    def __init__(self, code: str, message: str, restoration_status: str = "unknown"):
        self.code = code
        self.restoration_status = restoration_status
        super().__init__(message)


class Bridge:
    """Owns one executor. A timeout never implies that CAD has stopped."""

    def __init__(self, root: Path, timeout: float = 180, motion_scan_timeout: float = 600):
        self.root = root
        self.timeout = timeout
        self.motion_scan_timeout = motion_scan_timeout
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[str, concurrent.futures.Future] = {}
        self._process: subprocess.Popen | None = None
        self._startup = concurrent.futures.Future()
        self._quarantined_request: str | None = None
        self._log = None
        self._journal_lock = threading.Lock()
        self._journal_path = root / "runs" / "executor-state.json"

    def recovery_state(self) -> dict:
        with self._journal_lock:
            if not self._journal_path.exists():
                return {"status": "idle", "recovery_required": False}
            try:
                state = json.loads(self._journal_path.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("status") not in {"idle", "active", "unknown"}:
                    raise ValueError("Invalid journal")
            except (ValueError, OSError):
                return {"status": "unreadable", "recovery_required": True}
            return {**state, "recovery_required": state["status"] != "idle"}

    def _journal(self, state):
        with self._journal_lock:
            self._journal_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._journal_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({**state, "updated_at": time.time()}, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self._journal_path)

    @staticmethod
    def _pid_alive(pid):
        if not isinstance(pid, int) or pid <= 0:
            return True  # Missing identity cannot authorize recovery.
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() != 87  # Access denied remains blocked.
            try:
                code = ctypes.c_ulong()
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @property
    def cad_operation_state(self) -> str:
        with self._state_lock:
            if self._quarantined_request:
                return "unknown_after_timeout"
            if self._process and self._process.poll() is not None:
                return "executor_lost"
            return "available"

    def _start(self):
        if self._process is not None:
            if self._process.poll() is not None:
                raise CadError("EXECUTOR_LOST", "执行器已退出；确认 SolidWorks 状态后重启 MCP 服务。")
            if not self._startup.done():
                raise CadError("COM_CONNECTION_PENDING", "执行器尚未确认 COM 连接完成，不接受 CAD 操作。")
            self._startup.result()
            return
        exe = self.root / "executor" / "bin" / "SwExecutor.exe"
        if not exe.is_file():
            raise CadError("EXECUTOR_NOT_BUILT", "先运行 executor/build.ps1 编译执行器。")
        (self.root / "runs").mkdir(exist_ok=True)
        self._log = (self.root / "runs" / "executor.log").open("a", encoding="utf-8")
        self._process = subprocess.Popen(
            [str(exe)], cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self._log, text=True, encoding="utf-8", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read, daemon=True, name="cad-responses").start()
        try:
            hello = self._startup.result(timeout=20)
        except concurrent.futures.TimeoutError as exc:
            raise CadError("COM_CONNECTION_TIMEOUT", "未能连接桌面会话中的 SolidWorks；检查软件状态及执行器会话。") from exc
        if hello.get("error"):
            error = hello["error"]
            raise CadError(error.get("code", "COM_CONNECTION_FAILED"), error.get("message", "COM connection failed"))
        if hello.get("protocol_version") != 1 or not hello.get("ready"):
            raise CadError("PROTOCOL_MISMATCH", "执行器版本不匹配。")

    def _read(self):
        try:
            assert self._process and self._process.stdout
            for line in self._process.stdout:
                response = json.loads(line.lstrip("\ufeff"))
                if "ready" in response:
                    self._startup.set_result(response)
                    continue
                request_id = response.get("id")
                with self._state_lock:
                    future = self._pending.pop(request_id, None)
                    if request_id == self._quarantined_request:
                        self._quarantined_request = None
                state = self.recovery_state()
                if request_id == state.get("request_id"):
                    restoration = response.get("error", {}).get("restoration_status", "not_required")
                    if response.get("ok") and isinstance(response.get("result"), dict):
                        value = response["result"]
                        restoration = value.get("restoration_status", value.get("restoration", {}).get("status", "not_required"))
                    if state.get("recovering") and (not response.get("ok") or response.get("result", {}).get("restoration_status") != "restored"):
                        self._journal({**state["previous_state"], "status": "unknown", "last_recovery_error": response.get("error")})
                    else:
                        self._journal({**state, "status": "unknown" if restoration in {"unknown", "pending"} else "idle", "restoration_status": restoration})
                if future is not None:
                    future.set_result(response)
        except Exception as exc:
            error = CadError("EXECUTOR_PROTOCOL_ERROR", f"执行器响应无法解析：{type(exc).__name__}")
        else:
            error = CadError("EXECUTOR_LOST", "执行器已退出；CAD 操作是否停止需要确认。")
        if not self._startup.done():
            self._startup.set_exception(error)
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(error)

    def request(self, operation: str, **params):
        with self._lock:
            if self.cad_operation_state == "unknown_after_timeout":
                raise CadError("CAD_BUSY_AFTER_TIMEOUT", "上次调用超时，尚未确认 CAD 操作结束；暂不接受新 CAD 调用。")
            state = self.recovery_state()
            recovering = operation in {"restore_checkpoint", "restore_model_checkpoint"} and state["recovery_required"]
            if recovering and operation == "restore_checkpoint" and state.get("model_id"):
                raise CadError("RECOVERY_MODEL_MISMATCH", "通用模型故障须使用该模型的 restore_model_checkpoint，不能用专用机构检查点解除隔离。")
            if recovering and operation == "restore_model_checkpoint":
                target = state.get("model_id") or state.get("params", {}).get("model_id")
                if target and target != params.get("model_id"):
                    raise CadError("RECOVERY_MODEL_MISMATCH", "恢复必须针对故障请求的同一登记模型，不能用其他模型的检查点解除隔离。")
            if state["recovery_required"]:
                if not recovering:
                    raise CadError("RECOVERY_REQUIRED", "存在未确认结束的请求记录；先检查恢复状态，再恢复已登记实验检查点。")
                owned_idle = self._process is not None and self._process.pid == state.get("executor_pid") and not self._pending and self._quarantined_request is None
                if not owned_idle and self._pid_alive(state.get("executor_pid")):
                    raise CadError("PREVIOUS_EXECUTOR_ALIVE", "前一执行器仍存活或身份无法核实，拒绝并行恢复。")
            self._start()
            replacement = recovering and self._startup.result().get("process_id") != state.get("solidworks_pid")
            if replacement:
                if not params.get("allow_replacement_session"):
                    raise CadError("RECOVERY_SESSION_MISMATCH", "恢复默认绑定故障时相同的 SolidWorks 实例；旧实例已退出时可显式请求替代会话恢复。")
                if self._pid_alive(state.get("solidworks_pid")):
                    raise CadError("PREVIOUS_SOLIDWORKS_ALIVE", "旧SolidWorks实例仍存活或身份无法核实，拒绝替代会话恢复。")
            request_id = uuid.uuid4().hex
            future = concurrent.futures.Future()
            with self._state_lock:
                self._pending[request_id] = future
            try:
                assert self._process and self._process.stdin
                model_id = params.get("model_id")
                run_id = params.get("run_id", "")
                if not model_id and isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{32}", run_id):
                    try:
                        model_id = json.loads((self.root / "runs" / run_id / "solve.json").read_text(encoding="utf-8")).get("model_id")
                    except (OSError, ValueError, AttributeError):
                        pass
                self._journal({"status": "active", "request_id": request_id, "operation": operation, "params": params,
                               "model_id": model_id,
                               "executor_pid": self._process.pid, "solidworks_pid": self._startup.result().get("process_id"),
                               "recovering": recovering, "previous_state": state if recovering else None})
                self._process.stdin.write(json.dumps({"id": request_id, "op": operation, "params": params}) + "\n")
                self._process.stdin.flush()
                deadline = self.motion_scan_timeout if operation in {"check_interference_during_motion", "run_parameter_search", "diagnose_gear_phase", "import_assembly", "run_user_study", "restore_model_checkpoint"} else self.timeout
                response = future.result(timeout=deadline)
            except concurrent.futures.TimeoutError as exc:
                with self._state_lock:
                    # The late response clears quarantine only after the executor actually finishes.
                    if not future.done():
                        self._quarantined_request = request_id
                raise CadError("CAD_TIMEOUT", "调用超时；这不代表 SolidWorks 求解已停止。") from exc
            except (BrokenPipeError, OSError) as exc:
                raise CadError("EXECUTOR_LOST", "无法与执行器通信；请确认 SolidWorks 状态。") from exc
            if not response.get("ok"):
                error = response.get("error", {})
                raise CadError(error.get("code", "CAD_ERROR"), error.get("message", "CAD operation failed"), error.get("restoration_status", "unknown"))
            result = response["result"]
            if replacement:
                result = {**result, "recovery_session": {"previous_solidworks_pid": state.get("solidworks_pid"), "current_solidworks_pid": self._startup.result().get("process_id"), "replacement": True}}
            return result

    def close(self):
        # Never kill SolidWorks. EOF is processed by the executor at its next safe boundary.
        if self._process and self._process.stdin:
            try:
                self._process.stdin.close()
            except OSError:
                pass
