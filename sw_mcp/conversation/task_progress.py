"""File-only observations; observer heartbeats never prove native CAD progress."""
from contextlib import contextmanager
import math
import re
import threading
import time
from . import core


def current_view(session, value):
    """Read current ownership observations, including calls without a watcher.

    This refreshes presentation clocks only; it cannot prove native progress,
    release isolation, modify the task, or issue a CAD request.
    """
    try:
        if hasattr(session,'current_call_for_observation'):
            active=session.current_call_for_observation or {}
        else:
            # Compatibility for observation fixtures/older session objects;
            # current production sessions always provide the memory snapshot.
            owned=core.read(session.folder/'活会话归属.json')
            active=owned.get('in_flight') or {}
        pending=getattr(session,'pending_native_response',None) or {}
        operation=active.get('operation') or pending.get('operation')
        now=time.time();started=active.get('started')
        if not operation:
            if isinstance(value.get('progress'),dict):
                value['progress']={**value['progress'],'original_request_wait':{},'current_native_call':False}
            return value
        if type(started) not in (int,float) or not math.isfinite(started) or started>now:
            if not pending:return value
            started=now-max(0,time.monotonic()-pending['started_monotonic'])
        old=value.get('progress') or {}
        same=old.get('operation')==operation and abs(old.get('operation_started_at',0)-started)<2
        progress=dict(old) if same else {'round_index':value.get('round_index'),'round_total':value.get('round_total'),
            'stage':'native_call_pending','stage_started_at':started,'native_progress_observed':False,
            'last_native_update_at':None,'native_update_age_s':None,'completed_frames':None,'total_frames':None,'sampling_fraction':None,
            'stage_source':'owner_current_call_metadata_only','observation_source':'owner_current_call_metadata_only'}
        progress.update(operation=operation,operation_started_at=started,operation_elapsed_s=max(0,now-started),
            heartbeat_at=now,stage_elapsed_s=max(0,now-progress.get('stage_started_at',started)),
            overall_fraction=None,estimated_remaining_s=None,heartbeat_proves_native_progress=False,
            native_completion_proven_by_observer=False,automatic_retry=False,
            original_request_wait={k:v for k,v in pending.items() if k in {'request_id','operation','call_wait_budget_s','same_original_request','additional_native_dispatches'}},
            presentation_clock_refreshed_without_native_call=True,current_native_call=True)
        if progress.get('last_native_update_at') is not None:progress['native_update_age_s']=max(0,now-progress['last_native_update_at'])
        value['progress']=progress;value['native_stage']=progress['stage']
        return value
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        return value

LABELS = {
    'import_full_rebuild':'完整重建隔离副本', 'import_rebuild_snapshot':'核对重建前配合与姿态', 'prepare_gear_copy_metadata':'准备副本标准件标记',
    'initializing_solve': '初始化求解', 'motion_preflight': '检查求解条件',
    'native_calculate': '原生 Motion 求解', 'verify_native_time_axis': '读取并核对原生结果时间轴', 'capture_solver_poses': '采集全组件姿态',
    'postprocess_motion': '整理轨迹与验证驱动', 'restore_solve_scope': '恢复求解前状态',
    'finalize_solve_evidence': '核对恢复并保存证据',
}


def start_round(engine, task, index, total):
    with engine.lock:
        task.update(phase='running', round_index=index, round_total=total)
        task['progress'] = {'round_index': index, 'round_total': total, 'completed_rounds': index - 1,
                            'round_started_at': time.time(), 'stage': 'solving',
                            'scope': 'independent_solve_round_not_direction_or_native_completion'}
        engine.save(task)


def observe_stage(engine, task, status, message):
    with engine.lock:
        now = time.time()
        if task.get('native_stage') != status:
            task['stage_started_at'] = now
        task.update(native_stage=status, message=message, stage_observed_at=now)
        if 'progress' in task:
            task['progress'].update(stage=status,stage_started_at=task.get('stage_started_at',now),
                                    stage_elapsed_s=max(0,now-task.get('stage_started_at',now)),
                                    completed_frames=None,total_frames=None,sampling_fraction=None,
                                    stage_source='task_owner_stage',native_progress_observed=False)
        engine.save(task)


