"""Shared operational failure contract. A timeout never proves CAD stopped."""
import copy


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
    if code == 'MCP_OWNER_ALREADY_RUNNING':
        action.update(instruction='停用同一安装目录的其他 MCP 服务，等待其退出后显式重试；不要终止不明进程或清除恢复日志。',
                      options_status='manual_service_disconnect_required_no_parameter_change')
    elif code == 'MATE_OVERDEFINED' or (isinstance(diagnostics.get('details'), dict) and
            isinstance(diagnostics['details'].get('original_failure'), dict) and diagnostics['details']['original_failure'].get('code') == 'MATE_OVERDEFINED'):
        action['instruction'] = '核对方案与既有配合约束；原生过定义不证明某个无关配合有错。修改具体方案并重新预演、确认后再提交，不重复重试原方案。'
        action['options_status'] = 'manual_constraint_review_required_no_safe_geometry_inferred'
    return {'code': code, 'message': message, 'assertion': 'inconclusive',
            'restoration_status': restoration_status,
            'document_context_restoration_status': document_context_restoration_status,
            'diagnostics': diagnostics, 'next_action': action}
