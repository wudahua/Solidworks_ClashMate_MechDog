"""No-CAD, actual Windows job/tree cleanup acceptance using exclusively owned fixtures."""
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from ctypes import wintypes as w
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
HERE=Path(__file__).resolve().parent
from sw_mcp.conversation import core
from sw_mcp.conversation.process_identity import detached_flags,observe,same_process
from sw_mcp.conversation.process_context import process_table,snapshot
from sw_mcp.conversation.owner_transport import OwnerClient,fingerprint
from sw_mcp.conversation.host_scheduler import spec_for,control
from dialogue_client import Client


def await_file(path,timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if path.exists():return core.read(path)
        time.sleep(.05)
    raise RuntimeError('Fixture did not produce '+str(path))


def worker(root,mode):
    root=Path(root);work=root/'work';project=root/'fixture-product';runtime=HERE.parent/'runs/cr'
    core.write(root/'worker-ready.json',snapshot())
    await_file(root/'go.json')
    generation=uuid.uuid4().hex;folder=work/'ipc'/generation;folder.mkdir(parents=True)
    core.write(folder/'launch.json',{'generation':generation,'secret':uuid.uuid4().hex,'project':str(project),
        'runtime':str(runtime),'source_fingerprint':fingerprint()})
    if mode=='legacy':
        with (root/'legacy-owner.log').open('wb') as log:
            subprocess.Popen([sys.executable,'-X','utf8',str(HERE/'dialogue_fixture_owner.py'),'--work',str(work),'--generation',generation],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=detached_flags(),close_fds=True)
    else:
        control(core.read(root/'host-spec.json'),'run',generation)
    await_file(work/'owner.json')
    client=Client(project,work,runtime,root/'mcp-before',entry=HERE/'dialogue_fixture_frontend.py')
    source=root/'models/case.SLDASM';source.parent.mkdir();source.write_bytes(b'no CAD fixture')
    tid=client.tool('prepare_mechanism_task',assembly_path=str(source),task_kind='concentric')['task_id'];client.wait(tid)
    client.tool('plan_mechanism_task',task_id=tid);planned=client.wait(tid)
    assert planned['phase']=='awaiting_confirmation'
    core.write(root/'ready-for-cleanup.json',{'planned':planned,'worker':snapshot(),
        'owner':core.read(work/'owner.json')['identity'],'frontend_launcher_pid':client.process.pid})
    # This test worker is intentionally ended by the parent harness, not by a native CAD failure.
    while True:time.sleep(.1)


class Job:
    def __init__(self,pid):
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),
                ('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',w.DWORD),('affinity',ctypes.c_size_t),
                ('priority',w.DWORD),('scheduling',w.DWORD)]
        class Io(ctypes.Structure):_fields_=[('v',ctypes.c_uint64*6)]
        class Extended(ctypes.Structure):_fields_=[('basic',Basic),('io',Io),('pm',ctypes.c_size_t),('jm',ctypes.c_size_t),('ppm',ctypes.c_size_t),('pjm',ctypes.c_size_t)]
        api=ctypes.WinDLL('kernel32',use_last_error=True);self.api=api
        api.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];api.CreateJobObjectW.restype=w.HANDLE
        api.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        api.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenProcess.restype=w.HANDLE
        api.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];api.CloseHandle.argtypes=[w.HANDLE]
        self.handle=api.CreateJobObjectW(None,None)
        limits=Extended();limits.basic.flags=0x2000|0x800
        if not api.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):raise ctypes.WinError(ctypes.get_last_error())
        proc=api.OpenProcess(0x101,False,pid)
        try:
            if not proc or not api.AssignProcessToJobObject(self.handle,proc):raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if proc:api.CloseHandle(proc)
    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None


def fixture_descendants(root_identity):
    if same_process(root_identity)['status']!='same':raise RuntimeError('fixture root identity changed')
    rows=process_table();ids={root_identity['pid']}
    while True:
        expanded=ids|{pid for pid,row in rows.items() if row['parent_pid'] in ids}
        if expanded==ids:break
        ids=expanded
    found=[]
    for pid in ids:
        row=rows[pid];identity=observe(pid)
        if identity['status']!='running':continue
        if row['image'].casefold() not in {'python.exe','pythonw.exe','powershell.exe','conhost.exe'}:
            raise RuntimeError('Unexpected process in owned fixture tree: '+row['image'])
        if int(identity['created'])<int(root_identity['created']):raise RuntimeError('PID reuse in fixture ancestry')
        found.append({'identity':identity,'image':row['image'],'parent_pid':row['parent_pid']})
    return found


