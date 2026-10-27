"""Continue one retained request; never reconstruct a session or replay CAD."""
import json
import time
from . import core
from sw_mcp.bridge import CadError

# Owner work runs asynchronously to the MCP client. This is a bounded transport
# wait policy, not a prediction of mechanical solve duration or native progress.
MAX_CALL_WAIT_S = 3600
POLL_S = .5


def terminal(session, pending):
    bridge=session.bridge
    if not bridge or not session.proc or session.proc.poll() is not None:
        raise core.StopBatch('TASK_NATIVE_CONNECTION_LOST','原CAD连接已退出；保留原请求，不重新附着。')
    if not bridge._process or bridge._process.poll() is not None or not bridge._reader_thread or not bridge._reader_thread.is_alive():
        raise core.StopBatch('TASK_NATIVE_CONNECTION_LOST','原执行器连接已丢失，不能依据文件重建连接。')
    record=bridge.get_request_result(pending['request_id'])
    if record is None:return None
    if (record.get('owner_id')!=bridge._owner_id or record.get('operation')!=pending['operation']
            or record.get('params')!=pending['arguments'] or record.get('model_id')!=pending['model_id']):
        raise core.StopBatch('REQUEST_RESULT_INVALID','迟到响应与原请求绑定不一致。')
    with bridge._state_lock:
        if bridge._pending or bridge._quarantined_request is not None:return None
    state=bridge.recovery_state()
    if (state.get('request_id')!=pending['request_id'] or state.get('last_response_request_id')!=pending['request_id']
            or state.get('owner_id')!=bridge._owner_id or state.get('executor_pid')!=bridge._process.pid
            or state.get('solidworks_pid')!=session.proc.pid or state.get('journal_derived_fields_consistent') is not True):
        raise core.StopBatch('REQUEST_RESULT_INVALID','原连接日志与迟到响应无法交叉核对。')
    response=record['response'];result=response.get('result') or {}
    restoration=result.get('restoration_status',result.get('restoration',{}).get('status','not_required')) if response.get('ok') else response.get('error',{}).get('restoration_status','unknown')
    session.unknown=state.get('recovery_required') is not False or restoration in {'unknown','pending'}
    proof={'request_id':pending['request_id'],'operation':pending['operation'],'response_sha256':record['response_sha256'],
           'response_received_at':record['received_at'],'response_ok':response.get('ok') is True,
           'restoration_status':restoration,'native_state_known':not session.unknown,
           'native_error':response.get('error'),
           'same_retained_handles':True,'additional_native_dispatches':0,'whole_task_verified':False}
    proof['original_response_file']=str(bridge.root/'runs/requests'/(pending['request_id']+'.json'))
    core.write(session.folder/('迟到响应-'+pending['request_id']+'.json'),proof)
    session.late_response_reconciled=proof
    session.pending_native_response=None
    session.persist_ownership()
    return response


def wait(session, error, operation, arguments, started):
    diagnostics=getattr(error,'diagnostics',None) or {}
    request=diagnostics.get('request_id')
    if error.code!='CAD_TIMEOUT' or not request:raise error
    # The original Bridge journal must still bind the exact operation/arguments.
    bridge=session.bridge;state=bridge.recovery_state()
    if state.get('request_id')!=request or state.get('owner_id')!=bridge._owner_id or state.get('operation')!=operation or state.get('params')!=arguments:
        raise error
    pending={'request_id':request,'operation':operation,'arguments':arguments,'model_id':state.get('model_id'),
             'primary_timeout':json.loads(json.dumps(diagnostics)), 'call_wait_budget_s':MAX_CALL_WAIT_S,
             'started_monotonic':started,'same_original_request':True,'additional_native_dispatches':0}
    session.pending_native_response=pending
    core.write(session.folder/('等待超时-'+request+'.json'),{k:v for k,v in pending.items() if k!='started_monotonic'})
    session.persist_ownership()
    # The surrounding watch_call remains alive, so task heartbeats and elapsed
    # time keep advancing. A transport timeout is not a completed task failure.
    while True:
        response=terminal(session,pending)
        if response is not None:
            if not response.get('ok'):
                failure=response.get('error') or {}
                raise CadError(failure.get('code','CAD_ERROR'),failure.get('message','原生请求失败'),
                               failure.get('restoration_status','unknown'),failure.get('diagnostics'),
                               failure.get('document_context_restoration_status','not_required'))
            if session.unknown:raise core.StopBatch('NATIVE_STATE_UNKNOWN','原请求已返回，但恢复仍未确认；未继续任务。',session.late_response_reconciled)
            core.write(session.folder/'calls'/f'{session.serial:04d}-{operation}-late.json',
                       {'operation':operation,'arguments':arguments,'ok':True,'original_timeout_retained':True,
                        'elapsed_s':time.monotonic()-started,'late_response':session.late_response_reconciled})
            return response['result']
        if time.monotonic()-started>=MAX_CALL_WAIT_S:
            raise CadError('CAD_TIMEOUT','已停止等待；原请求可能仍在执行。只读查询原任务和迟到响应，未重派发、未判定求解失败。',
                diagnostics={**diagnostics,'managed_wait_budget_s':MAX_CALL_WAIT_S,'original_request_preserved':True,
                             'whole_task_verified':False,'retry_write_allowed':False})
        time.sleep(POLL_S)


def reconcile(session):
    pending=getattr(session,'pending_native_response',None)
    if pending:return terminal(session,pending)
    return None
