"""Retire a retained, exited CAD task by EOF to its idle owned executor only.

This never reconnects COM, restores a model, rewrites an unknown journal or
terminates a process. A completed response and all original identities matter.
"""
import os
from . import core
from .process_identity import same_process
from ..bridge import CadError


def review(task,session,allow_busy=False):
    result={'eligible':False,'CAD_calls':0,'processes_terminated':False,'restoration_verified':False,'blockers':[]}
    def block(reason):result['blockers'].append(reason);return result
    try:
        if task.get('busy') and not allow_busy:return block('task_still_busy')
        proc=getattr(session,'proc',None);bridge=getattr(session,'bridge',None)
        if not proc or proc.poll() is None:return block('retained_CAD_exit_not_observed')
        if not bridge or not bridge._process:return block('retained_executor_handle_missing')
        ownership=core.read(core.no_links(session.folder/'活会话归属.json'))
        if not str(ownership.get('owner',{}).get('created','')).isdecimal() or same_process(ownership['owner'])['status']!='same':return block('owner_creation_identity_unconfirmed')
        if (ownership.get('owner',{}).get('pid')!=os.getpid() or task.get('server_pid')!=os.getpid()
                or ownership.get('model_id')!=task.get('model_id') or task.get('model_id')!=session.model
                or ownership.get('runtime')!=str(session.runtime) or ownership.get('in_flight')!={}
                or getattr(session,'current_call_for_observation',None)!={} or getattr(session,'pending_native_response',None)):
            return block('task_ownership_or_dispatch_not_settled')
        for role,child in (('CAD',proc),('executor',bridge._process)):
            identity=ownership.get(role) or {}
            if identity.get('pid')!=child.pid or not str(identity.get('created','')).isdecimal():return block('bound_resource_identity_missing')
            state=same_process(identity)
            if role=='CAD' and state['status'] not in {'exited','pid_reused'}:return block('CAD_exit_identity_unconfirmed')
            if role=='executor' and state['status'] not in {'same','exited','pid_reused'}:return block('executor_identity_unconfirmed')
            if role=='executor' and child.poll() is None and state['status']!='same':return block('live_executor_identity_changed')
        with bridge._state_lock:
            if bridge._pending or bridge._quarantined_request is not None:return block('native_request_pending_or_quarantined')
        state=bridge.recovery_state();request=state.get('request_id')
        if (not request or state.get('last_response_request_id')!=request or state.get('executor_pid')!=bridge._process.pid
                or state.get('solidworks_pid')!=proc.pid or state.get('owner_id')!=bridge._owner_id
                or state.get('model_id')!=session.model or state.get('journal_derived_fields_consistent') is not True):
            return block('completed_bound_native_response_not_proven')
        response=bridge.get_request_result(request)
        if (not response or response.get('request_id')!=request or response.get('owner_id')!=bridge._owner_id
                or response.get('model_id')!=session.model or response.get('operation')!=state.get('operation')
                or not response.get('response_sha256')):return block('native_response_artifact_not_bound')
        result.update(eligible=True,CAD_pid=proc.pid,CAD_exit_code=proc.poll(),executor_pid=bridge._process.pid,
            native_request_id=request,native_response_sha256=response['response_sha256'],
            original_native_status=state.get('status'),same_retained_handles=True,
            copy_preserved_without_saving=True,journal_rewritten=False,executor_close_method='stdin_EOF_and_observed_exit')
        return result
    except (core.StopBatch,CadError,OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        return block('retirement_evidence_unavailable:'+str(error)[:160])


def finish(engine,task,session):
    proof=review(task,session,allow_busy=True)
    if not proof['eligible']:raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','原请求或退出身份未确认；未关闭执行器、未恢复CAD。',proof)
    from .task_engine import release_executor
    core.write(session.folder/'CAD退出后资源核对.json',proof)
    native={'owned_pid':proof['CAD_pid'],'native_process_exited':True,'exit_code':proof['CAD_exit_code'],
            'normal_zero_exit':proof['CAD_exit_code']==0,'force_kill':False,'native_exit_observed_by':'retained_Popen'}
    core.write(session.folder/'exit.json',native)
    executor=release_executor(session.bridge,session.folder);session.bridge=None
    session.proc=None;session.ended=True;session.import_restored=False;session.persist_ownership({})
    receipt={'ended':True,'model_id':session.model,'checkpoint_id':session.checkpoint,'runtime':str(session.runtime),
             'import_checkpoint_restored':False,'finish_mode':'failed_native_exited_copy_preserved_without_restore'}
    core.write(session.folder/'会话收尾.json',receipt)
    if task.get('error'):task['original_failure']=task['error']
    integrity=engine._source_review(task,session)
    engine._settle_closed(task,{'session':receipt,'native_exit':native,'executor_exit':executor,'restoration':None,
        'restoration_status':'not_verified','cleanup_status':'owned_resources_released_native_outcome_unverified',
        'previous_task_passed':False,'CAD_calls':0,'processes_terminated':False,'retirement_proof':proof},integrity)
    if integrity['unchanged']:task.update(phase='closed_unverified',task_outcome='failed_native_exited_resources_released')
    engine.save(task)