def end_owned_fixture(identity):
    """Test only. No process is selected by a foreign PID, name, or user's CAD inventory."""
    if same_process(identity)['status']!='same':return
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];api.OpenProcess.restype=w.HANDLE
    api.TerminateProcess.argtypes=[w.HANDLE,w.UINT];api.CloseHandle.argtypes=[w.HANDLE]
    h=api.OpenProcess(1,False,identity['pid'])
    if not h:raise ctypes.WinError(ctypes.get_last_error())
    try:
        if same_process(identity)['status']!='same':raise RuntimeError('fixture PID identity no longer matches')
        if not api.TerminateProcess(h,71):
            error=ctypes.get_last_error()
            # Job shutdown can have already started asynchronous process termination.
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and same_process(identity)['status']=='same':time.sleep(.05)
            if same_process(identity)['status']=='same':raise OSError(error,'Owned fixture terminate denied: '+str(identity['pid']))
    finally:api.CloseHandle(h)


def run_case(root,mode,cleanup):
    root.mkdir(parents=True)
    spec=None;job=None;client=None
    if mode=='scheduler':
        spec=spec_for(root/'work',entry=HERE/'dialogue_fixture_owner.py',testing=True)
        control(spec,'register');core.write(root/'host-spec.json',spec)
    with (root/'worker.log').open('wb') as log:
        child=subprocess.Popen([sys.executable,'-X','utf8',str(HERE/'dialogue_lifecycle.py'),'--worker',str(root),mode],
            stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    result={'mode':mode,'cleanup':cleanup,'real_CAD':False,'native_calls':0}
    try:
        ready=await_file(root/'worker-ready.json');job=Job(ready['identity']['pid']);core.write(root/'go.json',{})
        active=await_file(root/'ready-for-cleanup.json',40)
        result['before']=active;result['owned_cleanup_tree']=fixture_descendants(ready['identity'])
        # Closing this self-created job models a client's job cleanup; bounded descendants model recursive cleanup.
        job.close()
        time.sleep(.3)
        if cleanup=='tree':
            for row in reversed(result['owned_cleanup_tree']):
                # Console hosts follow their owning fixture's handles; never request their termination.
                if row['image'].casefold()!='conhost.exe':end_owned_fixture(row['identity'])
        child.wait(timeout=10);time.sleep(.3)
        result['owner_after_cleanup']=same_process(active['owner'])
        if mode=='legacy' and cleanup=='tree':
            assert result['owner_after_cleanup']['status']=='exited'
            result['status']='expected_legacy_failure_reproduced'
        else:
            assert result['owner_after_cleanup']['status']=='same',result
            client=Client(root/'fixture-product',root/'work',HERE.parent/'runs/cr',root/'mcp-after',entry=HERE/'dialogue_fixture_frontend.py')
            resumed=client.tool('get_mechanism_task',task_id=active['planned']['task_id'])
            assert resumed['plan_token']==active['planned']['plan_token']
            assert resumed['server_instance_id']==active['planned']['server_instance_id']
            assert resumed['phase']=='awaiting_confirmation'
            client.tool('execute_mechanism_task',task_id=resumed['task_id'],plan_token=resumed['plan_token'],confirmed=True,scope_confirmed=True)
            assert client.wait(resumed['task_id'])['phase']=='verified'
            client.tool('finish_mechanism_task',task_id=resumed['task_id']);assert client.wait(resumed['task_id'])['closed']
            assert core.read(root/'work'/('task-'+resumed['task_id'])/'session/fixture-apply-count.json')['calls']==1
            result.update(status='pass',same_owner_and_plan=True,fixture_apply_calls=1)
            client.close();OwnerClient(root/'fixture-product',root/'work',HERE.parent/'runs/cr').call('shutdown_idle')
    finally:
        if job:job.close()
        if client and client.process.poll() is None:client.close()
        if spec:
            for _ in range(30):
                if not control(spec,'query').get('running_instances'):break
                time.sleep(.2)
            result['task_cleanup']=control(spec,'unregister')
        core.write(root/'result.json',result)
    return result


def main():
    root=HERE.parent/'runs/formal-lifecycle'/uuid.uuid4().hex[:8];root.mkdir(parents=True)
    core.write(HERE.parent/'runs/当前正式生命周期验收.json',{'directory':str(root),'status':'running'})
    results=[]
    try:
        for mode,cleanup in [('scheduler','tree'),('scheduler','job')]:
            print('CASE',mode,cleanup,flush=True)
            results.append(run_case(root/(mode+'-'+cleanup),mode,cleanup))
        value={'status':'pass','CAD_started':False,'target_WorkBuddy_real_refresh_tested':False,'cases':results,'directory':str(root)}
        core.write(root/'result.json',value);core.write(HERE.parent/'runs/当前正式生命周期验收.json',{'directory':str(root),'status':'pass'})
        print(json.dumps({'directory':str(root),'status':'pass','CAD_started':False},ensure_ascii=False),flush=True)
    except BaseException:
        core.write(HERE.parent/'runs/当前正式生命周期验收.json',{'directory':str(root),'status':'failed'});raise


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':worker(sys.argv[2],sys.argv[3])
    else:main()
