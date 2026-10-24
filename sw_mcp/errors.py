"""Shared operational failure contract. A timeout never proves CAD stopped."""
import copy

# Deliberate guidance classes; none authorizes changing mechanical parameters or replaying a write.
NATIVE_ACTION_CLASSES={
    **dict.fromkeys(('CHECKPOINT_REQUIRES_INITIAL_TIME','CREATE_STUDY_REQUIRES_INITIAL_TIME','ACTIVE_TIME_NOT_FRAME_ALIGNED'),
                    ('mechanical_initial_state_review_required','AI核对当前算例时间与机械姿态，明确归零或恢复方案后再操作；不因时钟为零就认定姿态正确。')),
    **dict.fromkeys(('CHECKPOINT_SETTINGS_MISMATCH','CHECKPOINT_TIME_RESTORE_FAILED'),
                    ('checkpoint_recovery_review_required','AI读取原检查点和恢复证据；核对设置、时间和全组件姿态，不自动换检查点或重试写入。')),
    **dict.fromkeys(('STUDY_NOT_FOUND','MODEL_PREFLIGHT_FAILED'),
                    ('model_and_study_review_required','AI读取模型、算例和预检阻断项，确认存在且适用后再提出方案，不猜测或忽略重建失败。')),
    **dict.fromkeys(('DRIVE_ENTITY_STALE','CANDIDATE_CURSOR_STALE','DRIVE_ENTITY_NOT_FOUND'),
                    ('fresh_geometry_reference_required','AI重新只读查询该组件的引用并核对归属；旧引用和游标不可重用，新的写入方案需要重新确认。')),
    **dict.fromkeys(('COM_SESSION_NOT_FOUND','COM_SESSION_UNAVAILABLE','INVALID_SOLIDWORKS_PID','COM_SESSION_ID_MISMATCH','AMBIGUOUS_COM_SESSION'),
                    ('native_session_identity_review_required','AI核对SolidWorks实例与COM身份；仅在明确、安全的会话选择条件下重新选择，不能把进程存在当作COM可用。')),
    **dict.fromkeys(('NATIVE_TIME_AXIS_MISMATCH','MOTION_RESULTS_INCOMPLETE'),
                    ('native_result_evidence_review_required','AI先读取已保存时间轴、采样和失败工件；不把不完整结果记为通过，不为补诊断重复求解。')),
    **dict.fromkeys(('INVALID_MODEL_ID','MODEL_NOT_REGISTERED'),
                    ('registered_model_selection_required','AI从已有任务或登记清单核对model_id；不能用文件路径或其他会话ID冒充，也不自动重复导入。')),
}


def operational_error(code, message, restoration_status='unknown', diagnostics=None,
                      document_context_restoration_status='not_required', *, job_created=None):
    diagnostics = copy.deepcopy(diagnostics or {})
    diagnostics.setdefault('cad_dispatched', None)  # unknown is distinct from a pre-dispatch refusal
    diagnostics.setdefault('job_created', job_created)
    token = diagnostics.get('next_action')
    if not isinstance(token, str) and isinstance(diagnostics.get('details'), dict):
        token = diagnostics['details'].get('next_action')
    if isinstance(token, str):
        diagnostics['next_action_code'] = token  # retain legacy field for existing clients
    uncertain = restoration_status not in {'restored', 'not_required'} or code in {'CAD_TIMEOUT', 'EXECUTOR_LOST', 'EXECUTOR_PROTOCOL_ERROR'}
    action = {'automatic_retry': False, 'options': [],
              'instruction': ('先读取 get_recovery_state 并核对原请求是否结束；恢复未知时使用该模型的检查点恢复。不要重复派发写入。'
                              if uncertain else '读取完整失败诊断与已保存工件，核对参数、原生状态和恢复记录后再显式决定下一步。'),
              'recovery_state_query': {'tool': 'get_recovery_state', 'arguments': {}},
              'options_status': 'no_safe_parameter_change_inferred_from_error_code'}
    if isinstance(token, str): action['action_code'] = token
    if code in {'MCP_OWNER_ALREADY_RUNNING','EXECUTOR_ALREADY_RUNNING'}:
        action.update(instruction='停用同一安装目录的其他 MCP 服务，等待其退出后显式重试；不要终止不明进程或清除恢复日志。',
                      options_status='manual_service_disconnect_required_no_parameter_change')
    elif code == 'MATE_OVERDEFINED' or (isinstance(diagnostics.get('details'), dict) and
            isinstance(diagnostics['details'].get('original_failure'), dict) and diagnostics['details']['original_failure'].get('code') == 'MATE_OVERDEFINED'):
        action['instruction'] = '核对方案与既有配合约束；原生过定义不证明某个无关配合有错。修改具体方案并重新预演、确认后再提交，不重复重试原方案。'
        action['options_status'] = 'manual_constraint_review_required_no_safe_geometry_inferred'
    elif code in NATIVE_ACTION_CLASSES:
        action['options_status'],action['instruction']=NATIVE_ACTION_CLASSES[code]
    return {'code': code, 'message': message, 'assertion': 'inconclusive',
            'restoration_status': restoration_status,
            'document_context_restoration_status': document_context_restoration_status,
            'diagnostics': diagnostics, 'next_action': action}
