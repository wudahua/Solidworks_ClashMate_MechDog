"""Offline evidence ZIP; excludes CAD models and authenticated IPC envelopes/secrets."""
import hashlib
import json
import re
import time
import uuid
import zipfile
from pathlib import Path


def collect(work,task_id=''):
    from . import core
    if task_id and not re.fullmatch('[a-f0-9]{32}',task_id):raise core.StopBatch('INVALID_TASK_ID')
    work=core.no_links(Path(work));payload={};secrets=[]
    # Read the secrets only to scrub accidental occurrences. Never copy these private envelopes.
    for p in [work/'owner.json',*work.glob('ipc/*/launch.json')]:
        if p.exists():
            value=core.read(core.no_links(p))
            if isinstance(value.get('secret'),str) and value['secret']:secrets.append(value['secret'])
    def add(p,label):
        p=core.no_links(p)
        if not p.is_file():return
        if p.stat().st_size>25_000_000:raise core.StopBatch('EVIDENCE_MEMBER_TOO_LARGE')
        blob=p.read_bytes()
        for secret in secrets:blob=blob.replace(secret.encode('utf8'),b'[IPC_SECRET_REDACTED]')
        payload[label]=blob
    folders=[work/('task-'+task_id)] if task_id else sorted(work.glob('task-*'))
    for folder in folders:
        for p in folder.rglob('*'):
            if p.is_file() and p.suffix.casefold() in {'.json','.jsonl','.csv','.log','.txt','.stderr','.stdout'}:
                add(p,'tasks/'+folder.name+'/'+p.relative_to(folder).as_posix())
    for sub in ['connections','mcp-calls','host-control']:
        for p in (work/sub).glob('*.json'):add(p,sub+'/'+p.name)
    for name in ['运行目录选择.json','host-registration.json']:
        if (work/name).exists():add(work/name,name)
    for folder in (work/'ipc').glob('*'):
        if not re.fullmatch('[a-f0-9]{32}',folder.name):continue
        for name in ['process-context.json','source-attestation.json','start-broker.json','owner.log','lifecycle.jsonl','owner-exit.json']:
            p=folder/name
            if p.exists():add(p,'lifecycle/'+folder.name+'/'+name)
    if (work/'owner.json').exists():
        original=core.read(work/'owner.json')
        payload['owner-identity-redacted.json']=json.dumps({k:v for k,v in original.items() if k!='secret'},ensure_ascii=False,indent=2).encode('utf8')
    manifest={'schema':'conversation-evidence-1','created_at':time.time(),'CAD_calls_by_collector':0,
        'scope':'existing_files_snapshot_not_atomic_native_capture','raw_JSONRPC_transport_claimed':False,
        'IPC_auth_envelopes_included':False,'CAD_models_included':False,
        'files':{n:hashlib.sha256(b).hexdigest() for n,b in payload.items()}}
    payload['证据文件校验.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8')
    folder=work/'evidence';folder.mkdir(exist_ok=True)
    target=folder/('ClashMate诊断_'+uuid.uuid4().hex[:8]+'.zip')
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED) as z:
        for name,blob in payload.items():z.writestr(name,blob)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert all(z.read(n)==b for n,b in payload.items())
    digest=core.digest(target)
    sidecar=target.with_suffix(target.suffix+'.sha256.txt');sidecar.write_text(digest+' *'+target.name+'\n',encoding='utf8')
    return {'zip_path':str(target),'sha256':digest,'sha256_file':str(sidecar),'files':len(payload),
            'archive_format':'zip','CRC':'pass','CAD_calls':0,'models_included':False,'IPC_auth_secrets_included':False}
