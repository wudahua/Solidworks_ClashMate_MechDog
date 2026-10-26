"""Shared audited transport/lifecycle functions, derived from v1.0.7; no automatic batch entry."""

from __future__ import annotations

import argparse

import csv

import hashlib

import importlib.util

import json

import math

import os

import platform

import queue

import re

import shutil

import statistics

import subprocess

import sys

import threading

import time

import uuid

from . import startup_gate

from pathlib import Path

KIT = Path(__file__).resolve().parent

VERSION = '0.4.3-alpha.18'

KIT_VERSION = 'formal-dialogue-0.4.3-alpha.18'

ALLOWED = {'get_environment','get_recovery_state','import_assembly','inspect_model',
           'list_motion_studies','preflight_motion','list_drive_candidates','create_motion_study',
           'run_motion_study','verify_motion_preservation','get_job','get_motion_summary',
           'export_motion_curve','restore_model_checkpoint','get_run_artifacts','read_run_poses'}

PREPARATION_ONLY = {'reset_study_time','create_model_checkpoint'}

class StopBatch(RuntimeError):
    def __init__(self, code, detail='', diagnostics=None):
        self.code=code
        self.diagnostics=diagnostics
        super().__init__(code+(': '+detail if detail else ''))

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8',newline='\n')
    temporary.replace(path)

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def no_links(path):
    path=Path(path).absolute()
    for p in [path,*path.parents]:
        if p.is_symlink() or getattr(p,'is_junction',lambda:False)():
            raise StopBatch('LINKED_PATH_REFUSED',str(p))
    return path.resolve()

def fixture_hashes(source):
    source=no_links(source)
    if not source.is_file() or source.suffix.lower()!='.sldasm':
        raise StopBatch('ASSEMBLY_NOT_FOUND',str(source))
    values={}
    for p in sorted(source.parent.rglob('*')):
        no_links(p)
        if p.is_file():values[p.relative_to(source.parent).as_posix()]=digest(p)
    return values

def stable_instance(name):
    # Strip only the exact importer-generated prefix, never arbitrary underscores.
    return '/'.join(re.sub(r'^\d{4}_[0-9a-fA-F]{8}_','',s) for s in name.replace('\\','/').split('/'))

def virtual_pose_aliases(evidence):
    if evidence.get('materialize_virtual_components') is not True:return {}
    uid=evidence.get('model_id','').removeprefix('user_')
    checks=('component_identity_preserved','fixed_states_preserved','poses_preserved','configurations_preserved',
            'solid_geometry_properties_and_topology_preserved','mate_identity_and_references_preserved','study_settings_times_activation_preserved')
    if not re.fullmatch('[a-f0-9]{32}',uid) or evidence.get('completed') is not True or not all(evidence.get('verification',{}).get(k) is True for k in checks):
        raise StopBatch('VIRTUAL_POSE_IDENTITY_UNPROVEN')
    aliases={};originals=evidence['fixed_state_observation_before_externalization']['instances']
    for conversion in evidence['conversions']:
        if conversion.get('identity_binding')!='same_native_component_objects_and_unchanged_component_ids_then_reopen':raise StopBatch('VIRTUAL_POSE_IDENTITY_UNPROVEN')
        before,after,ids=(conversion[k] for k in ('instances_before','instances_after','native_component_ids'))
        if not len(before)==len(after)==len(ids):raise StopBatch('VIRTUAL_POSE_IDENTITY_UNPROVEN')
        for old,new,native_id in zip(before,after,ids):
            if originals.get(str(native_id))!=old:raise StopBatch('VIRTUAL_POSE_IDENTITY_UNPROVEN')
            # Strip ONLY the exact importer batch prefix inside the evidenced
            # original virtual parent name. Never guess a user's virtual_* name.
            source_name=re.sub(r'(?<=\^)\d{4}_'+re.escape(uid[:8])+r'_','',old)
            canonical='source_virtual:'+str(native_id)+':'+source_name
            if new in aliases or canonical in aliases.values():raise StopBatch('VIRTUAL_POSE_IDENTITY_COLLISION')
            aliases[new]=canonical
    if len(aliases)!=evidence.get('native_virtual_component_count'):raise StopBatch('VIRTUAL_POSE_IDENTITY_UNPROVEN')
    return aliases

