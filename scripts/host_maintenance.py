"""Offline, scoped retirement of verified idle hosts in legacy upgrade snapshots.

Never imports snapshot code, starts a host/executor, attaches COM, calls task.Stop,
or kills a process. Unknown/active instances are retained with their evidence.
"""
import argparse
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from sw_mcp.conversation import core
from sw_mcp.conversation.host_scheduler import control
from sw_mcp.conversation.process_identity import same_process
from sw_mcp.conversation.installation_scope import require_live_installation


def inventory(folder):
    folder=core.no_links(folder);folder.mkdir(parents=True,exist_ok=True)
    output=folder/('inventory-'+uuid.uuid4().hex+'.json')
    run=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/host_inventory.ps1'),
        '-Output',str(output)],capture_output=True,timeout=25,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if run.returncode or not output.is_file():raise ValueError('Host inventory unavailable; no retirement inferred')
    value=core.read(output)
    if not value.get('ok'):raise ValueError('Host inventory failed')
    return value['tasks']


def command_arguments(text):
    from ctypes import wintypes as w
    shell=ctypes.WinDLL('shell32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    shell.CommandLineToArgvW.argtypes=[w.LPCWSTR,ctypes.POINTER(ctypes.c_int)];shell.CommandLineToArgvW.restype=ctypes.POINTER(w.LPWSTR)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    count=ctypes.c_int();array=shell.CommandLineToArgvW(text,ctypes.byref(count))
    if not array:raise ValueError('Unparseable host arguments')
    try:return [array[i] for i in range(count.value)]
    finally:kernel.LocalFree(ctypes.cast(array,ctypes.c_void_p))


def candidate(row,installation,parse=command_arguments):
    if row.get('action_count')!=1:return None
    args=parse(row.get('arguments',''))
    if len(args)!=7 or args[:2]!=['-X','utf8'] or args[3]!='--work' or args[5:]!=['--generation','$(Arg0)']:return None
    if not Path(args[2]).is_absolute() or not Path(args[4]).is_absolute():return None
    entry=core.no_links(args[2]);work=core.no_links(args[4]);base=core.no_links(installation/'upgrade-backups')
    if not entry.is_relative_to(base):return None
    relative=entry.relative_to(base)
    if len(relative.parts)!=4 or not re.fullmatch('[a-f0-9]{32}',relative.parts[0]) or relative.parts[1:]!=('sw_mcp','conversation','owner_entry.py'):return None
    snapshot=base/relative.parts[0]
    if not work.is_relative_to(snapshot):return None
    python=core.no_links(row['python'])
    if python.name.casefold()!='pythonw.exe' or not python.is_file():return None
    token=hashlib.sha256((str(work).casefold()+'|'+str(entry).casefold()).encode('utf8')).hexdigest()[:16]
    spec={'name':'ClashMate-Conversation-'+token,'marker':'ClashMate interactive demand-only host v1 '+token,
        'python':str(python),'entry':str(entry),'work':str(work),'arguments':subprocess.list2cmdline(args),
        'working_directory':str(entry.parent)}
    if any(str(row.get(k,'')).casefold()!=spec[k].casefold() for k in ('name','marker','python','working_directory')) or row.get('arguments')!=spec['arguments']:
        raise ValueError('Snapshot task identity/marker differs; preserve task')
    return spec,snapshot


def existing_info(work,snapshot):
    info=core.read(core.no_links(work/'owner.json'))
    if core.no_links(info['project'])!=snapshot or not re.fullmatch('[a-f0-9]{32}',info['generation']) or not re.fullmatch('[a-f0-9]{64}',info['secret']):
        raise ValueError('Existing owner identity unavailable')
    if same_process(info['identity'])['status']!='same':raise ValueError('Existing owner process identity unconfirmed')
    folder=core.no_links(work/'ipc'/info['generation'])
    launch=core.read(core.no_links(folder/'launch.json'));proof=core.read(core.no_links(folder/'source-attestation.json'))
    if any(launch.get(k)!=info.get(k) for k in ('project','generation','source_fingerprint','secret')):
        raise ValueError('Existing launch identity mismatch')
    if proof.get('owner_pid')!=info['identity']['pid'] or proof.get('generation')!=info['generation'] or proof.get('source_fingerprint')!=info['source_fingerprint']:
        raise ValueError('Existing source attestation mismatch')
    hashes=proof.get('runtime_file_sha256')
    if not isinstance(hashes,dict) or not hashes:raise ValueError('Source attestation unavailable')
    if hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()!=info['source_fingerprint']:
        raise ValueError('Source fingerprint mismatch')
    from scripts.verify_release import safe_relative
    for name,digest in hashes.items():
        path=core.no_links(snapshot/safe_relative(name))
        if not path.is_file() or core.digest(path)!=digest:raise ValueError('Legacy host source changed; retain it')
    from sw_mcp.conversation.process_context import snapshot as context
    recorded=core.read(core.no_links(folder/'process-context.json'));current=context()
    if recorded.get('identity')!=info['identity'] or not current.get('session_id') or current.get('session_id')!=recorded.get('session_id'):
        raise ValueError('Existing host desktop identity unconfirmed')
    return info


def existing_request(work,info,method,timeout=10):
    if method not in {'status','shutdown_idle'}:raise ValueError('Only status and conditional idle shutdown are allowed')
    if same_process(info['identity'])['status']!='same':raise ValueError('Existing owner changed before request')
    folder=core.no_links(work/'ipc'/info['generation'])
    journal_dir=core.no_links(work/'host-maintenance-requests');journal_dir.mkdir(exist_ok=True)
    current=None
    for path in journal_dir.glob(info['generation']+'-*.json'):
        record=core.read(core.no_links(path))
        if record.get('status')=='responded' and record.get('stopped_when_idle') is True:
            raise ValueError('Original idle shutdown already confirmed; wait for process exit, do not resend')
        if record.get('status')!='pending':continue
        old_response=core.no_links(folder/'responses'/(record['request_id']+'.json'))
        if old_response.is_file():
            reply=core.read(old_response)
            if reply.get('id')!=record['request_id'] or not hmac.compare_digest(reply.get('secret',''),info['secret']):raise ValueError('Prior response identity unconfirmed')
            record.update(status='responded',stopped_when_idle=record['method']=='shutdown_idle' and reply.get('ok') is True and (reply.get('result') or {}).get('stopped_when_idle') is True);core.write(path,record)
            if record['method']=='shutdown_idle' and reply.get('ok'):
                raise ValueError('Prior idle shutdown confirmed; wait for original owner exit without another request')
        elif record['method']!=method:
            raise ValueError('Prior maintenance request outcome unconfirmed; inspect original response, do not queue another action')
        else:current=record
    identifier=current['request_id'] if current else uuid.uuid4().hex
    journal=journal_dir/(info['generation']+'-'+method+'.json')
    record=current or {'request_id':identifier,'generation':info['generation'],'method':method,'status':'pending','owner_identity':info['identity']}
    core.write(journal,record)
    request=core.no_links(folder/'requests'/(identifier+'.json'))
    if not request.exists():
        if (folder/'accepted'/(identifier+'.json')).exists():raise ValueError('Prior acceptance without response; no request reconstruction')
        core.write(request,{'id':identifier,'secret':info['secret'],'generation':info['generation'],'method':method,'args':[],'kwargs':{}})
    response=core.no_links(folder/'responses'/(identifier+'.json'));deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if response.is_file():
            reply=core.read(response)
            if reply.get('id')!=identifier or not hmac.compare_digest(reply.get('secret',''),info['secret']):raise ValueError('Existing host response identity mismatch')
            record.update(status='responded',stopped_when_idle=method=='shutdown_idle' and reply.get('ok') is True and (reply.get('result') or {}).get('stopped_when_idle') is True);core.write(journal,record)
            if not reply.get('ok'):raise ValueError('Existing host refused '+method+': '+str((reply.get('error') or {}).get('code','unknown')))
            return reply['result']
        time.sleep(.05)
    raise ValueError('Existing request outcome unconfirmed; do not repeat shutdown or unregister')


def retire_one(spec,snapshot,apply):
    work=Path(spec['work']);observed=control(spec,'query')
    result={'name':spec['name'],'work':str(work),'contract_verified':True,'status':'observed','cooperative_shutdown_requested':False}
    if not observed.get('registered'):return dict(result,status='already_absent')
    if not apply:return dict(result,status='would_inspect_running_host' if observed.get('running_instances') or observed.get('state') in {2,4} else 'would_unregister_idle_task')
    if observed.get('running_instances') or observed.get('state') in {2,4}:
        info=existing_info(work,snapshot);status=existing_request(work,info,'status')
        if status.get('owner_pid')!=info['identity']['pid'] or status.get('active_task') or status.get('prior_unfinished'):
            return dict(result,status='retained',reason='active_or_unfinished_owner')
        result['cooperative_shutdown_requested']=True
        stopped=existing_request(work,info,'shutdown_idle')
        if stopped.get('stopped_when_idle') is not True:raise ValueError('Idle shutdown not confirmed')
        deadline=time.monotonic()+15
        while same_process(info['identity'])['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        if same_process(info['identity'])['status'] not in {'exited','pid_reused'}:raise ValueError('Owner exit unconfirmed; preserve registration')
        while time.monotonic()<deadline:
            observed=control(spec,'query')
            if not observed.get('running_instances') and observed.get('state') not in {2,4}:break
            time.sleep(.2)
        if observed.get('running_instances') or observed.get('state') in {2,4}:raise ValueError('Scheduler wrapper still running; preserve registration')
    removed=control(spec,'unregister')  # Revalidates exact marker/SID/action and idle state.
    if removed.get('registered'):raise ValueError('Unregister outcome unconfirmed')
    final=control(spec,'query')
    if final.get('registered'):raise ValueError('Task still registered after removal')
    return dict(result,status='retired',owner_exit='confirmed' if result['cooperative_shutdown_requested'] else 'not_running')


def audit_backup_hosts(installation,folder,apply=False,rows=None):
    installation=core.no_links(installation);folder=core.no_links(folder)
    require_live_installation(ROOT,installation)
    folder.mkdir(parents=True,exist_ok=True)
    result={'schema_version':1,'installation':str(installation),'apply':apply,'retired_host_tasks':[],'retained_hosts':[],
        'observed_hosts':[],'unrelated_tasks_unchanged':True,'CAD_calls':0,'force_termination':False,'new_hosts_started':False}
    for row in inventory(folder) if rows is None else rows:
        # Read-only inventory is broad; all action is restricted to this install's legacy backup tree.
        prefix=(str(installation/'upgrade-backups')+os.sep).replace('/','\\').casefold()
        if prefix not in row.get('arguments','').replace('/','\\').casefold():continue
        try:
            match=candidate(row,installation)
            if match is None:
                result['retained_hosts'].append({'name':row.get('name'),'reason':'unrecognized_backup_action'});continue
            spec,snapshot=match;outcome=retire_one(spec,snapshot,apply)
            if outcome['status']=='retired':result['retired_host_tasks'].append(outcome)
            elif outcome['status']=='retained':result['retained_hosts'].append(outcome)
            else:result['observed_hosts'].append(outcome)
        except Exception as error:
            result['retained_hosts'].append({'name':row.get('name'),'reason':str(error),'automatic_retry':False})
    result['status']='review_required' if result['retained_hosts'] else 'pass'
    core.write(folder/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--installation',default=str(ROOT))
    parser.add_argument('--retire-idle',action='store_true');parser.add_argument('--output')
    args=parser.parse_args();folder=Path(args.output) if args.output else Path(args.installation)/'runs/host-maintenance'/uuid.uuid4().hex
    try:
        result=audit_backup_hosts(Path(args.installation),folder,args.retire_idle)
        print(json.dumps({**result,'directory':str(folder)},ensure_ascii=False));return 0 if result['status']=='pass' else 2
    except Exception as error:
        print(json.dumps({'status':'review_required','message':str(error),'force_termination':False,'automatic_retry':False},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
