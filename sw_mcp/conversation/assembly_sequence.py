"""Durable, ordered document tasks; every native write still needs a fresh plan.

The sequence links verified copied assemblies, never replays a write or rebuilds
COM from disk. It is deliberately not an atomic cross-document transaction.
"""
import copy
import re
import uuid
from pathlib import Path
from . import core, source_integrity

ROOT_SCOPE = '$root'
MAX_DOCUMENTS = 32


def schedule(catalog):
    if catalog.get('inventory_complete') is not True:
        raise ValueError('sequence_inventory_incomplete')
    rows = catalog.get('layers')
    if not isinstance(rows, list):
        raise ValueError('sequence_layers_invalid')
    names = [r['instance'] for r in rows]
    if len(set(names)) != len(names):
        raise ValueError('sequence_duplicate_instance')
    eligible = [r for r in rows if r.get('scope_selectable') is True]
    if len(eligible) > MAX_DOCUMENTS:
        raise ValueError('sequence_document_budget_exceeded')
    # Child documents first; stable names break ties without inferring intent.
    eligible.sort(key=lambda r: (-r['instance'].count('/'), r['instance']))
    steps = [{'instance': r['instance'], 'configuration': r['configuration'],
              'shared_document_instances': r['shared_document_instances'],
              'status': 'pending', 'task_id': None} for r in eligible]
    steps.append({'instance': ROOT_SCOPE, 'status': 'pending', 'task_id': None})
    blocked = [{'instance': r['instance'], 'reason': r.get('refusal_reason')}
               for r in rows if r.get('scope_selectable') is not True]
    return {'steps': steps, 'unsupported_layers': blocked,
            'ordering_basis': 'descendant_documents_before_parent_then_root',
            'mechanical_intent_inferred': False, 'atomic_all_layer_rollback': False}


def _path(engine, sequence_id):
    if not isinstance(sequence_id, str) or not re.fullmatch('[a-f0-9]{32}', sequence_id):
        raise core.StopBatch('CONNECTION_INTENT_INVALID', '分层序列身份无效。')
    return core.no_links(engine.work / 'assembly-sequences' / (sequence_id + '.json'))


def _load(engine, task):
    value = core.read(_path(engine, task.get('assembly_sequence_id')))
    index = task.get('assembly_sequence_step')
    if (type(index) is not int or not 0 <= index < len(value['steps']) or
            value['steps'][index]['task_id'] != task['task_id']):
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '任务与分层序列步骤不匹配；未重新派发。')
    return value, index


def _save(engine, value):
    core.write(_path(engine, value['sequence_id']), value)


def summary(value):
    out={k:copy.deepcopy(value.get(k)) for k in (
        'sequence_id','status','current_step','unsupported_layers','last_verified_result',
        'original_source','native_exit_warnings','mechanical_intent_inferred',
        'atomic_all_layer_rollback','all_supported_documents_completed','all_layers_completed')}
    out['steps']=[{**{k:r.get(k) for k in ('instance','configuration','status','task_id','completed_trials','all_components_covered')},
                   'bound_result_file_count':len(r.get('result_inputs',{}))} for r in value['steps']]
    out['completion_scope']='declared_targets_in_each_supported_document_not_global_DOF_or_full_travel'
    return out


def view(engine, task):
    value, _ = _load(engine, task)
    out=summary(value)
    current=engine.tasks.get(value['steps'][value['current_step']]['task_id'],{})
    out['current_task_phase']=current.get('phase')
    if current.get('phase')=='failed' and not current.get('closed'):
        out['recorded_sequence_status']=out['status'];out['status']='blocked_current_layer'
        out['current_failure_code']=(current.get('error') or {}).get('code')
    out['full_record_path']=str(_path(engine,value['sequence_id']))
    return out


def _scope_row(catalog, step):
    rows = [r for r in catalog['layers'] if r['instance'] == step['instance']]
    if (len(rows) != 1 or rows[0].get('scope_selectable') is not True or
            rows[0].get('configuration') != step['configuration'] or
            rows[0].get('shared_document_instances') != step['shared_document_instances']):
        raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED', '后续副本的装配层身份、配置或支持范围改变，停止继续。',
                             {'expected_layer': step, 'actual_layers': rows, 'write_dispatched': False})
    return rows[0]


def after_prepare(engine, task, session):
    """Runs on the existing serialized task worker, after ordinary discovery."""
    if not task.get('assembly_sequence_id'):
        return
    value, index = _load(engine, task)
    step = value['steps'][index]
    if step['instance'] != ROOT_SCOPE:
        from .connection_task import select_scope
        select_scope(engine, task, _scope_row(session.assembly_layers, step))
    task['phase']='constraint_review_ready'
    task['next_action']['instruction'] = (
        '分层序列第' + str(index + 1) + '/' + str(len(value['steps'])) + '层：' + step['instance'] + '。'
        'AI复用已确认的机械用途形成当前具体方案；新增或改变的实际写入须明确授权，'
        '没有新歧义不重复询问。当前层验证后keep_result=True保留隔离总装，再按序继续。'
        + task['next_action']['instruction'])
    value.update(status='reviewing_layer', current_step=index)
    step['status'] = 'reviewing'
    _save(engine, value)
    engine.save(task)


