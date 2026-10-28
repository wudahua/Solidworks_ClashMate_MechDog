"""Deliberate task failure semantics shared by owner, frontend and saved failures.

No classification infers restoration or permission to repeat a CAD write. New
literal task codes must be registered here (the AST contract test enforces it).
"""
from copy import deepcopy
import re
from sw_mcp.errors import operational_error, NATIVE_ACTION_CLASSES


CONFIRMATION_CODES = frozenset({
    'CONFIRMATION_REQUIRED', 'MATE_CONFIRMATION_REQUIRED',
    'KEEP_CHANGES_CONFIRMATION_REQUIRED', 'MOTION_TEST_CONFIRMATION_REQUIRED',
    'ORPHAN_CLOSE_CONFIRMATION_REQUIRED',
})

# Each entry is (options_status, instruction, codes). A tool is a diagnostic
# route, never evidence that its arguments require user input.
GROUPS = (
    ('explicit_human_confirmation_required',
     '向用户解释具体方案、机械范围与恢复或保留方式，取得明确授权；不得自行把确认字段改为true，不自动重试写入。',
     CONFIRMATION_CODES),
    ('user_parameter_correction_required',
     'AI核对工具声明、字段范围及原调用；定位文件或修正参数后显式调用。仅机械选择或授权确有必要时询问用户，不要求用户手抄ID或命令。',
     {'INVALID_MOTION_TYPE', 'INVALID_MOTION_PARAMETERS', 'INVALID_MINIMUM_TRAVEL',
      'INVALID_TASK_KIND', 'CONNECTION_INTENT_INVALID', 'CONCENTRIC_FIXED_CARD_PARAMETERS', 'GEAR_PARAMETERS_INVALID', 'INVALID_ASSEMBLY_PATH',
      'ASSEMBLY_NOT_FOUND', 'INVALID_INITIAL_STATE', 'INVALID_TASK_ID','INVALID_ALIGNMENT_MODE','SCOPE_CONFIRMATION_MUST_BE_BOOLEAN',
      'INCOMPATIBLE_FINISH_CHOICES', 'INVALID_POSE_BUDGET', 'INVALID_RECOMMENDATION_INDEX',
      'INVALID_RUN_ID', 'INVALID_SCOPE_CONFIRMATION', 'UNKNOWN_MATE_ACTION','EXTERNAL_GEAR_RATIO_INVALID','EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE'}),
    ('mechanical_selection_required',
     'AI用现有候选的名称、角色、位置及轴线解释歧义，请用户以机械用途或名称澄清；复用当前副本，不把几何排名当设计意图。',
     {'COMPONENT_NAME_AMBIGUOUS', 'REFERENCE_COMPONENT_SELECTION_REQUIRED', 'GEAR_ROLE_SELECTION_REQUIRED',
      'INCOMPLETE_MECHANICAL_SCOPE', 'MOVING_SCOPE_TOO_BROAD', 'INVALID_TASK_CANDIDATE',
      'EXTERNAL_GEAR_SELECTION_REQUIRED','EXTERNAL_GEAR_RATIO_REQUIRED','EXTERNAL_GEAR_RATIO_AMBIGUOUS'}),
    ('task_state_review_required_no_write_retry',
     'AI读取已有任务的阶段、busy和结果；运行中只查询，完成后安全收尾。不要重复prepare或execute，也不通过重启绕过一次性执行保护。',
     {'TASK_BUSY', 'TASK_ALREADY_EXECUTED', 'TASK_SESSION_ACTIVE', 'MANAGED_TASK_ACTIVE', 'GEAR_PLAN_CONSUMED',
      'LEGACY_JOBS_ACTIVE', 'COMPONENT_SELECTION_NOT_REQUESTED', 'INITIAL_STATE_SELECTION_NOT_READY',
      'TASK_NOT_READY_FOR_PLAN', 'TASK_NOT_READY_FOR_EXECUTION', 'MATE_PLAN_NOT_READY',
      'MATE_PREVIEW_NOT_READY', 'MATE_STATE_NOT_READY', 'MATE_SESSION_ALREADY_STARTED',
      'MATE_SESSION_ENDED', 'MOTION_SESSION_FINISHED', 'MOTION_BASELINE_NOT_READY',
      'MOTION_VERIFY_NOT_READY', 'KEEP_REQUIRES_VERIFIED_RESULT', 'TASK_SESSION_NOT_CREATED',
      'MANAGED_RUNTIME_NOT_READY', 'MANAGED_REPLAY_REQUIRES_LIVE_IDLE_TASK'}),
    ('fresh_task_plan_required_no_write_retry',
     'AI核对原任务、已选零件对、引用和一次性令牌；旧方案失效。先读取现场并按安全收尾结论决定重新规划，新方案须重新确认，不换绑旧基线或重放写入。',
     {'CONNECTION_PLAN_STALE','CONFIRMED_PAIR_CHANGED', 'MOTION_PROPOSAL_STALE', 'GEAR_PLAN_STALE',
      'MATE_RECOMMENDATION_STALE', 'MOTION_BASELINE_PAIR_MISMATCH',
      'MOTION_PAIR_REDISCOVERY_REQUIRED', 'MOTION_AXIS_CHANGED_AFTER_RESET','ALIGNMENT_PROPOSAL_STALE'}),
    ('task_plan_token_readback_required_no_write_retry',
     '提交令牌不匹配。AI先用get_mechanism_task读回原任务，核对阶段、方案和已有授权；不能仅凭此码断言方案失效，也不直接重复写入。已消费、过期或归属不明时只读原结果及收尾记录。',
     {'PLAN_TOKEN_MISMATCH'}),
    ('task_record_selection_required',
     'AI不传task_id调用get_mechanism_task查找现有记录；不猜测ID，不因找不到记录就重复创建或执行任务。',
     {'TASK_NOT_IN_CURRENT_SERVER'}),
    ('task_owner_recovery_review_required',
     'AI读取旧任务、原资源身份和现有恢复记录；不能从JSON重建COM、重放令牌或自动关闭失败记录。只有明确授权且资源退出证据齐全时才可异常归档，恢复仍按未验证报告。',
     {'TASK_OWNER_UNAVAILABLE', 'PRIOR_TASK_UNCONFIRMED', 'ORPHAN_NATIVE_SESSION_UNAVAILABLE',
      'ORPHAN_NATIVE_OUTCOME_UNCONFIRMED', 'ORPHAN_RESOURCE_IDENTITY_MISSING',
      'ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED', 'ORPHAN_EXECUTOR_GATE_NOT_IDLE',
      'INVALID_PERSISTED_TASK_IDENTITY', 'TASK_NATIVE_CONNECTION_LOST',
      'MANAGED_RECOVERY_CONNECTION_LOST', 'MANAGED_RECOVERY_IDENTITY_MISMATCH',
      'MANAGED_RECOVERY_SCOPE_MISMATCH'}),
    ('native_outcome_review_required_no_write_retry',
     'AI读取原请求、归属和恢复日志；超时或进程存在都不证明请求结束。未知状态不重试写入、不自动恢复或强制结束；原请求结束且同一活连接核对通过后才提出恢复。',
     {'CONNECTION_NATIVE_UNKNOWN','STUDY_CREATION_NATIVE_UNKNOWN', 'NATIVE_STATE_UNKNOWN', 'REQUEST_RESULT_INVALID', 'RECOVERY_WAIT_FOR_NATIVE_OUTCOME', 'EXECUTOR_EXIT_UNCONFIRMED', 'GEAR_ROLLBACK_FAILED',
      'TASK_FINISH_UNCONFIRMED', 'MATE_RECOVERY_REQUIRES_AI', 'RESTORE_NOT_VERIFIED',
      'RESTORE_AUDIT_FAILED', 'RESULT_CHECKPOINT_UNAVAILABLE', 'RESULT_RESTORE_NOT_VERIFIED',
      'KEPT_MATE_STATE_MISMATCH', 'CONTROL_PENDING_NO_TERMINATION', 'CONTROL_FAILED',
      'CONNECTION_PENDING_NO_TERMINATION', 'COM_STARTUP_NOT_READY', 'OWNED_PID_MISMATCH',
      'OWNED_SOLIDWORKS_EXITED', 'MCP_EXIT_UNCONFIRMED_NO_CAD_EXIT',
      'OWNED_CAD_EXIT_PENDING_NO_TERMINATION', 'OWNED_CAD_EXIT_NONZERO',
      'TASK_OWNER_REQUEST_UNCONFIRMED', 'OWNER_OPERATION_OUTCOME_UNCONFIRMED',
      'PREVIOUS_EXECUTOR_CRASH', 'EXECUTOR_GATE_UNAVAILABLE'}),
    ('mechanical_evidence_review_required_no_parameter_change',
     'AI读取已有初态、轨迹、组件身份和验证证据，报告不完整或不一致；不是简单参数错误，不放宽容差、改绑基线或为补诊断重复求解。',
     {'CONNECTION_EVIDENCE_FAILED','CONNECTION_CREATE_FAILED','CONNECTION_APPLY_ROLLED_BACK','INVALID_INITIAL_POSE', 'INVALID_MOTION_AXIS', 'INITIAL_POSE_COMPONENT_SCOPE_CHANGED',
      'STUDY_CONSTRAINT_STATE_UNVERIFIED','GEAR_MOTION_EVIDENCE_FAILED','GEAR_PARAMETERS_UNVERIFIED','GEAR_FIXED_STATE_UNVERIFIED','GEAR_SETUP_POSE_EXCEEDED','GEAR_SUPPORT_ALIGNMENT_EXCEEDED','GEAR_CONSTRAINT_CREATE_FAILED','GEAR_APPLY_ROLLED_BACK',
      'INITIAL_POSE_MISMATCH', 'INITIAL_FRAME_INVALID', 'BASELINE_TRAJECTORY_NOT_ACCEPTED',
      'DUPLICATE_POSE_SAMPLE', 'NONFINITE_POSE_SAMPLE', 'POSE_COMPONENT_MISSING',
      'POSE_GRID_INCOMPLETE', 'POSE_TIME_GRID_CHANGED', 'MOTION_COMPONENT_NOT_OBSERVED',
      'VIRTUAL_POSE_IDENTITY_UNPROVEN', 'VIRTUAL_POSE_IDENTITY_COLLISION',
      'POSE_IDENTITY_EVIDENCE_CHANGED', 'POSE_IDENTITY_MAPPING_CHANGED', 'POSE_IDENTITY_COLLISION',
      'POSES_EMPTY', 'POSE_SCOPE_CHANGED', 'POSE_TIME_CHANGED', 'POSES_NONFINITE',
      'SOURCE_CHANGED', 'CANDIDATE_SOURCE_MISMATCH', 'TASK_ARTIFACT_BINDING_MISSING', 'MOTION_POSE_EVIDENCE_UNAVAILABLE',
      'INVALID_INITIAL_TRANSFORM','CARD_ID_OR_IMMUTABLE_POLICY_CHANGED','CARD_SAMPLE_SCOPE_OR_GRID_CHANGED','CARD_TIME_GRID_CHANGED','ALIGNMENT_AUDIT_FAILED'}),
    ('supported_mechanical_scope_review_required',
     'AI说明当前受支持的零件、引用及验证范围，依据现有证据推荐可行方案；不自动解固定、替换几何或声称任意机构可用。必要时请用户澄清机械目标。',
     {'CONNECTION_GOAL_CONFLICT','CONNECTION_SCOPE_UNSUPPORTED','CONNECTION_REFERENCE_INVALID','CONCENTRIC_SCOPE_CARD_NOT_ELIGIBLE','GEAR_PUMP_SCOPE_UNSUPPORTED','GEAR_GEOMETRY_UNAVAILABLE','EXTERNAL_GEAR_SCOPE_UNSUPPORTED','EXTERNAL_GEAR_REFERENCE_INVALID','EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW','UNSUPPORTED_CARD_MATE','CARD_REQUIRES_ONE_FLOATING_ONE_FIXED',
      'CARD_REQUIRES_ONLY_SELECTED_COMPONENT_FLOATING','CARD_REQUIRES_ALIGNED_INITIAL_AXES_NO_REPOSITIONING',
      'ALIGNMENT_REQUIRES_PARALLEL_AXES','ALIGNMENT_TRANSLATION_LIMIT_EXCEEDED','ALIGNMENT_MOTION_NOT_VERIFIED','MOTION_REQUIRES_ONE_FLOATING_ONE_FIXED',
      'NO_CYLINDRICAL_DRIVE_ON_SELECTED_AXIS', 'NO_MOTION_DRIVE_CANDIDATE'}),
    ('geometry_completeness_review_required',
     'AI读取已保存的扫描范围、预算及续查待办；不把截断当完成，不循环使用自指游标，不为补材料重跑运动求解。',
     {'MOTION_DRIVE_GEOMETRY_BUDGET', 'MOTION_DRIVE_GEOMETRY_INCOMPLETE',
      'MOTION_GEOMETRY_CONTINUATION_LOOP', 'MOTION_GEOMETRY_SCOPE_CHANGED'}),
    ('installation_and_evidence_review_required',
     'AI核对现有安装、路径、构建或证据收集回执并自动整理诊断；不要求用户手工改配置，不删除现场或任意放宽路径保护。',
     {'CANDIDATE_PATH_INVALID', 'COMPILATION_FAILED', 'RUNTIME_LOCATION_UNAVAILABLE',
      'ACCEPTANCE_RUNTIME_PATH_TOO_LONG', 'LINKED_PATH_REFUSED', 'EVIDENCE_MEMBER_TOO_LARGE',
      'SW_INSTALL_PREREQUISITES_MISSING', 'SW_INSTALL_AMBIGUOUS', 'SW_INSTALL_NOT_FOUND', 'WINDOWS_REQUIRED'}),
    ('host_infrastructure_review_required_no_parameter_change',
     'AI离线整理已有宿主回执和任务诊断，核对契约、SID及源码身份；这不是用户参数错误。不循环查询不可用宿主、不删除未知记录或重建活会话。',
     {'TASK_OWNER_START_UNCONFIRMED', 'TASK_OWNER_START_BUSY', 'TASK_OWNER_IDENTITY_UNKNOWN',
      'TASK_OWNER_BUILD_MISMATCH', 'TASK_OWNER_LOST', 'TASK_OWNER_STOP_UNCONFIRMED',
      'INVALID_OWNER_ENVIRONMENT', 'INVALID_OWNER_GENERATION', 'INVALID_OWNER_OPERATION',
      'INVALID_OWNER_RESPONSE'}),
    ('legacy_session_finish_required',
     'AI先读取旧工具任务及恢复状态；确认无执行中或未知请求后使用finish_motion_session释放本服务执行器，再准备受管任务，不结束其他进程。',
     {'LEGACY_SESSION_REQUIRES_FINISH'}),
)

