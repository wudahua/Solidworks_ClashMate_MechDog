"""Readback-only token correction; never authorizes or replays a CAD write."""
from . import core


def require_plan_token(task, supplied):
    if task.get('execution_consumed'):
        raise core.StopBatch('TASK_ALREADY_EXECUTED', '方案已提交；读取原任务结果，不重放写入。')
    if task.get('closed') or task.get('plan_token_revoked') or task.get('phase') != 'awaiting_confirmation' or not task.get('plan_token'):
        raise core.StopBatch('TASK_NOT_READY_FOR_EXECUTION', '当前没有可执行的未消费确认方案；先读取原任务状态。')
    if supplied != task['plan_token']:
        proposal = task.get('proposal') or {}
        raise core.StopBatch('PLAN_TOKEN_MISMATCH', '提交的令牌不匹配；当前方案未消费，AI先读回原任务核对方案及已有授权。', {
            'task_id': task['task_id'], 'phase': task['phase'], 'plan_id': proposal.get('plan_id'),
            'current_plan_still_valid': True, 'submitted_token_accepted': False,
            'execution_consumed': False, 'requires_new_plan': False,
            'retry_after_readback_only': True, 'confirmation_must_match_current_proposal': True,
        })
