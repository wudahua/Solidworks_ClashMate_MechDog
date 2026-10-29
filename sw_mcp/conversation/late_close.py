"""Complete an already requested close by observing its retained process handle.

No process lookup, COM call, restore, exit request, or termination is performed.
Only a close whose own ExitApp helper succeeded and whose wait timed out qualifies.
"""
from pathlib import Path
from . import core


def read(folder,name):
    return core.read(core.no_links(folder/name))


def reconcile(engine,t,s):
    pending=getattr(s,'pending_owned_close',None)
    if (not pending or t.get('busy') or t.get('closed') or
            (t.get('error') or {}).get('code')!='OWNED_CAD_EXIT_PENDING_NO_TERMINATION'):
        return False
    proc=getattr(s,'proc',None)
    if (proc is None or proc is not getattr(s,'pending_close_process',None) or proc.pid!=pending['pid'] or
            s.bridge is not None or getattr(s,'pending_native_response',None) or
            not s.unknown or s.ended or pending['model_id']!=s.model or pending['checkpoint_id']!=s.checkpoint or
            pending['import_restored']!=s.import_restored or pending['committed']!=s.committed or
            t.get('server_instance_id')!=engine.server_instance_id):
        return False
    folder=s.folder
    ownership=read(folder,'活会话归属.json')
    executor=read(folder,'执行器收尾.json')
    helper=read(folder,'exit-control-exit.json');control=read(folder,'exit-control.json')
    if (ownership.get('in_flight') or ownership.get('pending_native_response') or
            (ownership.get('CAD') or {}).get('pid')!=proc.pid or
            ownership.get('model_id')!=s.model or ownership.get('checkpoint_id')!=s.checkpoint or
            executor.get('confirmed') is not True or executor.get('executor_exit_code')!=0 or
            executor.get('executor_pid')!=(ownership.get('executor') or {}).get('pid') or
            executor.get('force_kill') is not False or helper.get('expected_sw_pid')!=proc.pid or
            helper.get('helper_exit_code')!=0 or helper.get('termination_performed') is not False or
            control.get('ok') is not True or control.get('result',{}).get('pid')!=proc.pid or
            control.get('result',{}).get('exit_requested') is not True):
        return False
    finish=dict(t.get('finish') or {})
    kept=s.committed and not s.import_restored
    if kept:
        # Only joint/concentric workflows supply the saved independent pose proof.
        if (t.get('task_kind') not in {'concentric','gear_transmission','external_gear_pair','assembly_constraints'} or
                t.get('verification',{}).get('declared_scope_passed') is not True or
                finish.get('restoration_status')!='not_requested_result_preserved' or
                not core.restored_ok(finish.get('result_checkpoint_restore') or {}) or
                read(folder,'保留成果核对.json').get('passed') is not True):
            return False
        result_path=core.no_links(Path(read(folder,'导入.json')['path']))
        result_path.relative_to(core.no_links(s.runtime))
        finish.update(result_assembly_path=str(result_path),result_assembly_sha256=core.digest(result_path),
            includes_test_motion_study=t.get('task_kind')!='assembly_constraints',
            result_scope='verified_declared_basic_joint_small_trials_not_global_DOF_or_full_travel' if t.get('task_kind')=='assembly_constraints' else 'verified_declared_motion_or_concentric_scope_not_whole_mechanism_or_DOF')
    elif (not s.import_restored or s.committed or not core.restored_ok(finish.get('restoration') or {}) or
            read(folder,'恢复独立核对.json').get('passed') is not True):
        return False
    # Poll only the exact Popen retained when this close timed out. A recycled PID
    # or a new owner cannot satisfy this in-memory object identity requirement.
    code=proc.poll()
    if code is None:return False
    native={'owned_pid':proc.pid,'exit_code':code,'normal_zero_exit':code==0,'native_process_exited':True,
        'exit_code_process':'owned_SLDWORKS_not_control_helper','helper_exit_code':helper['helper_exit_code'],
        'force_kill':False,'native_exit_observed_by':'retained_Popen_after_original_close_wait',
        'late_exit_observation':True,'CAD_calls':0,'restore_repeated':False,'exit_request_repeated':False}
    core.write(folder/'exit.json',native)
    s.cleanup_warning=native if code else None
    if s.cleanup_warning:core.write(folder/'清理警告.json',native)
    receipt={'ended':True,'committed_copy_preserved':s.committed,'import_checkpoint_restored':s.import_restored,
        'finish_mode':'kept_committed_copy' if kept else 'restored_then_closed','model_id':s.model,
        'checkpoint_id':s.checkpoint,'runtime':str(s.runtime),'cleanup_warning':s.cleanup_warning,
        'late_exit_observation':True}
    core.write(folder/'会话收尾.json',receipt)
    s.unknown=False;s.ended=True;s.persist_ownership({})
    finish.update(session=receipt,native_exit=native,executor_exit=executor,late_exit_observation=True,
        cleanup_status='warning_nonzero_native_exit' if code else 'pass')
    engine._settle_closed(t,finish,engine._source_review(t,s))
    return True
