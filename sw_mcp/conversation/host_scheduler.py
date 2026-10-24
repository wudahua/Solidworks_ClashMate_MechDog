"""Interactive, on-demand Windows broker. Never creates a trigger or stores a password."""
import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path
from .task_engine import HERE, core


def spec_for(work, entry=None, python=None, testing=False):
    work=core.no_links(Path(work))
    entry=core.no_links(entry or HERE/'owner_entry.py')
    python=core.no_links(python or Path(sys.executable).with_name('pythonw.exe'))
    if not entry.is_file() or not python.is_file():
        raise core.StopBatch('HOST_RUNTIME_MISSING','任务托管入口或无控制台Python不可用。')
    token=hashlib.sha256((str(work).casefold()+'|'+str(entry).casefold()).encode('utf8')).hexdigest()[:16]
    name='ClashMate-'+('HostTest' if testing else 'Conversation')+'-'+token
    return {'name':name,'python':str(python),'arguments':subprocess.list2cmdline(['-X','utf8',str(entry),'--work',str(work),'--generation','$(Arg0)']),
            'working_directory':str(entry.parent),'marker':'ClashMate interactive demand-only host v1 '+token,
            'work':str(work),'entry':str(entry),'triggers':0,'user_context':'current_interactive_user_no_password'}


def control(spec,mode,generation=None,timeout=25):
    if os.name!='nt':raise core.StopBatch('WINDOWS_REQUIRED')
    folder=core.no_links(Path(spec['work'])/'host-control');folder.mkdir(parents=True,exist_ok=True)
    identifier=uuid.uuid4().hex
    request=folder/(identifier+'.request.json');output=folder/(identifier+'.response.json')
    core.write(request,{**spec,'mode':mode,'generation':generation})
    ps=Path(os.environ['WINDIR'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        run=subprocess.run([str(ps),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(HERE/'host_scheduler.ps1'),
                            '-Request',str(request),'-Output',str(output)],capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW,timeout=timeout)
    except subprocess.TimeoutExpired:
        raise core.StopBatch('HOST_CONTROL_UNCONFIRMED','仅停止等待；不重复启动任务或结束持有进程。',{'request':str(request),'mode':mode})
    if not output.exists():
        (folder/(identifier+'.stderr.log')).write_bytes(run.stderr)
        raise core.StopBatch('HOST_CONTROL_FAILED','托管控制未生成回执。',{'request':str(request),'exit_code':run.returncode})
    result=core.read(output)
    if run.returncode or not result.get('ok'):
        message=result.get('message','')
        code=next((c for c in ['HOST_TASK_COLLISION','HOST_TASK_NOT_REGISTERED','HOST_TASK_STILL_RUNNING'] if c in message),'HOST_CONTROL_FAILED')
        raise core.StopBatch(code,'Windows当前用户托管操作未完成；已有回执保留。',result)
    return result


def register_host(work,python=None):
    spec=spec_for(work,python=python)
    result=control(spec,'register')
    core.write(Path(work)/'host-registration.json',{'spec':spec,'receipt':result,'entry_sha256':core.digest(spec['entry'])})
    return result


def start_host(work,generation):
    path=core.no_links(Path(work)/'host-registration.json')
    if not path.is_file():
        raise core.StopBatch('HOST_SETUP_REQUIRED','请通过首次双击配置建立当前用户托管入口；尚未启动CAD，不回退到客户端子进程。')
    saved=core.read(path);expected=spec_for(work)
    if saved['spec']!=expected or saved['entry_sha256']!=core.digest(expected['entry']):
        raise core.StopBatch('HOST_REGISTRATION_STALE','托管入口与当前源码不一致，先完成双击更新，不自动替换活任务。')
    return control(expected,'run',generation,timeout=10)
