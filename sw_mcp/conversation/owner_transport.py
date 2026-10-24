"""Authenticated file RPC to one independent task owner. No network listener or CAD here."""
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from .task_engine import HERE, core
from .process_identity import same_process
from .host_scheduler import start_host, control as host_control
from scripts.lease_access import open_lease_file, lock_lease_file

METHODS = {'prepare', 'get', 'plan', 'execute', 'finish', 'status', 'shutdown_idle', 'tool'}


def source_manifest():
    root=HERE.parents[1]
    paths=sorted(HERE.glob('*.py'))+sorted(HERE.glob('*.ps1'))+sorted(HERE.glob('*.cs'))
    paths+=sorted((root/'sw_mcp').glob('*.py'))+sorted((root/'executor').glob('*.cs'))
    paths+=[root/'motion_server.py',root/'scripts/lease_access.py',root/'scripts/install_preflight.py']
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

def fingerprint():
    return hashlib.sha256(json.dumps(source_manifest(),sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()


class OwnerClient:
    def __init__(self, project, work, runtime_base, timeout=12):
        self.project = core.no_links(Path(project))
        self.work = core.no_links(Path(work)); self.work.mkdir(parents=True, exist_ok=True)
        self.runtime = Path(runtime_base).absolute(); self.timeout = timeout
        self.info = None

    def _verify_context(self,info):
        from .process_context import snapshot
        owner=core.read(core.no_links(self.work/'ipc'/info['generation']/'process-context.json'))
        current=snapshot()
        if owner.get('identity')!=info['identity'] or current.get('session_id')!=owner.get('session_id') or not current.get('session_id'):
            raise core.StopBatch('HOST_SESSION_MISMATCH','持有进程身份或桌面会话不匹配，未启动CAD。')
        core.write(self.work/'connections'/(uuid.uuid4().hex+'.json'),{'frontend':current,'owner_identity':info['identity'],
            'owner_generation':info['generation'],'source_fingerprint':info['source_fingerprint'],'same_desktop_session':True,'COM_called':False})

    def connect(self):
        if self.info:
            status=same_process(self.info['identity'])['status']
            if status in {'exited','pid_reused'}:
                self.info=None  # New owner may read/retire old records; it never recreates COM handles.
            elif status != 'same':
                raise core.StopBatch('TASK_OWNER_LOST', '任务持有进程不可确认，读取原记录，不重放写入。')
            else:return
        lease = open_lease_file(self.work / 'owner-start.lock')
        try:
            if lease.seek(0, 2) == 0:
                lease.write(b'0'); lease.flush()
            lease.seek(0)
            try:
                lock_lease_file(lease)
            except OSError:
                raise core.StopBatch('TASK_OWNER_START_BUSY', '正在建立任务连接，AI稍后读取状态。')
            path = core.no_links(self.work / 'owner.json')
            retired_generation=None
            if path.exists():
                info = core.read(path)
                status = same_process(info['identity'])['status']
                if status in {'exited','pid_reused'}:retired_generation=info['generation']
                if status == 'unknown':
                    raise core.StopBatch('TASK_OWNER_IDENTITY_UNKNOWN', '原持有进程身份无法核实，保留现场。')
                if status == 'same':
                    if Path(info['project']) != self.project:
                        raise core.StopBatch('TASK_OWNER_BUILD_MISMATCH', '活任务持有进程属于另一源码或产品环境，未替换。')
                    self._verify_context(info)
                    if info['source_fingerprint'] != fingerprint():
                        # Upgrades may retire an idle old owner, but cannot dispose of a live CAD task.
                        self.info=info
                        try:
                            stopped=self.call('shutdown_idle')
                            if stopped.get('stopped_when_idle') is not True:raise core.StopBatch('TASK_OWNER_STOP_UNCONFIRMED')
                        finally:self.info=None
                        deadline=time.monotonic()+10
                        while same_process(info['identity'])['status']=='same' and time.monotonic()<deadline:time.sleep(.05)
                        if same_process(info['identity'])['status'] not in {'exited','pid_reused'}:
                            raise core.StopBatch('TASK_OWNER_STOP_UNCONFIRMED','旧空闲持有进程尚未确认退出，不启动第二个。')
                        retired_generation=info['generation']
                    else:
                        self.info = info
                        return
            starting=self.work/'owner-starting.json'
            if starting.exists():
                pending=core.read(core.no_links(starting))
                if pending.get('launch_rejected_before_RunEx') is True or pending.get('generation')==retired_generation:
                    unconfirmed=False
                elif 'identity' in pending:
                    unconfirmed=same_process(pending['identity'])['status'] in {'same','unknown'}
                else:
                    unconfirmed=time.time()-pending.get('requested_at',0)<30
                    if not unconfirmed and (self.work/'host-registration.json').exists():
                        saved=core.read(self.work/'host-registration.json')
                        status=host_control(saved['spec'],'query',timeout=10)
                        unconfirmed=status.get('running_instances',0)>0 or status.get('state') in {2,4}
                if unconfirmed:
                    raise core.StopBatch('TASK_OWNER_START_UNCONFIRMED','已有持有进程启动记录，AI稍后查询，不重复创建。',
                                         {'generation':pending['generation']})
            generation = uuid.uuid4().hex
            folder = core.no_links(self.work / 'ipc' / generation)
            folder.mkdir(parents=True, exist_ok=False)
            secret = uuid.uuid4().hex + uuid.uuid4().hex
            launch = {'generation': generation, 'secret': secret, 'project': str(self.project),
                      'runtime': str(self.runtime), 'source_fingerprint': fingerprint(),
                      'environment':{k:os.environ[k] for k in ('SW_MCP_PROCESS_ID','SW_INSTALL_DIR','SW_MCP_LONG_OPERATION_WAIT_S') if k in os.environ}}
            core.write(folder / 'launch.json', launch)
            log = folder / 'owner.log'
            # The broker creates the owner in the logged-in desktop session, outside the MCP process tree.
            # There is deliberately no Popen fallback after a failed/missing registration.
            from .host_scheduler import register_host
            # An exact registered action is reused; unrelated actions are never overwritten.
            register_host(self.work)
            core.write(self.work/'owner-starting.json',{'generation':generation,'requested_at':time.time(),'launch_mode':'interactive_demand_task'})
            try:receipt=start_host(self.work,generation)
            except core.StopBatch as error:
                if (error.diagnostics or {}).get('launch_attempted') is False:
                    rejection={'generation':generation,'requested_at':time.time(),'launch_rejected_before_RunEx':True,
                               'error':{'code':error.code,'diagnostics':error.diagnostics},'retry_started':False}
                    core.write(folder/'start-rejected.json',rejection)
                    core.write(starting,rejection)  # Preserve evidence; no deletion, RunEx retry, or unknown-outcome reset.
                raise
            core.write(folder/'start-broker.json',receipt)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if path.exists():
                    info = core.read(path)
                    if info.get('generation') == generation:
                        self._verify_context(info);self.info = info
                        return
                time.sleep(.05)
            raise core.StopBatch('TASK_OWNER_START_UNCONFIRMED', '只停止等待，未重复启动或结束持有进程。', {'generation': generation, 'log': str(log)})
        finally:
            lease.close()

    def call(self, method, *args, **kwargs):
        if method not in METHODS:
            raise core.StopBatch('INVALID_OWNER_OPERATION')
        self.connect()
        folder = core.no_links(self.work / 'ipc' / self.info['generation'])
        identifier = uuid.uuid4().hex
        request = {'id': identifier, 'secret': self.info['secret'], 'generation': self.info['generation'],
                   'method': method, 'args': args, 'kwargs': kwargs}
        core.write(folder / 'requests' / (identifier + '.json'), request)
        response = folder / 'responses' / (identifier + '.json')
        deadline = time.monotonic() + (max(self.timeout,700) if method=='tool' else self.timeout)
        while time.monotonic() < deadline:
            if response.exists():
                reply = core.read(core.no_links(response))
                if not hmac.compare_digest(reply.get('secret', ''), self.info['secret']):
                    raise core.StopBatch('INVALID_OWNER_RESPONSE')
                if not reply['ok']:
                    raise core.StopBatch(reply['error']['code'], reply['error']['message'], reply['error'].get('diagnostics'))
                return reply['result']
            time.sleep(.05)
        raise core.StopBatch('TASK_OWNER_REQUEST_UNCONFIRMED', '请求已留存，AI查询任务状态；不重新提交执行。',
                             {'request_id': identifier, 'generation': self.info['generation'],
                              'next_tool': 'get_mechanism_task', 'retry_write_allowed': False})

    def prepare(self, *args, **kw): return self.call('prepare', *args, **kw)
    def get(self, *args, **kw): return self.call('get', *args, **kw)
    def plan(self, *args, **kw): return self.call('plan', *args, **kw)
    def execute(self, *args, **kw): return self.call('execute', *args, **kw)
    def finish(self, *args, **kw): return self.call('finish', *args, **kw)
    def evidence(self,task_id=''):
        from .evidence_bundle import collect
        return collect(self.work,task_id)