def observe_call(engine, task, value):
    with engine.lock:
        if not task.get('busy'):
            return
        task.setdefault('progress', {}).update(value)
        stage = value.get('stage')
        if stage:
            task.update(native_stage=stage, stage_started_at=value['stage_started_at'])
        prefix = ('第%d/%d轮独立求解：' % (task['round_index'], task['round_total'])) if task.get('round_index') else ''
        task['message'] = prefix + LABELS.get(stage, '等待本次原生调用返回') + '；心跳不代表CAD有进展，未返回时只查询，不重复提交。'
        engine.save(task)


def _native_record(path, job_id, run_id, started):
    try:
        if path.stat().st_size > 65536:
            return None
        value = core.read(path)
        if not isinstance(value, dict) or value.get('job_id') != job_id or value.get('run_id') not in (None, run_id):
            return None
        stamp = value.get('updated_at')
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or not started - 1 <= stamp <= time.time() + 1:
            return None
        stage = value.get('stage')
        if not isinstance(stage, str) or not re.fullmatch('[a-z][a-z0-9_]{0,79}', stage):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


@contextmanager
def watch_call(session, operation, arguments, interval=2):
    callback = getattr(session, 'on_progress', None)
    if callback is None or operation not in {'run_user_study','_apply_external_gear_pair','_apply_gear_transmission','restore_model_checkpoint','import_assembly','_import_gear_assembly'}:
        yield
        return
    started = time.time()
    clock = time.monotonic()
    stop = threading.Event()
    run_id, job_id = arguments.get('run_id'), arguments.get('job_id')
    path = session.runtime/'runs/progress'/(job_id + '.json') if isinstance(job_id, str) and re.fullmatch('[a-f0-9]{32}', job_id) else None

    def emit():
        now = time.time()
        record = _native_record(path, job_id, run_id, started) if path else None
        stamp = record['updated_at'] if record else None
        entered = record.get('stage_started_at', stamp) if record else started
        if type(entered) not in (int, float) or not math.isfinite(entered) or not started - 1 <= entered <= now + 1:
            entered = stamp or started
        stage = record['stage'] if record else 'native_call_pending'
        completed, total = (record.get('completed'), record.get('total')) if record else (None, None)
        fraction_known = stage == 'capture_solver_poses' and type(completed) is int and type(total) is int and 0 <= completed <= total and total > 0
        callback({'operation': operation, 'run_id': run_id, 'operation_started_at': started,
                  'operation_elapsed_s': max(0, time.monotonic() - clock), 'stage': stage,
                  'stage_started_at': entered, 'stage_elapsed_s': max(0, now - entered),
                  'heartbeat_at': now, 'last_native_update_at': stamp,
                  'native_update_age_s': max(0, now - stamp) if stamp is not None else None,
                  'native_progress_observed': record is not None,
                  'completed_frames': completed if fraction_known else None,
                  'total_frames': total if fraction_known else None,
                  'sampling_fraction': completed / total if fraction_known else None,
                  'overall_fraction': None, 'estimated_remaining_s': None,
                  'heartbeat_proves_native_progress': False, 'automatic_retry': False,
                  'native_completion_proven_by_observer': False,
                  'original_request_wait': {k:v for k,v in (getattr(session,'pending_native_response',None) or {}).items()
                                           if k in {'request_id','operation','call_wait_budget_s','same_original_request','additional_native_dispatches'}},
                  'stage_source': 'executor_progress_file' if record else 'owner_wait_heartbeat_only',
                  'observation_source': 'executor_progress_file' if record else 'owner_wait_heartbeat_only'})

    def safe_emit():
        try:
            emit()
        except Exception as error:
            # Observability must not interrupt, cancel or retry the native call.
            session.progress_observation_error = type(error).__name__

    safe_emit()
    def worker():
        while not stop.wait(interval):
            safe_emit()
    observer = threading.Thread(target=worker, name='ClashMate-file-progress', daemon=True)
    observer.start()
    try:
        yield
    finally:
        stop.set()
        observer.join(timeout=5)
