"""Read-only process ancestry and current job limits, for redacted lifecycle evidence."""
import os
from .process_identity import observe


def process_table():
    import ctypes
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ProcessID',w.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
                  ('th32ModuleID',w.DWORD),('cntThreads',w.DWORD),('th32ParentProcessID',w.DWORD),
                  ('pcPriClassBase',w.LONG),('dwFlags',w.DWORD),('szExeFile',w.WCHAR*260)]
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];api.CreateToolhelp32Snapshot.restype=w.HANDLE
    api.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];api.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
    api.CloseHandle.argtypes=[w.HANDLE]
    handle=api.CreateToolhelp32Snapshot(2,0)
    if handle==ctypes.c_void_p(-1).value:raise OSError(ctypes.get_last_error(),'snapshot unavailable')
    try:
        e=Entry();e.dwSize=ctypes.sizeof(e);rows={};ok=api.Process32FirstW(handle,ctypes.byref(e))
        while ok:
            rows[e.th32ProcessID]={'pid':e.th32ProcessID,'parent_pid':e.th32ParentProcessID,'image':e.szExeFile}
            ok=api.Process32NextW(handle,ctypes.byref(e))
        return rows
    finally:api.CloseHandle(handle)


def snapshot():
    value={'identity':observe(os.getpid()),'parent_pid':os.getppid(),'COM_called':False}
    if os.name!='nt':return value
    try:
        import ctypes
        from ctypes import wintypes as w
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.GetCurrentProcess.restype=w.HANDLE
        api.IsProcessInJob.argtypes=[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)]
        member=w.BOOL();api.IsProcessInJob(api.GetCurrentProcess(),None,ctypes.byref(member))
        value['in_job']=bool(member.value)
        # Basic limit information starts with two LARGE_INTEGER values and a DWORD limit mask.
        api.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p]
        buf=ctypes.create_string_buffer(144)
        if member.value and api.QueryInformationJobObject(None,9,buf,len(buf),None):
            mask=int.from_bytes(buf.raw[16:20],'little')
            value.update(job_limit_flags=mask,kill_on_job_close=bool(mask&0x2000),breakaway_allowed=bool(mask&0x800),silent_breakaway=bool(mask&0x1000))
        session=w.DWORD();api.ProcessIdToSessionId.argtypes=[w.DWORD,ctypes.POINTER(w.DWORD)]
        if api.ProcessIdToSessionId(os.getpid(),ctypes.byref(session)):value['session_id']=session.value
        rows=process_table();chain=[];pid=os.getpid();seen=set()
        while pid in rows and pid not in seen and len(chain)<8:
            seen.add(pid);row=rows[pid];chain.append({**row,'observed_identity':observe(pid)});pid=row['parent_pid']
        value['ancestry']=chain
    except OSError as error:value['context_error']=str(error)
    return value