def start(engine, task):
    engine._require_session(task['task_id'])
    session = engine.sessions[task['task_id']]
    if (task['phase'] != 'constraint_review_ready' or task.get('assembly_sequence_id') or
            getattr(session, 'selected_assembly_layer', None) or task.get('execution_consumed')):
        raise core.StopBatch('CONNECTION_INTENT_INVALID', '分层序列须从尚未选择内部范围、尚未执行的新总装体检开始。')
    try:
        route = schedule(session.assembly_layers)
    except (ValueError, KeyError, TypeError) as error:
        raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED', '分层清单或文档预算不完整，未启动部分序列。',
                             {'reason': str(error), 'write_dispatched': False}) from error
    sid = uuid.uuid4().hex
    value = {**route, 'sequence_id': sid, 'status': 'starting', 'current_step': 0,
             'original_source': task['source'],
             'original_inputs': copy.deepcopy(task.get('source_dependency_hashes') or {}),
             'last_verified_result': None, 'native_exit_warnings': [],
             'all_supported_documents_completed': False, 'all_layers_completed': False}
    _require_files(value['original_inputs'])
    value['steps'][0].update(task_id=task['task_id'], status='preparing')
    task.update(assembly_sequence_id=sid, assembly_sequence_step=0)
    _save(engine, value)
    engine.save(task)
    return engine._submit(task, 'selecting_assembly_layer', lambda: after_prepare(engine, task, session))


def _require_files(hashes):
    if not hashes:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '缺少分层成果的完整输入绑定。')
    for name, digest in hashes.items():
        p = core.no_links(Path(name))
        if not p.is_file() or core.digest(p) != digest:
            raise core.StopBatch('SOURCE_CHANGED', '已保存的分层输入发生改变，未继续导入。',
                                 {'changed_path': name, 'write_dispatched': False})


def _result_inputs(task):
    finish = task.get('finish') or {}
    native = finish.get('native_exit') or {}
    executor = finish.get('executor_exit') or {}
    if (not task.get('closed') or task.get('verification', {}).get('declared_scope_passed') is not True or
            finish.get('restoration_status') != 'not_requested_result_preserved' or
            finish.get('next_round_allowed') is not True or finish.get('source_files_unchanged') is not True or
            native.get('native_process_exited') is not True or native.get('force_kill') is not False or
            type(native.get('exit_code')) is not int or executor.get('confirmed') is not True or
            executor.get('executor_exit_code') != 0 or executor.get('force_kill') is not False):
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '前一层尚无完整验证、已保存成果及原生退出证据，不能推进下一层。')
    p = core.no_links(Path(finish['result_assembly_path']))
    if core.digest(p) != finish.get('result_assembly_sha256'):
        raise core.StopBatch('SOURCE_CHANGED', '前一层成果总装哈希改变，未重绑或继续。')
    # Exact importer-owned copied file set, not an arbitrary directory scan.
    imported = core.read(Path(task['directory']) / 'session/导入.json')
    runtime = core.no_links(Path(core.read(Path(task['directory']) / 'session/活会话归属.json')['runtime']))
    model = imported['model_id']
    if not re.fullmatch('user_[a-f0-9]{32}',model) or core.no_links(Path(imported['path']))!=p:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','导入身份与保留总装不一致。')
    evidence = core.read(runtime / 'experiments/user_assemblies' / model[5:] / 'import-evidence.json')
    paths = evidence.get('copy_paths')
    # Import evidence names are versioned by the importer; callers must supply
    # the explicit registered copied inventory, never silently fall back.
    if not isinstance(paths, list) or not paths:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '导入副本文件清单缺失，保留成果但不自动继续。')
    values = {}
    copied_root=runtime / 'experiments/user_assemblies' / model[5:] / 'files'
    if len(paths)!=imported['file_count']:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','副本文件数量与导入登记不符。')
    for row in paths:
        path = core.no_links(Path(row))
        path.relative_to(copied_root)
        if str(path) in values or path.suffix.lower() not in source_integrity.CAD_SUFFIXES:
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','副本清单重复或包含非CAD文件。')
        values[str(path)] = core.digest(path)
    if str(p) not in values:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '成果总装不属于已登记副本清单。')
    return p, values


