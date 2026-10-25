"""Explicit own-CAD card: reconnect an idle legacy bridge, then two pump tasks.

Requires a clean isolated installed package and an explicitly selected assembly.
Never attaches an existing user CAD instance or deletes its recovery journal.
"""
import argparse,os,sys,time,traceback,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dialogue_client import Client
from sw_mcp.conversation import core,sw_install,startup_gate
from sw_mcp.conversation.mate_worker import compile_runtime
from sw_mcp.conversation.owner_transport import OwnerClient,source_manifest
from sw_mcp.conversation.host_scheduler import spec_for,control
from sw_mcp.conversation.process_identity import same_process


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--assembly',type=Path,required=True)
    parser.add_argument('--runtime-base',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=core.no_links(args.assembly);folder=core.no_links(args.output)
    folder.mkdir(parents=True,exist_ok=False);work=folder/'work';native=folder/'legacy-empty';native.mkdir()
    assert not (ROOT/'runs/executor-state.json').exists(),'Use an isolated clean installation, retain any existing journal.'
    result={'status':'running','version':core.VERSION,'source':str(source),'source_hashes':core.fixture_hashes(source),
            'sources_sha256':source_manifest(),'local_real_CAD':True,'human_WorkBuddy_tested':False,'rounds':[],
            'confirmation_source':'user_authorized_local_development_card','force_termination':False}
    c=None;tid=None;proc=None
    try:
        startup_gate.require_idle(folder)
        install=Path(sw_install.resolve(ROOT)['resolved_directory']);compile_runtime(ROOT,install,folder)
        def retain(value):
            nonlocal proc
            proc=value
        core.launch(ROOT,install,native,on_started=retain)
        c=Client(ROOT,work,args.runtime_base,folder/'frontend1',entry=ROOT/'motion_server.py')
        env=c.tool('get_environment',solidworks_pid=str(proc.pid));assert env['solidworks_process_id']==proc.pid
        refused=c.rpc('tools/call',{'name':'get_environment','arguments':{'solidworks_pid':'auto'}})['structuredContent']
        assert refused['error']['code']=='STARTUP_SELECTION_NOT_ALLOWED'
        assert refused['error']['diagnostics']['startup_selection_blockers']==['connection_already_used']
        state=c.tool('get_recovery_state');assert state['status']=='idle' and not state['recovery_required']
        assert state['session_admission']['startup_selection_allowed'] is False
        legacy_pid=state['session_admission']['retained_executor_pid'];result['initial_recovery_state']=state
        owner=OwnerClient(ROOT,work,args.runtime_base).call('status')['server_instance_id']
        assert c.close();c=Client(ROOT,work,args.runtime_base,folder/'frontend2',entry=ROOT/'motion_server.py')
        assert c.tool('get_environment')['solidworks_process_id']==proc.pid
        for number in (1,2):
            value=c.rpc('tools/call',{'name':'prepare_mechanism_task','arguments':{
                'assembly_path':str(source),'task_kind':'gear_transmission','reverse_direction':number==2}})['structuredContent']
            assert value['ok'],value
            if number==1:
                proof=value['legacy_session_handoff'];assert proof['confirmed'] and proof['executor_pid']==legacy_pid
                assert proof['executor_exit_code']==0 and not proof['CAD_exit_requested'] and not proof['force_kill']
                assert proc.poll() is None,'Automatic handoff must leave the legacy CAD instance alive.'
                result['automatic_handoff']=proof
            else:assert 'legacy_session_handoff' not in value
            tid=value['result']['task_id'];prepared=c.wait(tid)
            assert prepared['phase']=='proposal_ready' and prepared['server_instance_id']==owner,prepared
            settings=prepared['motion_parameters'];assert settings['requested_minimum_travel']==0 and 'minimum_travel' not in settings
            assert settings['signed_target_travel_deg']==(-72 if number==2 else 72)
            c.tool('plan_mechanism_task',task_id=tid);planned=c.wait(tid);assert planned['phase']=='awaiting_confirmation',planned
            c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
            verified=c.wait(tid);assert verified['phase']=='verified' and verified['verification']['declared_scope_passed'],verified
            assert verified['verification']['repeatability']['passed']
            for run in verified['verification']['runs']:
                assert run['audit']['passed'] and run['audit']['rows']==558
                assert abs(run['audit']['signed_final_degrees']['input_shaft']-settings['signed_target_travel_deg'])<.1
            c.tool('finish_mechanism_task',task_id=tid);closed=c.wait(tid)
            assert closed['closed'] and closed['finish']['cleanup_status']=='pass',closed
            assert closed['finish']['source_files_unchanged'] and closed['finish']['restoration']['restoration_status']=='restored'
            assert closed['finish']['executor_exit']['executor_exit_code']==0
            result['rounds'].append(closed);core.write(folder/'result.json',result);tid=None
        # Handoff never closes CAD. Close only the retained empty instance that
        # this card launched, now that both managed executors have ended.
        core.close_owned(None,proc,ROOT,native);result['legacy_empty_exit']=core.read(native/'exit.json');proc=None
        assert core.fixture_hashes(source)==result['source_hashes']
        result['evidence']=c.tool('get_mechanism_task',collect_evidence=True);assert c.close();c=None
        result['owner_shutdown']=OwnerClient(ROOT,work,args.runtime_base).call('shutdown_idle')
        identity=core.read(work/'owner.json')['identity'];deadline=time.monotonic()+20
        while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        assert same_process(identity)['status']!='same';spec=spec_for(work)
        for _ in range(30):
            if not control(spec,'query').get('running_instances'):break
            time.sleep(.1)
        result['registration_removed']=control(spec,'unregister');assert not result['registration_removed']['registered']
        result.update(status='pass',same_owner_two_transmission_tasks=True,original_source_unchanged=True)
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc(),active_task=tid)
        if c and tid:
            try:
                state=c.tool('get_mechanism_task',task_id=tid);result['last_task']=state
                if not state.get('busy') and not state.get('error',{}).get('native_unknown'):
                    c.tool('finish_mechanism_task',task_id=tid);result['failure_cleanup']=c.wait(tid)
            except Exception as cleanup:result['cleanup_error']=str(cleanup)
        # Unknown state is preserved; no blanket cleanup or termination.
        raise
    finally:
        if c:c.close()
        core.write(folder/'result.json',result)
        print({'status':result['status'],'directory':str(folder),'rounds':len(result['rounds'])},flush=True)


if __name__=='__main__':main()
