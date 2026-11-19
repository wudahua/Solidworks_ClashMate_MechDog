"""Preview and explicitly confirm material edits in one owned assembly copy."""
import json
import uuid

from . import core, task_execution
from ..bridge import CadError


def propose(engine, task, assignments):
    task_id=task['task_id']
    engine._require_session(task_id)
    if task['phase'] not in {'constraint_review_ready','awaiting_confirmation'} or task.get('connection_batch_history'):
        raise core.StopBatch('TASK_NOT_READY_FOR_PLAN','用新体检副本单独规划零件材质。')
    session=engine.sessions[task_id]
    if getattr(session,'selected_assembly_layer',None) or task.get('assembly_sequence_id'):
        raise core.StopBatch('PARAMETER_NOT_APPLICABLE','整机材质盘点及写入须在装配根范围进行。')
    previous={k:task.get(k) for k in ('phase','proposal','plan_token','plan_token_revoked','next_action')}

    def operation():
        try:
            plan=session.call('_preview_part_materials',model_id=session.model,assignments_json=json.dumps(assignments,ensure_ascii=False))
        except CadError as error:
            if error.code!='PARAMETER_NOT_APPLICABLE' or session.unknown:
                raise
            task.update(previous)
            task['material_input_review']={'code':error.code,'message':str(error),'diagnostics':error.diagnostics}
            return
        task.pop('material_input_review',None)
        task.pop('assembly_plan_review',None)
        task.pop('assembly_plan_snapshot',None)
        task.update(phase='awaiting_confirmation',plan_token=uuid.uuid4().hex,plan_token_revoked=False,
                    proposal={**plan,'task_operation':'assign_part_materials'},
                    next_action={'tool':'execute_mechanism_task','arguments':{'task_id':task_id},
                                 'instruction':'列出零件、配置以及变更前后材质，取得明确确认后再执行。'})
        core.write(session.folder/'零件材质方案.json',plan)
    return engine._submit(task,'planning_part_materials',operation)


def execute(engine, task, token, confirmed, scope_confirmed, alignment_confirmed):
    task_id=task['task_id']
    engine._require_session(task_id)
    if confirmed is not True or scope_confirmed is not True:
        raise core.StopBatch('CONFIRMATION_REQUIRED','须确认方案列出的零件配置和材质。')
    if alignment_confirmed is not False:
        raise core.StopBatch('PARAMETER_NOT_APPLICABLE','材质写入没有初态调整选项。')
    task_execution.require_plan_token(task,token)
    task.update(execution_consumed=True,confirmation={'confirmed':True,'scope_confirmed':True})
    engine.save(task)

    def operation():
        session=engine.sessions[task_id]
        note=session.call('_apply_part_materials',plan_id=task['proposal']['plan_id'],confirmed=True)
        if not (note.get('materials_verified') and note.get('mates_and_poses_unchanged') and note.get('source_files_unchanged')):
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','隔离副本的材质或机械状态核对失败。')
        session.capture_applied_result()
        session.committed=True
        session.import_restored=False
        task.update(phase='verified',verification={'declared_scope_passed':True,'material_assignments':note['assignments'],
                    'mates_and_poses_unchanged':True,'scope':'verified_material_assignment_only'},
                    next_action={'tool':'finish_mechanism_task','arguments':{'task_id':task_id},
                                 'instruction':'核对已写入的零件材质。用户明确要交付成果副本时才传keep_result=true。'})
        core.write(session.folder/'零件材质写入核对.json',note)
    return engine._submit(task,'assigning_part_materials',operation)
