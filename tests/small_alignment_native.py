"""Explicit local own-copy CAD acceptance; no human-client certification."""
import json,sys,time,traceback,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dialogue_client import Client
from sw_mcp.conversation import core
from sw_mcp.conversation.owner_transport import OwnerClient,source_manifest
from sw_mcp.conversation.host_scheduler import spec_for,control
from sw_mcp.conversation.process_identity import same_process

ROOT=Path(__file__).resolve().parents[1]

def main():
    folder=ROOT/'runs/alignment-native'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    work=folder/'work';runtime=ROOT/'runs/cr'
    source=Path(core.read(ROOT/'圆边配合交付_v0.2/prepared-input.json')['assembly']);before=core.fixture_hashes(source)
    result={'status':'running','version':core.VERSION,'source':str(source),'source_hashes':before,'sources_sha256':source_manifest(),
        'rounds':[],'local_real_CAD':True,'human_WorkBuddy_tested':False,'confirmation_source':'authorized_development_acceptance_card_not_human_client',
        'work':str(work),'runtime':str(runtime)}
    core.write(ROOT/'runs/当前小幅对齐验收.json',{'directory':str(folder),'status':'running'})
    c=None;tid=None
    try:
        c=Client(ROOT,work,runtime,folder/'mcp1');assert len(c.rpc('tools/list',{})['tools'])==30
        for number in (1,2):
            print('ROUND',number,flush=True)
            tid=c.tool('prepare_mechanism_task',assembly_path=str(source),task_kind='concentric',moving_component_hint='长轴',reference_component_hint='泵体')['task_id']
            state=c.wait(tid);assert state['phase']=='proposal_ready',state
            chosen=state['proposals'][0]['candidate_id']
            c.tool('plan_mechanism_task',task_id=tid,candidate_id=chosen)
            state=c.wait(tid);assert state['phase']=='alignment_choice_required',state
            assert state['strict_card_rejection']['code']=='CARD_REQUIRES_ALIGNED_INITIAL_AXES_NO_REPOSITIONING'
            c.tool('plan_mechanism_task',task_id=tid,candidate_id=chosen,alignment_mode='small_translation')
            planned=c.wait(tid);assert planned['phase']=='awaiting_confirmation',planned
            assert .0001<planned['alignment_proposal']['expected_translation_mm']<=.01
            if number==1:
                owner=planned['server_instance_id'];assert c.close();c=Client(ROOT,work,runtime,folder/'mcp2')
                assert c.tool('get_mechanism_task',task_id=tid)['plan_token']==planned['plan_token']
            assert planned['server_instance_id']==owner
            refused=c.rpc('tools/call',{'name':'execute_mechanism_task','arguments':{'task_id':tid,'plan_token':planned['plan_token'],
                'confirmed':True,'scope_confirmed':True}})['structuredContent']
            assert refused['ok'] is False and refused['error']['code']=='CONFIRMATION_REQUIRED',refused
            assert c.tool('get_mechanism_task',task_id=tid).get('execution_consumed') is not True
            c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True,alignment_confirmed=True)
            verified=c.wait(tid);core.write(folder/f'round-{number}-verification.json',verified)
            assert verified['phase']=='verified' and verified['verification']['declared_scope_passed'],verified
            proof=verified['verification'];assert proof['pre_alignment_motion_preservation_certified'] is False
            assert len(proof['runs'])==2 and proof['repeatability']['passed'] and proof['alignment']['passed']
            try:
                c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True,alignment_confirmed=True)
                raise AssertionError('duplicate write accepted')
            except core.StopBatch as error:assert error.code=='TASK_ALREADY_EXECUTED',error
            c.tool('finish_mechanism_task',task_id=tid);closed=c.wait(tid)
            assert closed['closed'] and closed['finish']['cleanup_status']=='pass',closed
            assert closed['finish']['restoration']['restoration_status']=='restored'
            assert closed['finish']['native_exit']['normal_zero_exit'] and closed['finish']['executor_exit']['executor_exit_code']==0
            assert closed['finish']['source_files_unchanged'];result['rounds'].append(closed);tid=None
            core.write(folder/'result.json',result)
        assert core.fixture_hashes(source)==before
        result['evidence']=c.tool('get_mechanism_task',collect_evidence=True);assert c.close();c=None
        result['owner_idle_shutdown']=OwnerClient(ROOT,work,runtime).call('shutdown_idle')
        identity=core.read(work/'owner.json')['identity'];deadline=time.monotonic()+20
        while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        assert same_process(identity)['status']!='same'
        spec=spec_for(work)
        for _ in range(30):
            if not control(spec,'query').get('running_instances'):break
            time.sleep(.1)
        result['registration_removed']=control(spec,'unregister');assert result['registration_removed']['registered'] is False
        result.update(status='pass',two_rounds_same_owner=True,original_source_unchanged=True)
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc(),active_task=tid)
        if c and tid:
            try:
                state=c.tool('get_mechanism_task',task_id=tid);result['last_task']=state
                if not state.get('busy') and not state.get('error',{}).get('native_unknown'):
                    c.tool('finish_mechanism_task',task_id=tid);result['failure_cleanup']=c.wait(tid)
            except Exception as cleanup:result['cleanup_error']=str(cleanup)
        raise
    finally:
        if c:c.close()
        core.write(folder/'result.json',result);core.write(ROOT/'runs/当前小幅对齐验收.json',{'directory':str(folder),'status':result['status']})
        print(json.dumps({'status':result['status'],'directory':str(folder),'rounds':len(result['rounds'])},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