def compare_pose_files(first,second):
    def rows(path):
        path=Path(path);aliases={};sidecar=path.parent/'pose-identity.json'
        if sidecar.exists():
            identity=read(sidecar);evidence=Path(identity['import_evidence_path'])
            if digest(evidence)!=identity['import_evidence_sha256']:raise StopBatch('POSE_IDENTITY_EVIDENCE_CHANGED')
            aliases=virtual_pose_aliases(read(evidence))
            if aliases!=identity['aliases']:raise StopBatch('POSE_IDENTITY_MAPPING_CHANGED')
        result={}
        with Path(path).open(encoding='utf-8-sig',newline='') as f:
            for row in csv.DictReader(f):
                key=(int(row['frame']),aliases.get(row['instance'],stable_instance(row['instance'])))
                if key in result:raise StopBatch('POSE_IDENTITY_COLLISION',str(key))
                result[key]=row
        if not result:raise StopBatch('POSES_EMPTY')
        return result
    a,b=rows(first),rows(second)
    if a.keys()!=b.keys():raise StopBatch('POSE_SCOPE_CHANGED')
    translation=rotation=0.0
    for key in a:
        x,y=a[key],b[key]
        if abs(float(x['time_s'])-float(y['time_s']))>1e-7:raise StopBatch('POSE_TIME_CHANGED')
        values=[float(row[k]) for row in (x,y) for k in ['x_m','y_m','z_m',*['r'+str(i)+str(j) for i in range(3) for j in range(3)]]]
        if any(not math.isfinite(v) for v in values):raise StopBatch('POSES_NONFINITE')
        translation=max(translation,math.sqrt(sum((float(x[k])-float(y[k]))**2 for k in ('x_m','y_m','z_m'))))
        dot=sum(float(x['r'+str(i)+str(j)])*float(y['r'+str(i)+str(j)]) for i in range(3) for j in range(3))
        rotation=max(rotation,math.acos(max(-1,min(1,(dot-1)/2))))
    return {'rows':len(a),'maximum_translation_m':translation,'maximum_rotation_rad':rotation,
            'passed':translation<=1e-7 and rotation<=1e-6,
            'translation_tolerance_m':1e-7,'rotation_tolerance_rad':1e-6}

def runtime_path_budget(root):
    # .NET Framework atomic metadata writes append 37 characters. Include the
    # SHA sidecar and legacy archive path; merely checking the CAD filename is
    # insufficient. This is a preflight, not Windows long-path policy mutation.
    probes=[root/'experiments/user_assemblies'/('0'*32)/'save-observations'/('0'*32)/'0000000001.json.sha256',
            root/'experiments/user_assemblies'/('0'*32)/'save-observations/legacy'/('0'*64+'.json')]
    maximum=max(len(str(p))+37 for p in probes)
    if maximum>=260:raise StopBatch('ACCEPTANCE_RUNTIME_PATH_TOO_LONG','原子元数据临时路径预计长度'+str(maximum)+'；用--runtime-base明确指定更短的测试目录。')
    return {'atomic_metadata_maximum_path_characters':maximum,'legacy_windows_limit_exclusive':260,
            'scope':'known_save_observation_and_legacy_atomic_metadata_layout_not_all_arbitrary_CAD_names'}

def control(root,pid,action,folder,timeout=30):
    path=folder/(action+'-control.json')
    with (folder/(action+'-control.log')).open('wb') as stream:
        proc=subprocess.Popen([str(root/'executor/bin/AcceptanceControl.exe'),str(root),action,str(pid),str(path)],
            env={**os.environ,'SW_MCP_PROCESS_ID':str(pid)},stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW)
        write(folder/(action+'-control-process.json'),{'pid':proc.pid,'expected_sw_pid':pid})
        try:proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:raise StopBatch('CONTROL_PENDING_NO_TERMINATION',str(proc.pid))
        finally:write(folder/(action+'-control-exit.json'),{'helper_pid':proc.pid,'expected_sw_pid':pid,
            'helper_exit_code':proc.poll(),'native_exit_code_not_proven':True,'termination_performed':False})
    if proc.returncode or not path.exists() or not read(path).get('ok'):raise StopBatch('CONTROL_FAILED',str(path))
    return read(path)

