"""Local real-CAD dialogue acceptance. Own instances/copies only; no human-client claim."""
import argparse,json,sys,time,traceback,uuid,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dialogue_client import Client
from sw_mcp.conversation import core
from sw_mcp.conversation.owner_transport import OwnerClient,source_manifest
from sw_mcp.conversation.host_scheduler import spec_for,control
from sw_mcp.conversation.process_identity import same_process

ROOT=Path(__file__).resolve().parents[1]


def main(case,keep_last=False,axis_index=2,expected_native_error='',use_recommendation=False,workspace_additions=False):
    folder=ROOT/'runs/dialogue-native'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    work=folder/'work';runtime=ROOT/'runs/cr'
    pump=Path(core.read(ROOT/'圆边配合交付_v0.2/prepared-input.json')['assembly'])
    guide=ROOT/'测试用例/方槽直线导轨/滑轨.SLDASM'
    if workspace_additions:
        assert case=='linear','Workspace-mutation acceptance is restricted to the copied guide model.'
        copied=folder/'models/guide';shutil.copytree(guide.parent,copied);guide=copied/guide.name
        (copied/'operator-notes.md').write_text('before task',encoding='utf8')
    from sw_mcp.conversation import source_integrity
    hashes=source_integrity.snapshot if workspace_additions else core.fixture_hashes
    source=guide if case=='linear' else pump
    before=hashes(source)
    inputs={str(p):hashes(p) for p in ([pump,guide] if case=='chain' else [source])}
    cases=['rotary','linear','concentric','concentric'] if case=='chain' else [case,case]
    result={'status':'running','case':case,'rounds':[],'local_real_CAD':True,'human_WorkBuddy_tested':False,
        'confirmation_source':'existing_authorized_development_cards','source':str(source),
        'work':str(work),'runtime':str(runtime),'sources_sha256':source_manifest(),'source_hashes':before,'keep_last':keep_last}
    result.update(test_card_axis_index=axis_index,expected_native_error=expected_native_error,
        acceptance_scope='native_rejection_reporting_and_restore_not_motion_success' if expected_native_error else 'declared_motion_and_restore',
        motion_passed=False if expected_native_error else None,use_recommendation=use_recommendation,
        workspace_additions_in_isolated_model_copy=workspace_additions)
    core.write(ROOT/'runs/当前正式对话验收.json',{'directory':str(folder),'case':case,'status':'running'})
    c=None;tid=None
    try:
        c=Client(ROOT,work,runtime,folder/'mcp1')
        assert len(c.rpc('tools/list',{})['tools'])==30
        for round_no,mode in enumerate(cases,1):
            source=guide if mode=='linear' else pump
            print('ROUND',mode,round_no,flush=True)
            args={'assembly_path':str(source),'moving_component_hint':'滑块2-1' if mode=='linear' else '长轴',
                'reference_component_hint':'导轨-1' if mode=='linear' else 'GB_Spur_gear_S14A75H50L12.0N-2',
                'task_kind':'concentric' if mode=='concentric' else 'motion','motion':'linear' if mode=='linear' else 'rotary',
                'speed':1 if mode=='linear' else 12,'duration_s':2 if mode=='linear' else 1,'output_fps':30,
                'reverse_direction':mode!='concentric' and round_no==2}
            tid=c.tool('prepare_mechanism_task',**args)['task_id'];state=c.wait(tid)
            assert state['phase']=='proposal_ready',state
            if mode=='concentric':chosen=state['proposals'][0]
            else:
                matches=[r for r in state['proposals'] if abs(r['axis_global'][axis_index])>1-1e-8]
                assert len(matches)==1,{'different_native_axes_require_mechanical_selection':matches,'all':state['proposals']}
                chosen=matches[0]
                if use_recommendation:
                    assert state['suggested_candidate_id']==chosen['candidate_id'],state
                    result.setdefault('recommendations_verified',[]).append(chosen)
            plan=c.tool('plan_mechanism_task',task_id=tid,candidate_id=chosen['candidate_id'])
            if plan.get('needs_initial_state_selection'):
                core.write(folder/f'round-{round_no}-initial-state-choice.json',plan)
                c.tool('plan_mechanism_task',task_id=tid,candidate_id=chosen['candidate_id'],initial_state='study_zero')
            planned=c.wait(tid);assert planned['phase']=='awaiting_confirmation',planned
            core.write(folder/f'round-{round_no}-plan.json',planned)
            if round_no==1:
                assert c.close();c=Client(ROOT,work,runtime,folder/'mcp2')
                resumed=c.tool('get_mechanism_task',task_id=tid)
                assert resumed['server_instance_id']==planned['server_instance_id']
                assert resumed['plan_token']==planned['plan_token']
                assert resumed['connection_check']['journal_idle'] is True
                result['frontend_reconnected_with_live_native_handles']=True
                result['owner_instance_id']=planned['server_instance_id']
            assert planned['server_instance_id']==result['owner_instance_id']
            # Missing authorization must not consume the token or enqueue a solve.
            refusals=[]
            for confirmed,scope_confirmed in [(False,True),(True,False)]:
                response=c.rpc('tools/call',{'name':'execute_mechanism_task','arguments':{
                    'task_id':tid,'plan_token':planned['plan_token'],'confirmed':confirmed,'scope_confirmed':scope_confirmed}})['structuredContent']
                error=response['error']
                assert response['ok'] is False and error['code']=='CONFIRMATION_REQUIRED',response
                assert error['next_action']['options_status']=='explicit_human_confirmation_required',response
                assert error['next_action']['automatic_retry'] is False
                state=c.tool('get_mechanism_task',task_id=tid)
                assert state['phase']=='awaiting_confirmation' and not state['busy'] and not state.get('execution_consumed'),state
                assert state['plan_token']==planned['plan_token']
                refusals.append(error)
            core.write(folder/f'round-{round_no}-confirmation-refusals.json',refusals)
            c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
            verified=c.wait(tid)
            if expected_native_error:
                assert verified['phase']=='failed' and verified['error']['code']==expected_native_error,verified
                assert verified['verification']['declared_scope_passed'] is False
                assert verified['verification']['curve_status']=='not_exported_native_verification_not_passed'
                result.setdefault('expected_native_failures',[]).append(verified)
            else:assert verified['phase']=='verified' and verified['verification']['declared_scope_passed'],verified
            run=verified['verification'].get('run_id',verified['verification'].get('after_run_id'))
            if not expected_native_error:
                history=c.tool('get_motion_summary',run_id=run)
                assert history.get('run_id')==run,history
                result.setdefault('managed_history_reads',[]).append({'run_id':run,'read_via_public_tool':True})
            try:
                c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
                raise AssertionError('duplicate execution accepted')
            except core.StopBatch as error:assert error.code=='TASK_ALREADY_EXECUTED',error
            if case=='chain' and round_no==1:
                recovery=c.tool('get_recovery_state')
                assert recovery['solidworks_pid']==planned['connection_check']['CAD_pid'] if 'connection_check' in planned else recovery.get('solidworks_pid')
                restored=c.tool('restore_model_checkpoint',model_id=verified['model_id'],checkpoint_id=core.read(Path(verified['directory'])/'session/导入.json')['checkpoint']['checkpoint_id'])
                assert restored['restoration_status']=='restored'
                result['explicit_same_session_checkpoint_recovery']=True
            keep=keep_last and round_no==len(cases)
            if workspace_additions:
                out=guide.parent/'out2/位移曲线';out.mkdir(parents=True,exist_ok=True)
                (out/f'round-{round_no}.csv').write_text('time_s,value_m\n0,0\n',encoding='utf8')
                (guide.parent/'operator-notes.md').write_text('host memory changed after solve '+str(round_no),encoding='utf8')
            c.tool('finish_mechanism_task',task_id=tid,keep_result=keep);closed=c.wait(tid)
            assert closed['closed'],closed
            if keep:
                assert closed['finish']['restoration_status']=='not_requested_result_preserved',closed
                assert Path(closed['finish']['result_assembly_path']).is_file()
                assert closed['finish']['session']['committed_copy_preserved'] is True
            else:assert closed['finish']['restoration']['restoration_status']=='restored',closed
            assert closed['finish']['native_exit']['normal_zero_exit'] is True,closed
            assert closed['finish']['executor_exit']['executor_exit_code']==0,closed
            assert closed['finish']['source_files_unchanged'] is True
            if workspace_additions:
                integrity=closed['finish']['source_integrity']
                assert integrity['scope']=='native_import_frozen_dependencies' and integrity['input_count']==len(closed['source_dependency_hashes']),integrity
                assert integrity['input_count']>1 and not any(r['path']=='operator-notes.md' for r in integrity['added']),integrity
                assert any(r['path']==f'out2/位移曲线/round-{round_no}.csv' for r in integrity['added']),integrity
                result.setdefault('workspace_additions_checked',[]).append(integrity)
            result['rounds'].append(closed);tid=None
            core.write(folder/'result.json',result)
        assert all(hashes(Path(p))==recorded for p,recorded in inputs.items())
        result['evidence']=c.tool('get_mechanism_task',collect_evidence=True)
        assert c.close();c=None
        result['owner_idle_shutdown']=OwnerClient(ROOT,work,runtime).call('shutdown_idle')
        identity=core.read(work/'owner.json')['identity'];deadline=time.monotonic()+15
        while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        assert same_process(identity)['status']!='same'
        spec=spec_for(work)
        for _ in range(20):
            if not control(spec,'query').get('running_instances'):break
            time.sleep(.2)
        result['host_test_registration_removed']=control(spec,'unregister')
        result.update(status='pass',source_files_unchanged=True,two_rounds_same_owner=True,motion_passed=not bool(expected_native_error))
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc(),active_task=tid)
        if c and tid:
            try:
                state=c.tool('get_mechanism_task',task_id=tid);result['last_task']=state
                if not state.get('busy') and not state.get('closed') and not state.get('error',{}).get('native_unknown'):
                    c.tool('finish_mechanism_task',task_id=tid);result['failure_cleanup']=c.wait(tid)
            except Exception as cleanup:result['cleanup_error']=str(cleanup)
        raise
    finally:
        if c:c.close()
        core.write(folder/'result.json',result)
        core.write(ROOT/'runs/当前正式对话验收.json',{'directory':str(folder),'case':case,'status':result['status']})
        print(json.dumps({'case':case,'status':result['status'],'directory':str(folder),'rounds':len(result['rounds'])},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',choices=['rotary','linear','concentric','chain'],required=True);p.add_argument('--keep-last',action='store_true')
    p.add_argument('--axis-index',type=int,choices=[0,1,2],default=2,help='Explicit developer test-card world axis; not inferred from a part name')
    p.add_argument('--expect-native-error',default='');p.add_argument('--use-recommendation',action='store_true')
    p.add_argument('--workspace-additions',action='store_true',help='Add CSV and edit non-CAD notes after solve, in an isolated input copy only')
    args=p.parse_args();main(args.case,args.keep_last,args.axis_index,args.expect_native_error,args.use_recommendation,args.workspace_additions)
