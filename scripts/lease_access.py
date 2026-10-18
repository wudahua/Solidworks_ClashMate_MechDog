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
    # ACL/attributes/filter denial (5) remains ambiguous, never asserted busy.
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


def lease_diagnostics(path, error, stage):
    winerror = getattr(error, 'winerror', None)
    return {'lease_path': str(path), 'stage': stage, 'winerror': winerror,
            'errno': getattr(error, 'errno', None), 'error_type': type(error).__name__,
            'native_message': str(error), 'sharing_conflict_proven': winerror in (32, 33),
            'access_failure_kind': 'sharing_or_lock_violation' if winerror in (32, 33) else 'access_or_io_failure_not_proven_owner',
            'owner_pid': None, 'owner_identity_status': 'OS_lock_does_not_expose_holder_PID',
            'cad_dispatched': False}