def launch(root,install,folder,on_started=None):
    startup_gate.require_idle(folder)
    launch_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    with (folder/'sw-native.stdout.log').open('wb') as out,(folder/'sw-native.stderr.log').open('wb') as err:
        proc=subprocess.Popen([str(install/'SLDWORKS.exe')],stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    if on_started:on_started(proc)
    write(folder/'owned-instance.json',{'pid':proc.pid,'started_by_suite':True,'root':str(root),'no_user_pid_accepted':True,
        'executable':str(install/'SLDWORKS.exe'),'launch_observed_at_utc':launch_utc,
        'owner_identity':'Popen_retained_process_handle_not_PID_lookup'})
    deadline=time.monotonic()+180
    env={**os.environ,'SW_MCP_PROCESS_ID':str(proc.pid)}
    attempt=0
    while True:
        if proc.poll() is not None:raise StopBatch('OWNED_SOLIDWORKS_EXITED',str(proc.returncode))
        attempt+=1
        out=(folder/f'connection-{attempt}.stdout').open('wb');err=(folder/f'connection-{attempt}.stderr').open('wb')
        check=subprocess.Popen([str(root/'executor/bin/SwExecutor.exe'),'check-connection'],env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        try:check.wait(timeout=60)
        except subprocess.TimeoutExpired:raise StopBatch('CONNECTION_PENDING_NO_TERMINATION',str(check.pid))
        finally:out.close();err.close()
        hello=json.loads((folder/f'connection-{attempt}.stdout').read_bytes())
        startup_gate.connection_refusal(hello,folder,attempt,proc.pid)
        if hello.get('ready'):
            if hello['process_id']!=proc.pid:raise StopBatch('OWNED_PID_MISMATCH')
            break
        if time.monotonic()>deadline:raise StopBatch('COM_STARTUP_NOT_READY')
        time.sleep(2)
    control(root,proc.pid,'empty',folder)
    return proc

def restored_ok(value):
    return (value.get('restoration_status')=='restored' and value.get('source_files_unchanged') is True
            and type(value.get('maximum_transform_delta')) in (int,float)
            and math.isfinite(value['maximum_transform_delta']) and value['maximum_transform_delta']<=1e-7)

def close_owned(wire,proc,root,folder):
    def event(stage,**evidence):
        with (folder/'exit-host.stages.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'stage':stage,'observed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                'monotonic_s':time.monotonic(),'owned_pid':proc.pid,**evidence},ensure_ascii=False)+'\n')
    event('before_mcp_close')
    if wire is not None and (wire.unknown or not wire.close()):raise StopBatch('MCP_EXIT_UNCONFIRMED_NO_CAD_EXIT')
    event('after_mcp_close',mcp_exit_code=wire.process.returncode if wire is not None else None)
    event('before_exit_control')
    control(root,proc.pid,'exit',folder,45)
    event('after_exit_control',helper_exit_code=read(folder/'exit-control-exit.json')['helper_exit_code'])
    event('before_native_wait',maximum_wait_s=45)
    try:proc.wait(timeout=45)
    except subprocess.TimeoutExpired:raise StopBatch('OWNED_CAD_EXIT_PENDING_NO_TERMINATION',str(proc.pid))
    event('after_native_wait',native_exit_code=proc.returncode)
    write(folder/'exit.json',{'owned_pid':proc.pid,'exit_code':proc.returncode,'normal_zero_exit':proc.returncode==0,
        'native_process_exited':True,'exit_code_process':'owned_SLDWORKS_not_control_helper',
        'helper_exit_code':read(folder/'exit-control-exit.json')['helper_exit_code'],'force_kill':False})
    if proc.returncode!=0:raise StopBatch('OWNED_CAD_EXIT_NONZERO',str(proc.returncode))

