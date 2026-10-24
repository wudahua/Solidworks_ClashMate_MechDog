"""Observe the existing executor mutex before launching CAD; never create it or touch COM."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import os

MUTEX_NAME = r'Local\SolidWorksClashMate_MechDog_Executor'
MESSAGES = {
    'EXECUTOR_ALREADY_RUNNING': '另一个 ClashMate MCP 服务正在占用执行器。请在 WorkBuddy 或其他客户端暂时停用本项目的 SolidWorks MCP 服务，保留已有 SolidWorks 窗口；停用后回到助手核对会话状态。助手不会代替你结束其他进程。',
    'PREVIOUS_EXECUTOR_CRASH': '检测到上一个执行器异常结束，请先交由 AI 核对现场；不会启动新的 SolidWorks 或自动清除保护。',
    'EXECUTOR_GATE_UNAVAILABLE': '无法确认执行器是否空闲，已在启动 SolidWorks 前停止；诊断已保存，请交给 AI。',
}

def observe(name=MUTEX_NAME):
    result = {'mutex_name': name, 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'point_in_time_not_lease_reservation', 'owner_pid': None,
              'owner_client_identified': False, 'COM_called': False, 'process_control': False}
    if os.name != 'nt':
        return dict(result, status='unknown', reason='WINDOWS_REQUIRED')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    api.OpenMutexW.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.ReleaseMutex.argtypes = [wintypes.HANDLE]
    api.ReleaseMutex.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.OpenMutexW(0x00100001, False, name)  # SYNCHRONIZE | MUTEX_MODIFY_STATE
    if not handle:
        error = ctypes.get_last_error()
        return dict(result, status='available' if error == 2 else 'unknown',
                    reason='mutex_absent' if error == 2 else 'OpenMutex_failed', win32_error=error)
    acquired = False
    try:
        wait = api.WaitForSingleObject(handle, 0)
        acquired = wait in (0, 0x80)
        result.update(status={0: 'available', 0x80: 'abandoned', 0x102: 'occupied'}.get(wait, 'unknown'),
                      wait_result=wait, reason='existing_mutex_observed')
        if wait == 0xffffffff:
            result['win32_error'] = ctypes.get_last_error()
    finally:
        # Release only ownership obtained by this same thread; never a foreign owner's lock.
        if acquired and not api.ReleaseMutex(handle):
            result.update(status='unknown', reason='ReleaseMutex_failed', win32_error=ctypes.get_last_error())
        api.CloseHandle(handle)
    return result

def require_idle(folder, observer=None):
    from . import core
    receipt = folder / '执行器启动前检查.json'
    if receipt.exists() and core.read(core.no_links(receipt)).get('status') == 'abandoned':
        raise core.StopBatch('PREVIOUS_EXECUTOR_CRASH', MESSAGES['PREVIOUS_EXECUTOR_CRASH'], core.read(receipt))
    result = (observer or observe)()
    core.write(receipt, result)
    if result['status'] != 'available':
        code = {'occupied': 'EXECUTOR_ALREADY_RUNNING', 'abandoned': 'PREVIOUS_EXECUTOR_CRASH'}.get(result['status'], 'EXECUTOR_GATE_UNAVAILABLE')
        raise core.StopBatch(code, MESSAGES[code], result)
    return result

def connection_refusal(hello, folder, attempt, owned_pid):
    """Do not retry fatal executor errors or hide them behind a generic COM timeout."""
    from . import core
    error = hello.get('error') or {}
    code = error.get('code')
    if code not in MESSAGES:
        return
    diagnostics = {'underlying_error': error, 'attempt': attempt, 'owned_pid': owned_pid,
                   'original_stdout': str(folder / ('connection-' + str(attempt) + '.stdout')),
                   'CAD_import_started': False, 'native_exit_confirmed': False,
                   'automatic_native_retry': False}
    core.write(folder / '启动阻断诊断.json', diagnostics)
    raise core.StopBatch(code, MESSAGES[code] + ' 本次专用实例已经启动，保留现场并交回诊断，不重复启动。', diagnostics)

def next_action(code):
    return MESSAGES.get(code)
