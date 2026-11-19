"""Explicit standalone changes to an owned assembly and its saved checkpoint."""
import json
import uuid

from . import core, task_execution
from .. import connection_mate_changes
from ..bridge import CadError


def propose(engine, task, requests, independentize_mirrors):
    task_id = task['task_id']
    engine._require_session(task_id)
    if task['phase'] not in {'constraint_review_ready', 'awaiting_confirmation'} or task.get('connection_batch_history'):
        raise core.StopBatch('TASK_NOT_READY_FOR_PLAN', '请在装配体检副本中单独规划装配改造。')
    session = engine.sessions[task_id]
    survey = getattr(session, 'connection_survey', None)
    if (getattr(session, 'selected_assembly_layer', None) or task.get('assembly_sequence_id')
            or not isinstance(survey, dict) or survey.get('inventory_complete') is not True):
        raise core.StopBatch('PARAMETER_NOT_APPLICABLE', '装配改造须在装配根范围使用完整配合清单。')

    changes = []
    affected_pairs = []
    if requests is not None:
        try:
            _, changes = connection_mate_changes.prepare(survey, requests)
            names = {c['component_id']: c['instance'] for c in survey['components']}
            mates = {m['native_feature_id']: m for m in survey['mates']}
            for change in changes:
                refs = mates[change['native_feature_id']].get('entities') or []
                components = [names.get(ref.get('component_id')) for ref in refs]
                if len(components) != 2 or any(not name for name in components) or components[0] == components[1]:
                    raise ValueError('mate_change_requires_observed_component_pair')
                affected_pairs.append({'name': change['name'], 'components': components,
                                       'before_suppressed': change['before'], 'after_suppressed': change['after']})
        except (ValueError, TypeError, KeyError) as error:
            raise core.StopBatch('MATE_CHANGE_REVIEW_REQUIRED', '请从本次体检中选择身份明确的基础配合，复核受影响的零件对。',
                                 {'reason': str(error), 'write_dispatched': False}) from error

    operation_kind = 'independentize_mirrors' if independentize_mirrors else 'change_existing_mates'
    previous = {k: task.get(k) for k in ('phase', 'proposal', 'plan_token', 'plan_token_revoked', 'next_action')}

    def operation():
        try:
            plan = session.call('_preview_assembly_repair', model_id=session.model,
                                proposal_json=json.dumps({'mate_changes': changes}, ensure_ascii=False),
                                independentize_mirrors=independentize_mirrors)
        except CadError as error:
            if error.code != 'ASSEMBLY_REPAIR_SCOPE_UNVERIFIED' or session.unknown:
                raise
            task.update(previous)
            task['assembly_repair_review'] = {'code': error.code, 'message': str(error),
                                              'diagnostics': error.diagnostics, 'write_dispatched': False}
            return
        task.pop('assembly_repair_review', None)
        task.pop('assembly_plan_review', None)
        task.pop('assembly_plan_snapshot', None)
        proposal = {**plan, 'task_operation': operation_kind, 'affected_component_pairs': affected_pairs}
        task.update(phase='awaiting_confirmation', plan_token=uuid.uuid4().hex, plan_token_revoked=False,
                    proposal=proposal, next_action={'tool': 'execute_mechanism_task', 'arguments': {'task_id': task_id},
                        'instruction': '说明受影响的零件对或镜向特征及实例，取得明确同意后执行。核验范围是装配状态，运动需另行验证。'})
        core.write(session.folder/'装配改造方案.json', proposal)

    return engine._submit(task, 'planning_assembly_repair', operation)


def execute(engine, task, token, confirmed, scope_confirmed, alignment_confirmed):
    task_id = task['task_id']
    engine._require_session(task_id)
    if confirmed is not True or scope_confirmed is not True:
        raise core.StopBatch('CONFIRMATION_REQUIRED', '须确认旧配合状态或明确的镜向独立化范围。')
    if alignment_confirmed is not False:
        raise core.StopBatch('PARAMETER_NOT_APPLICABLE', '装配改造方案没有初态对齐选项。')
    task_execution.require_plan_token(task, token)
    task.update(execution_consumed=True, confirmation={'confirmed': True, 'scope_confirmed': True})
    engine.save(task)

    def operation():
        session = engine.sessions[task_id]
        proposal = task['proposal']
        note = session.call('_apply_assembly_repair', plan_id=proposal['plan_id'], confirmed=True)
        core.write(session.folder/'装配改造原生核对.json', note)
        if (not all(note.get(k) is True for k in ('mate_inventory_verified', 'poses_references_fixed_flags_verified',
                                               'reopened_verified', 'source_files_unchanged'))
                or note.get('added_mates') != 0 or note.get('motion_verified') is not False
                or note.get('mate_changes') != proposal['mate_changes']
                or note.get('mirror_feature_ids') != [m['native_feature_id'] for m in proposal['mirror_features']]
                or note.get('independent_occurrences') != proposal['independent_occurrences']):
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '改造回执与已确认的装配变更不一致。')
        session.capture_applied_result()
        session.committed = True
        session.import_restored = False
        task.update(phase='verified', verification={'declared_scope_passed': True,
                    'scope': proposal['task_operation'], **note},
                    next_action={'tool': 'finish_mechanism_task', 'arguments': {'task_id': task_id},
                        'instruction': '核对改造范围和重开回执。经确认保留成果后，用成果副本继续体检、补配合或运动验证。'})

    return engine._submit(task, 'applying_assembly_repair', operation)
