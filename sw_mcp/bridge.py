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
import hashlib
import stat
from pathlib import Path
from sw_mcp.startup import executor_diagnostics


class CadError(RuntimeError):
    def __init__(self, code: str, message: str, restoration_status: str = "unknown", diagnostics: dict | None = None, document_context_restoration_status: str = "not_required"):
        self.code = code
        self.restoration_status = restoration_status
        self.diagnostics = diagnostics or {}
        self.document_context_restoration_status = document_context_restoration_status
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
        self._owner_id = uuid.uuid4().hex
        self._lease = None
        self._reader_thread = None
        self._ever_dispatched = False

    def _acquire_lease(self):
        """OS releases the journal lease if its Python owner crashes."""
        if self._lease is not None:
            return
        directory = self.root / "runs"
        lease = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            lease = (directory / "executor-owner.lock").open("a+b")
            if lease.seek(0, 2) == 0:
                lease.write(b"0")
                lease.flush()
            lease.seek(0)
        except OSError as exc:
            if lease is not None:
                lease.close()
            raise CadError("MCP_LEASE_UNAVAILABLE", "无法创建服务锁文件；请检查安装目录的写权限。", "not_required",
                           executor_diagnostics(self.root / "executor/bin/SwExecutor.exe", stage="open_lease", error=exc)) from exc
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lease.close()
            raise CadError("MCP_OWNER_ALREADY_RUNNING", "本安装目录已有 MCP 服务持有请求日志；请先停用该服务。", "not_required") from exc
        self._lease = lease

    @staticmethod
    def _validate_hello(hello):
        if not isinstance(hello, dict):
            raise CadError("PROTOCOL_MISMATCH", "执行器握手格式不匹配。", "not_required")
        if hello.get("error"):
            error = hello["error"]
            raise CadError(error.get("code", "COM_CONNECTION_FAILED"), error.get("message", "COM connection failed"), "not_required", error.get("diagnostics"))
        if hello.get("protocol_version") != 1 or hello.get("ready") is not True:
            raise CadError("PROTOCOL_MISMATCH", "执行器版本不匹配。", "not_required")
        pid = hello.get("process_id")
        if type(pid) is not int or pid <= 0:
            raise CadError("COM_IDENTITY_MISSING", "执行器未提供有效 SolidWorks PID；请求没有发送。", "not_required")
        return hello

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
            temporary = self._journal_path.with_name(self._journal_path.name + "." + uuid.uuid4().hex + ".tmp")
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
        self._acquire_lease()
        if self._process is not None:
            if self._process.poll() is not None:
                if not self._retryable_startup_failure():
                    raise CadError("EXECUTOR_LOST", "执行器已退出；确认 SolidWorks 状态后重启 MCP 服务。")
                if self._reader_thread is not None:
                    self._reader_thread.join(timeout=1)
                    if self._reader_thread.is_alive():
                        raise CadError("COM_CONNECTION_PENDING", "旧启动响应仍在结束；请稍后重试连接。", "not_required")
                for stream in (self._process.stdin, self._process.stdout):
                    if stream is not None:
                        stream.close()
                if self._log is not None:
                    self._log.close()
                self._process = None
                self._startup = concurrent.futures.Future()
                self._reader_thread = None
            else:
                if not self._startup.done():
                    raise CadError("COM_CONNECTION_PENDING", "执行器尚未确认 COM 连接完成，不接受 CAD 操作。")
                self._validate_hello(self._startup.result())
                return
        exe = self.root / "executor" / "bin" / "SwExecutor.exe"
        try:
            if not stat.S_ISREG(exe.stat().st_mode):
                raise CadError("EXECUTOR_NOT_BUILT", "执行器路径不是文件；先运行 executor/build.ps1 编译。", "not_required", executor_diagnostics(exe, stage="inspect"))
        except FileNotFoundError as exc:
            raise CadError("EXECUTOR_NOT_BUILT", "执行器不存在；先运行 executor/build.ps1 编译。", "not_required", executor_diagnostics(exe, stage="inspect", error=exc)) from exc
        except OSError as exc:
            code = "EXECUTOR_ACCESS_DENIED" if isinstance(exc, PermissionError) else "EXECUTOR_START_FAILED"
            raise CadError(code, "无法检查执行器文件；核对路径权限并保留原始错误。", "not_required", executor_diagnostics(exe, stage="inspect", error=exc)) from exc
        try:
            (self.root / "runs").mkdir(exist_ok=True)
            self._log = (self.root / "runs" / "executor.log").open("a", encoding="utf-8")
        except OSError as exc:
            raise CadError("EXECUTOR_LOG_UNAVAILABLE", "无法创建执行器日志；请检查安装目录的写权限。", "not_required", executor_diagnostics(exe, stage="open_log", error=exc)) from exc
        try:
            self._process = subprocess.Popen(
                [str(exe)], cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self._log, text=True, encoding="utf-8", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            code = "EXECUTOR_NOT_BUILT" if isinstance(exc, FileNotFoundError) else "EXECUTOR_ACCESS_DENIED" if isinstance(exc, PermissionError) else "EXECUTOR_START_FAILED"
            message = "启动时未找到执行器或工作目录；核对路径后重新编译。" if isinstance(exc, FileNotFoundError) else "执行器启动被拒绝；检查权限和宿主运行限制，保留诊断。" if isinstance(exc, PermissionError) else "执行器启动失败；请查看原始系统错误。"
            diagnostics = executor_diagnostics(exe, stage="launch", error=exc)
            try:
                self._log.write(json.dumps({"startup_error": code, "diagnostics": diagnostics}, ensure_ascii=False) + "\n")
            except OSError:
                pass
            finally:
                self._log.close()
                self._log = None
            raise CadError(code, message, "not_required", diagnostics) from exc
        self._reader_thread = threading.Thread(target=self._read, daemon=True, name="cad-responses")
        self._reader_thread.start()
        try:
            hello = self._startup.result(timeout=20)
        except concurrent.futures.TimeoutError as exc:
            raise CadError("COM_CONNECTION_TIMEOUT", "未能连接桌面会话中的 SolidWorks；检查软件状态及执行器会话。") from exc
        self._validate_hello(hello)

    def _retryable_startup_failure(self):
        """Retry only an explicit no-session handshake, before any request dispatch."""
        if self._ever_dispatched or self._pending or self._quarantined_request or self.recovery_state()["recovery_required"]:
            return False
        if not self._startup.done() or self._startup.cancelled():
            return False
        try:
            hello = self._startup.result()
        except Exception:
            return False
        return (isinstance(hello, dict) and hello.get("protocol_version") == 1 and hello.get("ready") is False
                and isinstance(hello.get("error"), dict)
                and hello["error"].get("code") in {"COM_SESSION_NOT_FOUND", "COM_SESSION_UNAVAILABLE"})

    def reconcile_missing_identity(self, *, model_id: str, checkpoint_id: str, solidworks_pid: int, journal_sha256: str, operation_ended_confirmed: bool):
        """Manual CLI only: bind unknown identity, then verify a real checkpoint restore."""
        if operation_ended_confirmed is not True:
            raise CadError("MANUAL_RECONCILIATION_REQUIRED", "须由操作者确认旧操作已经结束；不能以超时或通信失败替代该确认。")
        with self._lock:
            self._acquire_lease()
            raw = self._journal_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != journal_sha256.lower():
                raise CadError("RECOVERY_JOURNAL_CHANGED", "请求日志已经改变，请重新检查，不能覆盖新记录。")
            state = self.recovery_state()
            if not state["recovery_required"] or type(state.get("solidworks_pid")) is int and state["solidworks_pid"] > 0:
                raise CadError("RECONCILIATION_NOT_APPLICABLE", "仅允许核对历史缺失 SolidWorks PID 的隔离记录。")
            old_executor = state.get("executor_pid")
            if type(old_executor) is not int or old_executor <= 0 or self._pid_alive(old_executor):
                raise CadError("PREVIOUS_EXECUTOR_ALIVE", "旧执行器仍存活或身份无法核实，不允许人工绑定。")
            target = state.get("model_id") or state.get("params", {}).get("model_id")
            if target and target != model_id:
                raise CadError("RECOVERY_MODEL_MISMATCH", "必须恢复故障记录中的同一模型。")
            if not re.fullmatch(r"user_[a-f0-9]{32}", model_id) or not re.fullmatch(r"[a-f0-9]{32}", checkpoint_id):
                raise CadError("INVALID_CHECKPOINT_ID", "必须指定登记模型和有效检查点。")
            model_folder = self.root / "experiments" / "user_assemblies" / model_id[5:]
            model = json.loads((model_folder / "model.json").read_text(encoding="utf-8"))
            checkpoint = json.loads((model_folder / "checkpoints" / checkpoint_id / "checkpoint.json").read_text(encoding="utf-8"))
            if model.get("Id") != model_id or checkpoint.get("model_id") != model_id:
                raise CadError("RECOVERY_MODEL_MISMATCH", "检查点不属于指定登记模型。")
            self._start()  # Native global mutex also rejects another installation's executor.
            hello = self._validate_hello(self._startup.result())
            if type(solidworks_pid) is not int or hello["process_id"] != solidworks_pid:
                raise CadError("RECOVERY_SESSION_MISMATCH", "已连接 SolidWorks PID 与操作者核对的实例不同。")
            archive = self.root / "runs" / "recovery-audit" / (journal_sha256 + ".json")
            archive.parent.mkdir(parents=True, exist_ok=True)
            if not archive.exists():
                archive.write_bytes(raw)
            self._journal({**state, "status": "unknown", "model_id": model_id, "solidworks_pid": solidworks_pid,
                           "manual_identity_reconciliation": {"operation_ended_confirmed_by_operator": True, "previous_journal_sha256": journal_sha256, "previous_journal_archive": str(archive), "observed_solidworks_pid": hello["process_id"], "checkpoint_id": checkpoint_id}})
        # Do not set idle. Only the verified restore response can lift quarantine.
        return self.request("restore_model_checkpoint", model_id=model_id, checkpoint_id=checkpoint_id)

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
                if request_id == state.get("request_id") and state.get("owner_id") == self._owner_id:
                    restoration = response.get("error", {}).get("restoration_status", "not_required")
                    if response.get("error", {}).get("code") == "COM_CALL_FAILED" and restoration == "not_required":
                        restoration = "unknown"
                        response["error"]["restoration_status"] = "unknown"
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
            self._acquire_lease()
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
            hello = self._validate_hello(self._startup.result())
            if recovering and (type(state.get("solidworks_pid")) is not int or state["solidworks_pid"] <= 0):
                raise CadError("RECOVERY_IDENTITY_MISSING", "历史记录缺少 SolidWorks 身份；请使用 scripts/recover.py 诊断并按官方流程核对，不能直接放行替代会话。", diagnostics={"previous_state": state})
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
                wire = json.dumps({"id": request_id, "op": operation, "params": params}) + "\n"
                self._ever_dispatched = True
                self._journal({"status": "active", "owner_id": self._owner_id, "dispatch_state": "dispatching", "request_id": request_id, "operation": operation, "params": params,
                               "model_id": model_id,
                               "executor_pid": self._process.pid, "solidworks_pid": self._startup.result().get("process_id"),
                               "recovering": recovering, "previous_state": state if recovering else None})
                self._process.stdin.write(wire)
                self._process.stdin.flush()
                deadline = self.motion_scan_timeout if operation in {"check_interference_during_motion", "run_parameter_search", "diagnose_gear_phase", "import_assembly", "run_user_study", "verify_motion_preservation", "replay_motion_frame", "restore_model_checkpoint"} else self.timeout
                response = future.result(timeout=deadline)
            except concurrent.futures.TimeoutError as exc:
                with self._state_lock:
                    # The late response clears quarantine only after the executor actually finishes.
                    if not future.done():
                        self._quarantined_request = request_id
                raise CadError("CAD_TIMEOUT", "调用超时；这不代表 SolidWorks 求解已停止。") from exc
            except (BrokenPipeError, OSError) as exc:
                state_after = self.recovery_state()
                if state_after.get("request_id") == request_id and state_after.get("status") == "active":
                    self._journal({**state_after, "status": "unknown", "communication_failure": type(exc).__name__})
                raise CadError("EXECUTOR_LOST", "无法与执行器通信；请确认 SolidWorks 状态。") from exc
            if not response.get("ok"):
                error = response.get("error", {})
                raise CadError(error.get("code", "CAD_ERROR"), error.get("message", "CAD operation failed"), error.get("restoration_status", "unknown"), error.get("diagnostics"), error.get("document_context_restoration_status", "not_required"))
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
        if self._lease is not None:
            self._lease.close()
            self._lease = None
        if self._log is not None:
            self._log.close()
            self._log = None
