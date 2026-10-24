"""Read-only OS process identity. Never attach COM, signal, or terminate a process."""
import os


def observe(pid):
    if type(pid) is not int or pid <= 0:
        return {'status': 'unknown'}
    if os.name != 'nt':
        try:
            from pathlib import Path
            stat = (Path('/proc') / str(pid) / 'stat').read_text()
            return {'status': 'running', 'pid': pid, 'created': stat.rsplit(')', 1)[1].split()[19]}
        except FileNotFoundError:
            return {'status': 'exited', 'pid': pid}
        except OSError:
            return {'status': 'unknown', 'pid': pid}
    import ctypes
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    api.OpenProcess.restype = w.HANDLE
    api.GetProcessTimes.argtypes = [w.HANDLE, *[ctypes.POINTER(w.FILETIME)] * 4]
    api.GetProcessTimes.restype = w.BOOL
    api.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    api.WaitForSingleObject.restype = w.DWORD
    api.CloseHandle.argtypes = [w.HANDLE]
    handle = api.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        return {'status': 'exited' if error == 87 else 'unknown', 'pid': pid, 'win32_error': error}
    try:
        if api.WaitForSingleObject(handle, 0) == 0:
            return {'status': 'exited', 'pid': pid}
        times = [w.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return {'status': 'unknown', 'pid': pid, 'win32_error': ctypes.get_last_error()}
        return {'status': 'running', 'pid': pid,
                'created': str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)}
    finally:
        api.CloseHandle(handle)


def same_process(identity):
    current = observe(identity.get('pid'))
    if current['status'] == 'running':
        current['status'] = 'same' if current.get('created') == identity.get('created') else 'pid_reused'
    return current


def detached_flags():
    """Do not inherit a client's kill-on-close job. Refuse launch if breakaway is denied."""
    if os.name != 'nt':
        return 0
    import ctypes
    import subprocess
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetCurrentProcess.restype = w.HANDLE
    api.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    api.IsProcessInJob.restype = w.BOOL
    in_job = w.BOOL()
    if not api.IsProcessInJob(api.GetCurrentProcess(), None, ctypes.byref(in_job)):
        raise OSError(ctypes.get_last_error(), 'Cannot determine client job membership')
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return flags | (subprocess.CREATE_BREAKAWAY_FROM_JOB if in_job.value else 0)
