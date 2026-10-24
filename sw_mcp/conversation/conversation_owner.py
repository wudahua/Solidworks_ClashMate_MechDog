"""Private, independent task owner. MCP disconnect never closes CAD or loses pending confirmation."""
import argparse
import hmac
import os
import re
import time
from pathlib import Path
from .task_engine import TaskEngine, core
from .owner_transport import METHODS, fingerprint,source_manifest
from .process_identity import observe
from .process_context import snapshot
from scripts.lease_access import open_lease_file, lock_lease_file


def serve(work, generation, engine_factory=TaskEngine, idle_s=900):
    from .installation_scope import require_live_installation
    require_live_installation(Path(__file__),work)
    work = core.no_links(work)
    if not re.fullmatch('[a-f0-9]{32}', generation):
        raise core.StopBatch('INVALID_OWNER_GENERATION')
    folder = core.no_links(work / 'ipc' / generation)
    launch = core.read(folder / 'launch.json')
    require_live_installation(launch['project'],launch['runtime'])
    if launch['generation'] != generation or launch['source_fingerprint'] != fingerprint():
        raise core.StopBatch('TASK_OWNER_BUILD_MISMATCH')
    for key,value in launch.get('environment',{}).items():
        if key not in {'SW_MCP_PROCESS_ID','SW_INSTALL_DIR','SW_MCP_LONG_OPERATION_WAIT_S'} or not isinstance(value,str):
            raise core.StopBatch('INVALID_OWNER_ENVIRONMENT')
        os.environ[key]=value
    lease = open_lease_file(work / 'conversation-owner.lock')
    if lease.seek(0, 2) == 0:
        lease.write(b'0'); lease.flush()
    lease.seek(0); lock_lease_file(lease)
    engine = engine_factory(Path(launch['project']), work, Path(launch['runtime']))
    context=snapshot()
    core.write(folder/'process-context.json',context)
    core.write(folder/'source-attestation.json',{'source_fingerprint':fingerprint(),'owner_pid':os.getpid(),
        'generation':generation,'entrypoint':__file__,'runtime_file_sha256':source_manifest(),'CAD_started_by_attestation':False})
    info = {**launch, 'identity': observe(os.getpid()), 'started_at': time.time()}
    core.write(work / 'owner.json', info)
    last_request = time.monotonic()
    seen=set()
    normal_return=False
    try:
        while True:
            for request_path in sorted((folder / 'requests').glob('*.json')):
                if request_path.name in seen:continue
                core.no_links(request_path)
                response_path = folder / 'responses' / request_path.name
                if response_path.exists():
                    seen.add(request_path.name)
                    continue
                try:
                    request = core.read(request_path)
                    if not isinstance(request,dict) or not isinstance(request.get('secret'),str):raise ValueError('invalid envelope')
                    if not hmac.compare_digest(request['secret'], launch['secret']):raise ValueError('wrong secret')
                    if request.get('generation') != generation or not isinstance(request.get('id'),str) or request['id'] + '.json' != request_path.name:raise ValueError('wrong identity')
                except (OSError,ValueError):
                    seen.add(request_path.name)
                    core.write(folder/'rejected'/request_path.name,{'reason':'invalid_request_envelope','CAD_dispatched':False})
                    continue
                last_request = time.monotonic()
                method = request.get('method')
                reply = {'id': request['id'], 'secret': launch['secret']}
                stop = False
                accepted_path=folder/'accepted'/request_path.name
                if accepted_path.exists():
                    reply.update(ok=False,error={'code':'OWNER_OPERATION_OUTCOME_UNCONFIRMED','message':'已有受理记录，不能再次执行。'})
                    core.write(response_path,reply);seen.add(request_path.name);continue
                # A started request without its response is never replayed after loss of an owner.
                core.write(folder / 'accepted' / request_path.name, {'method': method, 'at': time.time()})
                try:
                    if method not in METHODS:
                        raise core.StopBatch('INVALID_OWNER_OPERATION')
                    if method == 'status':
                        value = {'owner_pid': os.getpid(), 'server_instance_id': engine.server_instance_id,
                                 'active_task': engine.active, 'prior_unfinished': engine.prior_unfinished}
                    elif method == 'shutdown_idle':
                        if engine.active or engine.prior_unfinished:
                            raise core.StopBatch('TASK_SESSION_ACTIVE', '有未结束任务，不能退出持有进程。')
                        stop = True; value = {'stopped_when_idle': True, 'CAD_dispatched': False}
                    else:
                        value = getattr(engine, method)(*request.get('args', []), **request.get('kwargs', {}))
                    reply.update(ok=True, result=value)
                except Exception as error:
                    reply.update(ok=False, error={'code': getattr(error, 'code', type(error).__name__),
                                                 'message': str(error), 'diagnostics': getattr(error, 'diagnostics', None)})
                core.write(response_path, reply)
                seen.add(request_path.name)
                if stop:
                    normal_return=True
                    return
            if not engine.active and not engine.prior_unfinished and time.monotonic() - last_request > idle_s:
                normal_return=True
                return
            time.sleep(.05)
    finally:
        engine.shutdown()
        lease.close()
        core.write(folder/'owner-exit.json',{'owner_pid':os.getpid(),'owner_generation':generation,'at':time.time(),
            'active_task':engine.active,'prior_unfinished':engine.prior_unfinished,'normal_return_reached':normal_return})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--generation', required=True)
    args = parser.parse_args()
    serve(args.work, args.generation)