def closed(engine, task):
    """Called only after ordinary finish has settled actual native resources."""
    if not task.get('assembly_sequence_id'):
        return
    value, index = _load(engine, task)
    step = value['steps'][index]
    if step['status'] in {'completed', 'restored', 'stopped'}:
        return
    finish = task.get('finish') or {}
    if finish.get('restoration_status') != 'not_requested_result_preserved':
        step.update(status='restored', restored_current_layer_only=True)
        value.update(status='stopped_current_layer_restored', current_step=index)
        _save(engine, value)
        return
    try:
        path, files = _result_inputs(task)
    except (core.StopBatch,OSError,ValueError,KeyError,TypeError) as error:
        step.update(status='blocked_evidence')
        value.update(status='blocked_after_close',sequence_error={'code':getattr(error,'code',type(error).__name__),'message':str(error)})
        _save(engine,value)
        task['next_action']={'tool':'get_mechanism_task','arguments':{'task_id':task['task_id'],'collect_evidence':True},'automatic_retry':False,
                             'instruction':'原生收尾已结束，但成果链绑定未通过；保留当前结果及诊断，不继续下一层或重放配合。'}
        engine.save(task)
        return
    step.update(status='completed', result_assembly_path=str(path), result_inputs=files,
                declared_scope_passed=True, completed_trials=task['verification']['completed_trials'],
                all_components_covered=task['verification'].get('whole_assembly_declared_targets_passed') is True)
    value['last_verified_result'] = str(path)
    if finish['native_exit']['normal_zero_exit'] is not True:
        value['native_exit_warnings'].append({'task_id': task['task_id'], 'step': index,
                                              'exit_code': finish['native_exit']['exit_code'], 'cause': 'not_proven'})
    last = index == len(value['steps']) - 1
    value.update(status='stopped_by_request' if value['status']=='stopped_by_request' else ('completed_supported_scope' if not value['unsupported_layers'] else 'partial_unsupported_layers') if last else 'ready_to_continue',
                 all_supported_documents_completed=last, all_layers_completed=last and not value['unsupported_layers'] and all(r.get('all_components_covered') is True for r in value['steps']))
    _save(engine, value)
    if not last and value['status']=='ready_to_continue':
        task['next_action'] = {'tool': 'plan_mechanism_task',
                              'arguments': {'task_id': task['task_id'], 'assembly_sequence': 'continue'},
                              'automatic_retry': False,
                              'instruction': '本层验证及收尾已核对。AI从绑定的成果总装准备下一层，不需要用户手动重选或复制路径；不复用旧执行令牌。'}
    engine.save(task)


def advance(engine, task):
    value, index = _load(engine, task)
    if not task.get('closed') or task.get('busy'):
        raise core.StopBatch('TASK_NOT_READY_FOR_PLAN', '先完成当前层验证及保存收尾，不并发启动下一层。')
    next_index = index + 1
    if next_index < len(value['steps']) and value['steps'][next_index].get('task_id'):
        child_id=value['steps'][next_index]['task_id'];child=engine.tasks.get(child_id)
        if not child or child.get('assembly_sequence_id')!=value['sequence_id'] or child.get('assembly_sequence_step')!=next_index:
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','已登记下一层缺少匹配任务记录，保留现场，不自动重建或重复prepare。')
        return {'task_id': child_id, 'sequence_id': value['sequence_id'],
                'replayed': False, 'existing_next_task': True, 'next_tool': 'get_mechanism_task'}
    if value['status'] != 'ready_to_continue' or value['steps'][index]['status'] != 'completed':
        raise core.StopBatch('TASK_NOT_READY_FOR_PLAN', '序列没有可继续的已验证成果；读取分层记录，不重放写入。')
    if index != value['current_step'] or next_index >= len(value['steps']):
        raise core.StopBatch('CONNECTION_INTENT_INVALID', '不能跳层、回退或从过期任务继续。')
    _require_files(value['original_inputs'])
    _require_files(value['steps'][index]['result_inputs'])
    gate=getattr(engine,'continuation_gate',None)
    if gate:gate()
    return engine.prepare(value['last_verified_result'], task_kind='assembly_constraints',
                          _sequence_binding=(value['sequence_id'], next_index))


def bind_new(engine, task, binding):
    sid, index = binding
    value = core.read(_path(engine, sid))
    if (type(index) is not int or index != value['current_step'] + 1 or index>=len(value['steps']) or
            value['status'] != 'ready_to_continue' or value['steps'][index].get('task_id') or
            task['source'] != value['last_verified_result']):
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '下一层任务与冻结顺序或成果不匹配。')
    value['steps'][index].update(task_id=task['task_id'], status='preparing')
    value.update(current_step=index, status='preparing_layer')
    task.update(assembly_sequence_id=sid, assembly_sequence_step=index)
    engine.save(task)
    _save(engine, value)


def stop(engine, task):
    value, index = _load(engine, task)
    if task.get('busy') or index != value['current_step']:
        raise core.StopBatch('TASK_BUSY', '只在当前层空闲时停止序列，不中断原生调用。')
    value['status'] = 'stopped_by_request'
    _save(engine, value)
    return {'task_id': task['task_id'], 'assembly_sequence': summary(value), 'native_calls': False,
            'instruction': '已停止后续层；现有活任务仍须finish正常恢复或保存收尾，先前成果副本保留，原始输入未改。'}


def dispatch(engine, task, action):
    if action == 'start':
        return start(engine, task)
    if action == 'continue':
        return advance(engine, task)
    if action == 'stop':
        return stop(engine, task)
    raise core.StopBatch('CONNECTION_INTENT_INVALID', 'assembly_sequence仅支持start、continue、stop。')
