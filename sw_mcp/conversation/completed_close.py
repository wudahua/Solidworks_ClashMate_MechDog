"""Read-only retirement proof for tasks whose native close already completed."""
from pathlib import Path
from . import core,startup_gate
from .process_identity import same_process


def has_receipt(task):
    return (Path(task['directory'])/'session/会话收尾.json').is_file()


def prove(task,same_owner=False):
    folder=core.no_links(Path(task['directory'])/'session')
    paths={name:core.no_links(folder/name) for name in ('会话收尾.json','exit.json','执行器收尾.json','活会话归属.json')}
    if not all(p.is_file() for p in paths.values()):
        raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','退出收据不完整，保留任务；不恢复或重放写入。')
    receipt,native,executor,ownership=(core.read(paths[n]) for n in paths)
    if (receipt.get('ended') is not True or receipt.get('import_checkpoint_restored') is not True
        or receipt.get('finish_mode')!='restored_then_closed' or receipt.get('model_id')!=task.get('model_id')
        or not receipt.get('checkpoint_id') or receipt.get('checkpoint_id')!=ownership.get('checkpoint_id')
        or receipt.get('runtime')!=ownership.get('runtime') or ownership.get('model_id')!=task.get('model_id')
        or ownership.get('owner',{}).get('pid')!=task['server_pid'] or ownership.get('ended') is not True
        or ownership.get('in_flight')!={} or ownership.get('committed') is not False
        or native.get('native_process_exited') is not True or native.get('normal_zero_exit') is not True
        or native.get('exit_code')!=0 or executor.get('confirmed') is not True or executor.get('executor_exit_code')!=0):
        raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','恢复、退出或归属证据不一致；不解除保护。')
    observations={}
    for role in ('owner','CAD','executor'):
        identity=ownership.get(role) or {}
        if not identity.get('pid') or (role!='CAD' and not identity.get('created')):
            raise core.StopBatch('ORPHAN_RESOURCE_IDENTITY_MISSING','缺少资源身份，不能仅按PID解除保护。')
        if role=='CAD' and native.get('owned_pid')!=identity['pid']:
            raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','退出记录不是本任务的CAD实例。')
        if role=='executor' and executor.get('executor_pid')!=identity['pid']:
            raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','退出记录不是本任务的执行器。')
        observed=same_process(identity);observations[role]={'recorded':identity,'now':observed}
        allowed={'same'} if role=='owner' and same_owner else {'exited','pid_reused'} if identity.get('created') else {'exited'}
        if observed['status'] not in allowed:
            raise core.StopBatch('ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED','资源仍运行或身份未知，保留现场。',observations)
    journal_path=core.no_links(Path(ownership['runtime'])/'runs/executor-state.json')
    journal=core.read(journal_path) if journal_path.is_file() else {}
    if (journal.get('status')!='idle' or journal.get('recovery_required') is not False
        or journal.get('executor_pid')!=ownership['executor']['pid'] or journal.get('solidworks_pid')!=ownership['CAD']['pid']):
        raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','日志不能证明该任务原生请求已结束。')
    gate=startup_gate.observe()
    if gate.get('status')!='available':raise core.StopBatch('ORPHAN_EXECUTOR_GATE_NOT_IDLE',diagnostics=gate)
    return {'session':receipt,'native_exit':native,'executor_exit':executor,
            'resource_observations':observations,'native_journal_sha256':core.digest(journal_path),
            'receipt_hashes':{n:core.digest(p) for n,p in paths.items()},'executor_gate':gate,
            'CAD_calls':0,'processes_terminated':False,'restoration_verified_by':'previous_completed_receipts_not_new_restore'}
