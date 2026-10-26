"""Read-only retirement of an unreachable task; never infer native restoration."""
from pathlib import Path
import time
from . import core, startup_gate
from .process_identity import same_process


def _review(task):
    """Death of every bound resource supersedes stale *liveness*, not outcome."""
    folder = core.no_links(Path(task['directory']) / 'session')
    ownership_path = core.no_links(folder / '活会话归属.json')
    result = {'archive_eligible': False, 'observed_at': time.time(),
              'required_evidence': ['original_owner_identity_and_exit', 'original_CAD_identity_and_exit',
                                    'original_executor_identity_and_exit', 'bound_native_journal', 'available_executor_gate'],
              'resource_observations': {}, 'blockers': [], 'CAD_calls': 0,
              'processes_terminated': False, 'restoration_verified': False,
              'copy_preserved_without_saving_verified_result': True}

    def block(code, message, **details):
        result['blockers'].append({'code': code, 'message': message, **details})
        return result

    if not ownership_path.is_file():
        return block('ORPHAN_RESOURCE_IDENTITY_MISSING', '缺少原活会话归属记录；AI收集已有证据，不从单个CAD PID推断全部资源已结束。', path=str(ownership_path))
    ownership = core.read(ownership_path)
    result['ownership_sha256'] = core.digest(ownership_path)
    if not isinstance(ownership, dict):
        return block('ORPHAN_RESOURCE_IDENTITY_MISSING', '归属记录结构无效，不能推断进程已结束。')
    owner = ownership.get('owner') or {}
    if not isinstance(owner, dict) or owner.get('pid') != task.get('server_pid') or ownership.get('model_id') != task.get('model_id'):
        return block('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED', '归属记录的owner或模型不属于该任务。')
    result['historical_native_state'] = {key: ownership.get(key) for key in ('native_unknown', 'in_flight', 'committed', 'ended')}
    full_native_identity = bool(ownership.get('CAD') and ownership.get('executor'))
    no_native_started = (not task.get('model_id') and not ownership.get('CAD') and not ownership.get('executor')
                         and ownership.get('native_unknown') is False and ownership.get('in_flight') == {}
                         and ownership.get('committed') is False)
    if not full_native_identity and not no_native_started:
        return block('ORPHAN_RESOURCE_IDENTITY_MISSING', '原生资源身份不完整；启动中或未知的缺失身份不能按未启动处理。')
    result['native_resources_started'] = full_native_identity
    for role in ('owner', 'CAD', 'executor'):
        identity = ownership.get(role)
        if not identity:
            continue  # Only the explicitly clean, native-not-started case above.
        if (not isinstance(identity, dict) or type(identity.get('pid')) is not int or identity['pid'] <= 0
                or not isinstance(identity.get('created'), str) or not identity['created'].isdecimal()):
            return block('ORPHAN_RESOURCE_IDENTITY_MISSING', '缺少进程PID或创建身份，不能仅按PID解除保护。', role=role)
        observed = same_process(identity)
        result['resource_observations'][role] = {'recorded': identity, 'now': observed}
        if observed['status'] not in {'exited', 'pid_reused'}:
            return block('ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED', '原owner、CAD或执行器仍运行或身份未知；保留记录。', role=role)
    if full_native_identity:
        runtime = Path(ownership.get('runtime', ''))
        if not runtime.is_absolute():
            return block('ORPHAN_RESOURCE_IDENTITY_MISSING', '缺少绝对运行目录，不能借用当前安装日志。')
        journal_path = core.no_links(runtime / 'runs/executor-state.json')
        if not journal_path.is_file():
            return block('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED', '缺少绑定旧执行器和CAD的日志；只收集已有证据，不查询死亡COM。', path=str(journal_path))
        journal = core.read(journal_path)
        if (not isinstance(journal, dict) or type(journal.get('executor_pid')) is not int
                or type(journal.get('solidworks_pid')) is not int
                or journal.get('executor_pid') != ownership['executor']['pid']
                or journal.get('solidworks_pid') != ownership['CAD']['pid']):
            return block('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED', '旧日志的执行器或CAD不匹配，不借用其他会话状态。', path=str(journal_path))
        result['native_journal'] = {'path': str(journal_path), 'sha256': core.digest(journal_path),
                                    'status': journal.get('status'), 'recovery_required': journal.get('recovery_required'),
                                    'request_id': journal.get('request_id'), 'operation': journal.get('operation'),
                                    'historical_snapshot_only': True, 'rewritten': False}
    gate = startup_gate.observe()
    result['executor_gate'] = gate
    if gate.get('status') != 'available':
        return block('ORPHAN_EXECUTOR_GATE_NOT_IDLE', '当前执行器门禁不空闲；不结束其他客户端进程。')
    result.update(archive_eligible=True,
                  native_outcome='unverified_all_bound_resources_ended',
                  historical_pending_request_not_replayed=True,
                  archived_state_does_not_prove_restore_or_normal_exit=True)
    return result


def review(task):
    try:
        return _review(task)
    except (core.StopBatch, OSError, ValueError, KeyError, TypeError) as error:
        return {'archive_eligible': False, 'blockers': [{
            'code': getattr(error, 'code', 'ORPHAN_RESOURCE_IDENTITY_MISSING'),
            'message': '归档证据不可读取或格式无效；保留现场，不从缺失数据推断安全。',
            'detail': str(error)[:400]}], 'CAD_calls': 0, 'processes_terminated': False,
            'restoration_verified': False}


def require_retirement(task):
    proof = review(task)
    if not proof['archive_eligible']:
        blocker = proof['blockers'][0]
        raise core.StopBatch(blocker['code'], blocker['message'], {'task_id': task['task_id'], 'orphan_review': proof})
    return proof
