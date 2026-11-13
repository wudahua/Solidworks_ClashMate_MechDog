"""Read-only retirement of an unreachable task; never infer native restoration."""
from pathlib import Path
import time
from . import core, startup_gate
from .process_identity import same_process


def _preimport_partial_start(task, ownership, folder):
    """Use a real pre-import producer record, never null diagnostics as proof.

    This establishes only a startup boundary. The old CAD/owner must still be
    proved exited and an unbound executor excluded by the live exclusive gate.
    """
    if (task.get('model_id') or ownership.get('model_id') or ownership.get('checkpoint_id')
            or not ownership.get('CAD') or ownership.get('executor')
            or ownership.get('native_unknown') is not False or ownership.get('committed') is not False
            or ownership.get('in_flight') not in (None, {}) or ownership.get('pending_native_response') not in (None, {})):
        return None
    path = core.no_links(folder / 'CAD会话状态.json')
    if not path.is_file():return None
    state = core.read(path)
    if (not isinstance(state, dict) or state.get('status') not in {'starting', 'startup_failed'}
            or state.get('owned_pid') != ownership['CAD']['pid']
            or state.get('runtime') != ownership.get('runtime')
            or state.get('model_id') or state.get('checkpoint_id')
            or state.get('committed') is not False):return None
    # Any contradictory persisted import/call evidence keeps the task blocked.
    if (folder / '导入.json').exists() or any((folder / 'calls').glob('*.json')):return None
    runtime = Path(ownership.get('runtime', ''))
    if not runtime.is_absolute() or core.no_links(runtime / 'runs/executor-state.json').exists():return None
    return {'path': str(path), 'sha256': core.digest(path), 'status': state['status'],
            'scope': 'recorded_preimport_startup_boundary_not_restoration_or_historical_zero_CAD',
            'unrecorded_executor_requires_available_gate': True}


def _review(task):
    """Death of every bound resource supersedes stale *liveness*, not outcome."""
    folder = core.no_links(Path(task['directory']) / 'session')
    ownership_path = core.no_links(folder / '活会话归属.json')
    result = {'archive_eligible': False, 'observed_at': time.time(),
              'required_evidence': ['original_owner_identity_and_exit', 'original_CAD_identity_and_exit',
                                    'original_executor_identity_and_exit_or_proven_preimport_boundary', 'bound_native_journal_if_started'],
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
    result['native_resources_started'] = bool(ownership.get('CAD') or ownership.get('executor'))
    for role in ('owner', 'CAD', 'executor'):
        identity = ownership.get(role)
        if not identity:
            continue
        if (not isinstance(identity, dict) or type(identity.get('pid')) is not int or identity['pid'] <= 0
                or not isinstance(identity.get('created'), str) or not identity['created'].isdecimal()):
            return block('ORPHAN_RESOURCE_IDENTITY_MISSING', '缺少进程PID或创建身份，不能仅按PID解除保护。', role=role)
        observed = same_process(identity)
        result['resource_observations'][role] = {'recorded': identity, 'now': observed}
        if observed['status'] not in {'exited', 'pid_reused'}:
            return block('ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED', '原owner、CAD或执行器仍运行或身份未知；保留记录。', role=role)
    partial = _preimport_partial_start(task, ownership, folder) if not full_native_identity and not no_native_started else None
    if not full_native_identity and not no_native_started and not partial:
        return block('ORPHAN_RESOURCE_IDENTITY_MISSING', '原生资源身份不完整，且缺少绑定的导入前启动证据；不把空值当作未派发。')
    result['startup_classification'] = 'partial_preimport_start' if partial else 'bound_native_session' if full_native_identity else 'native_not_started'
    if partial:result['preimport_startup_evidence'] = partial
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
    if (partial or no_native_started) and gate.get('status') != 'available':
        result['owned_idle_executor_handoff_may_allow_retirement'] = True
        return block('ORPHAN_EXECUTOR_GATE_NOT_IDLE', '导入前记录没有执行器身份，须排除仍存活的未登记执行器；AI可核对并正常释放本宿主空闲连接，不能结束其他客户端。')
    # Retirement changes metadata only. A different live executor does not
    # revive proved-dead bound resources. New CAD admission retains its gate.
    result['current_executor_gate_is_new_task_admission_not_historical_outcome'] = not bool(partial)
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
