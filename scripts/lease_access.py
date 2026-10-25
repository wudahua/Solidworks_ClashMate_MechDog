"""Open without truncation; preserve Windows sharing-vs-access-denied evidence."""
import os


def open_lease_file(path):
    if os.name != 'nt':
        return path.open('a+b')
    import ctypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint,
                                  ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    # OPEN_ALWAYS, shared read/write/delete. A conflicting holder yields 32/33;
    # Access denial (5) can include service/handle topology as well as ACL,
    # attributes or filters. Preserve the code; never assert a holder from it.
    handle = kernel.CreateFileW(str(path), 0xC0000000, 7, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    try:
        return os.fdopen(descriptor, 'r+b')
    except BaseException:
        os.close(descriptor)
        raise


def lock_lease_file(file, unlock=False):
    """Nonblocking byte-zero lock, interoperable with CRT owners; retain Win32 33."""
    if os.name != 'nt':
        import fcntl
        fcntl.flock(file, fcntl.LOCK_UN if unlock else fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    import ctypes
    import msvcrt
    class Overlapped(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', ctypes.c_uint32), ('OffsetHigh', ctypes.c_uint32), ('hEvent', ctypes.c_void_p)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    method = kernel.UnlockFileEx if unlock else kernel.LockFileEx
    method.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Overlapped)] if unlock else [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Overlapped)]
    method.restype = ctypes.c_int
    overlapped = Overlapped()
    handle = msvcrt.get_osfhandle(file.fileno())
    ok = method(handle, 0, 1, 0, ctypes.byref(overlapped)) if unlock else method(handle, 3, 0, 1, 0, ctypes.byref(overlapped))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def lease_diagnostics(path, error, stage):
    winerror = getattr(error, 'winerror', None)
    return {'lease_path': str(path), 'stage': stage, 'winerror': winerror,
            'errno': getattr(error, 'errno', None), 'error_type': type(error).__name__,
            'native_message': str(error), 'sharing_conflict_proven': winerror in (32, 33),
            'occupied_proven': winerror in (32, 33),
            'byte_lock_conflict_observed': winerror == 33,
            'native_code_source': 'Win32_GetLastError' if winerror is not None else 'exception_errno_only_no_native_code',
            'access_failure_kind': 'sharing_or_lock_violation' if winerror in (32, 33) else 'access_or_io_failure_not_proven_owner',
            'owner_pid': None, 'owner_identity_status': 'OS_lock_does_not_expose_holder_PID',
            'possible_causes': ['same_installation_service_or_host_handle_topology','file_attributes','ACL','filesystem_filter_or_IO'] if winerror == 5 else [],
            'service_presence_proven': False, 'lock_path_probe_mutation': False,
            'cad_dispatched': False}


def lease_access_instruction():
    return ('WinError 5或访问失败不能单独证明权限不足或服务占用。AI先只读核对本安装已有MCP服务、对话宿主及任务/恢复记录；'
            '不要为检查而新启动执行器。仅在本服务无活动受管任务、无运行中旧工具任务且恢复状态已确认空闲时，'
            '可调用finish_motion_session；安全收尾后只停用同一安装的相关客户端，再显式重做升级预检。'
            '若确认服务已退出仍失败，再检查文件属性、ACL或文件系统过滤器；不删除、重命名锁文件，不改权限，不强杀或自动重试。')