TASK_ACTION_CLASSES = {}
for status, instruction, codes in GROUPS:
    for code in codes:
        if code in TASK_ACTION_CLASSES:
            raise ValueError('Duplicate task error policy: ' + code)
        TASK_ACTION_CLASSES[code] = (status, instruction)

# These checks occur before submitting the current request to any CAD worker.
# This says nothing about a *previous* task's restoration.
PRE_DISPATCH_CODES = frozenset({
    'INVALID_MOTION_TYPE', 'INVALID_MOTION_PARAMETERS', 'INVALID_MINIMUM_TRAVEL',
    'INVALID_TASK_KIND', 'CONCENTRIC_FIXED_CARD_PARAMETERS', 'INVALID_ASSEMBLY_PATH',
    'INVALID_INITIAL_STATE', 'INVALID_TASK_ID', 'INCOMPATIBLE_FINISH_CHOICES',
    'TASK_NOT_IN_CURRENT_SERVER', 'PLAN_TOKEN_MISMATCH', *CONFIRMATION_CODES,
})


def task_failure(code, message, diagnostics=None, *, task_id='', asynchronous=False):
    """No task restoration success is inferred from an error code or tool hint."""
    diag = deepcopy(diagnostics or {})
    task_id = task_id if re.fullmatch('[a-f0-9]{32}', task_id or '') else ''
    known_refusal = not asynchronous and code in PRE_DISPATCH_CODES
    host = code.startswith('HOST_') or code in TASK_ACTION_CLASSES and TASK_ACTION_CLASSES[code][0].startswith('host_infrastructure_')
    if host:
        known_refusal = not asynchronous and (diag.get('launch_attempted') is False or code in {'HOST_TASK_COLLISION', 'HOST_PRINCIPAL_UNVERIFIABLE'})
    diag.update(cad_dispatched=False if known_refusal else None, job_created=False if known_refusal else None)
    value = operational_error(code, message, 'unknown', diag, job_created=diag['job_created'])
    if known_refusal:
        value['assertion'] = 'not_applicable'
    action = value['next_action']
    if host:
        status, instruction = next((s, i) for s, i, _ in GROUPS if s.startswith('host_infrastructure_'))
        if code=='HOST_BACKUP_TREE_REFUSED':
            instruction='AI停止从升级备份树启动服务，定位原正式安装目录并核对入口；备份只用于恢复。不能通过改参数、重试启动或删除快照标记绕过。'
    else:
        status, instruction = TASK_ACTION_CLASSES.get(code, NATIVE_ACTION_CLASSES.get(code, (None, None)))
    if status:
        action.update(options_status=status, instruction=instruction)
    if code=='PLAN_TOKEN_MISMATCH' and not asynchronous and diag.get('current_plan_still_valid') is True:
        action.update(instruction='本次输入令牌错误，当前方案未消费且无需重建。AI读取原任务取得当前令牌，逐项核对方案与已有明确授权一致后才可提交；方案或授权改变须重新确认。不得猜令牌，不自动重试写入。',
                      requires_new_plan=False,readback_required=True,confirmation_must_match_current_proposal=True)
    # Native errors retain their more specific operational_error classifications.
    if code == 'INVALID_TASK_ID':
        value['message'] = 'task_id须为32位小写十六进制；无任务ID时先不传task_id调用get_mechanism_task。'
    if code == 'LEGACY_SESSION_REQUIRES_FINISH':
        action.update(tool='finish_motion_session', arguments={})
        if diag.get('running_job_ids'):
            action.update(tool='get_job',arguments={'job_id':diag['running_job_ids'][0]},
                          instruction='AI先读取原旧工具任务并等待结束；不在执行中调用finish_motion_session或重复prepare。')
        elif diag.get('pending_requests'):
            action.update(tool='get_recovery_state',arguments={},instruction='AI先读取原请求状态；请求未结束时不释放执行器。')
    else:
        action.update(tool='get_mechanism_task', arguments={'collect_evidence': True} if host else {'task_id': task_id} if task_id else {})
    if code=='EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE' and diag.get('requested_initial_state')=='study_zero' and diag.get('old_study_frame_zero_supported_in_this_task') is False:
        suggestion=diag.get('next_action') or {};arguments=suggestion.get('arguments') or {}
        selected=arguments.get('task_id','')
        if re.fullmatch('[a-f0-9]{32}',selected):
            action.update(tool='plan_mechanism_task',arguments={**arguments,'task_id':selected,'initial_state':'saved'},
                options_status='initial_state_selection_required',instruction=suggestion.get('instruction',message),
                previous_role_ratio_and_group_arguments_must_be_preserved=True,
                initial_state_change_is_not_execution_authorization=True,
                recovery_state_query={'tool':'get_mechanism_task','arguments':{'task_id':selected}})
    if host:
        action['recovery_state_query'] = {'tool': 'get_mechanism_task', 'arguments': {'collect_evidence': True}}
    elif code == 'PRIOR_TASK_UNCONFIRMED' or code.startswith('ORPHAN_'):
        selected=task_id or diag.get('task_id') or ((diag.get('blocking_tasks') or [{}])[0].get('task_id',''))
        selected=selected if re.fullmatch('[a-f0-9]{32}',selected or '') else ''
        action.update(tool='get_mechanism_task',arguments={'task_id':selected} if selected else {},
            recovery_state_query={'tool':'get_mechanism_task','arguments':{'task_id':selected} if selected else {}},
            archive_before_new_prepare=True,
            archive_confirmation={'tool':'finish_mechanism_task',
                'arguments':{'task_id':selected,'close_unrestored':True,'keep_result':False},
                'only_after':'explicit_user_consent_and_all_original_resource_exit_proof',
                'not_verified_result_save':True},
            evidence_collection={'tool':'get_mechanism_task','arguments':{'task_id':selected,'collect_evidence':True} if selected else {'collect_evidence':True}})
        if not selected:
            action.pop('archive_confirmation',None)
            action['task_id_readback_required']=True
        if code == 'ORPHAN_CLOSE_CONFIRMATION_REQUIRED':
            action['instruction']='向用户说明：仅保留现有副本文件和失败证据并关闭记录，恢复未验证，不另存已验证成果。取得明确授权后以close_unrestored=true、keep_result=false核对归档条件；不得自行确认或强制归档。'
    elif code in {'TASK_OWNER_REQUEST_UNCONFIRMED', 'OWNER_OPERATION_OUTCOME_UNCONFIRMED'}:
        action['recovery_state_query'] = {'tool': 'get_mechanism_task', 'arguments': {'task_id': task_id} if task_id else {}}
    if code == 'ORPHAN_EXECUTOR_GATE_NOT_IDLE':
        action['instruction'] += (' AI先核对门禁由哪个安装/客户端持有；若本正式服务仅有空闲旧工具执行器、'
            'active_task为空、没有运行中工具任务且恢复状态明确空闲，可先调用finish_motion_session，'
            '再重新核对归档条件。其他客户端占用或状态未知时保留现场，不结束不明进程。')
        action['conditional_actions'] = [{'tool':'finish_motion_session','arguments':{},'automatic_retry':False,
            'when':'same_service_legacy_executor_only_and_no_active_managed_task_and_no_running_jobs_and_recovery_confirmed_idle'}]
    return value
