"""Explicit development card: own pump copies, rollback, two tasks and saved reopen."""
import os,sys,time,uuid,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dialogue_client import Client
from sw_mcp.conversation import core,gear_transmission as gt
from sw_mcp.conversation.task_engine import ConversationSession
from sw_mcp.conversation.motion_tasks import pose_snapshot,require_same_poses
from sw_mcp.conversation.owner_transport import OwnerClient,source_manifest
from sw_mcp.conversation.host_scheduler import spec_for,control
from sw_mcp.conversation.process_identity import same_process

ROOT=Path(__file__).resolve().parents[1]

def main():
    folder=ROOT/'runs/gear-native'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    work=folder/'work';runtime=ROOT/'runs/gr';source=Path(core.read(ROOT/'圆边配合交付_v0.2/prepared-input.json')['assembly'])
    before=core.fixture_hashes(source)
    result={'status':'running','version':core.VERSION,'source':str(source),'source_hashes':before,'sources_sha256':source_manifest(),
        'rounds':[],'work':str(work),'runtime':str(runtime),'local_real_CAD':True,'human_WorkBuddy_tested':False,
        'confirmation_source':'user_authorized_local_development_card_not_claimed_human_client_confirmation'}
    core.write(ROOT/'runs/当前完整齿轮传动验收.json',{'directory':str(folder),'status':'running'})
    c=None;tid=None;s=None
    try:
        class RollbackSession(ConversationSession):
            def rescan(self,hint=''):
                self.initial_inspection=self.call('inspect_model',model_id=self.model,detail_level='full')
                return self.call('_preview_gear_transmission',model_id=self.model)
        original=os.environ.get('SW_MCP_FAULT_TESTS');os.environ['SW_MCP_FAULT_TESTS']='1'
        try:
            s=RollbackSession(ROOT,folder/'rollback',runtime)
            plan=s.discover(source);gt.validate_roles(plan)
            try:s.call('_test_gear_transmission_rollback',plan_id=plan['plan_id']);raise AssertionError('controlled failure missing')
            except Exception as error:
                assert getattr(error,'code',None)=='GEAR_APPLY_ROLLED_BACK',str(error)
                result['controlled_rollback_error']={'code':error.code,'diagnostics':error.diagnostics}
            assert not s.unknown
            after=s.call('inspect_model',model_id=s.model,detail_level='full')
            proof=require_same_poses(pose_snapshot(s.initial_inspection['components']),pose_snapshot(after['components']),'rollback_after_unfix')
            assert len(after['mates'])==0
            assert {r['component_id']:r['fixed_component'] for r in after['components']}=={r['component_id']:r['fixed_component'] for r in s.initial_inspection['components']}
            result['rollback_pose_and_fixed_verified']=proof;s.restore();result['rollback_close']=s.close();s=None
        finally:
            if original is None:os.environ.pop('SW_MCP_FAULT_TESTS',None)
            else:os.environ['SW_MCP_FAULT_TESTS']=original
        c=Client(ROOT,work,runtime,folder/'mcp1');assert len(c.rpc('tools/list',{})['tools'])==30
        for number in (1,2):
            print('FULL CHAIN ROUND',number,flush=True)
            tid=c.tool('prepare_mechanism_task',assembly_path=str(source),task_kind='gear_transmission',reverse_direction=number==2)['task_id']
            assert c.wait(tid)['phase']=='proposal_ready'
            c.tool('plan_mechanism_task',task_id=tid);planned=c.wait(tid);assert planned['phase']=='awaiting_confirmation',planned
            if number==1:
                owner=planned['server_instance_id'];assert c.close();c=Client(ROOT,work,runtime,folder/'mcp2')
                assert c.tool('get_mechanism_task',task_id=tid)['plan_token']==planned['plan_token']
            assert owner==planned['server_instance_id']
            refused=c.rpc('tools/call',{'name':'execute_mechanism_task','arguments':{'task_id':tid,'plan_token':planned['plan_token'],'confirmed':True}})['structuredContent']
            assert refused['ok'] is False and refused['error']['code']=='CONFIRMATION_REQUIRED'
            assert c.tool('get_mechanism_task',task_id=tid).get('execution_consumed') is not True
            c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
            verified=c.wait(tid);core.write(folder/f'round-{number}-verification.json',verified)
            assert verified['phase']=='verified' and verified['verification']['declared_scope_passed'],verified
            proof=verified['verification'];assert proof['repeatability']['passed'] and proof['contact_or_tooth_geometry_validated'] is False
            for run in proof['runs']:
                assert run['audit']['passed'] and run['audit']['rows']==558
                assert abs(run['audit']['signed_final_degrees']['input_shaft']-(-72 if number==2 else 72))<.1
                assert abs(run['audit']['signed_final_degrees']['output_shaft']-(72 if number==2 else -72))<.1
            try:c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True);raise AssertionError('duplicate accepted')
            except core.StopBatch as error:assert error.code=='TASK_ALREADY_EXECUTED'
            c.tool('finish_mechanism_task',task_id=tid,keep_result=number==2);closed=c.wait(tid)
            assert closed['closed'] and closed['finish']['source_files_unchanged'],closed
            assert closed['finish']['native_exit']['native_process_exited'] and closed['finish']['executor_exit']['executor_exit_code']==0
            if number==1:assert closed['finish']['restoration']['restoration_status']=='restored' and closed['finish']['cleanup_status']=='pass'
            else:result['saved_result']=closed['finish']['result_assembly_path']
            result['rounds'].append(closed);core.write(folder/'result.json',result);tid=None
        # Reimport the saved result through the official motion task. Read-only
        # inspection during preparation verifies persisted mates/fixed state.
        tid=c.tool('prepare_mechanism_task',assembly_path=result['saved_result'],task_kind='motion',moving_component_hint='长轴',reference_component_hint='泵体')['task_id']
        reopened=c.wait(tid);assert reopened['phase']=='proposal_ready',reopened
        record=core.read(Path(reopened['directory'])/'session/导入.json');model=record['model_id']
        # Persisted initial inspection is owned by the session; its native call
        # receipt is read from disk without invoking another tool or solver.
        calls=sorted((Path(reopened['directory'])/'session/calls').glob('*-inspect_model.json'))
        observed=core.read(calls[0])['result'];assert len(observed['mates'])==9 and sum(not x['fixed_component'] for x in observed['components'])==6
        result['saved_reopen_observation']={'mate_count':9,'moving_components':6,'new_solve_dispatched':False,'model_id':model}
        c.tool('finish_mechanism_task',task_id=tid);end=c.wait(tid);assert end['closed'] and end['finish']['source_files_unchanged']
        result['reopen_cleanup']=end;tid=None
        assert core.fixture_hashes(source)==before
        result['evidence']=c.tool('get_mechanism_task',collect_evidence=True);assert c.close();c=None
        result['owner_shutdown']=OwnerClient(ROOT,work,runtime).call('shutdown_idle')
        identity=core.read(work/'owner.json')['identity'];deadline=time.monotonic()+20
        while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        assert same_process(identity)['status']!='same';spec=spec_for(work)
        for _ in range(30):
            if not control(spec,'query').get('running_instances'):break
            time.sleep(.1)
        result['registration_removed']=control(spec,'unregister');assert result['registration_removed']['registered'] is False
        result.update(status='pass',two_transmission_tasks_same_owner=True,original_source_unchanged=True)
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc(),active_task=tid)
        if c and tid:
            try:
                state=c.tool('get_mechanism_task',task_id=tid);result['last_task']=state
                if not state.get('busy') and not state.get('error',{}).get('native_unknown'):
                    c.tool('finish_mechanism_task',task_id=tid);result['failure_cleanup']=c.wait(tid)
            except Exception as cleanup:result['cleanup_error']=str(cleanup)
        if s and not s.unknown:
            try:s.restore();result['rollback_failure_cleanup']=s.close()
            except Exception as cleanup:result['rollback_cleanup_error']=str(cleanup)
        raise
    finally:
        if c:c.close()
        core.write(folder/'result.json',result);core.write(ROOT/'runs/当前完整齿轮传动验收.json',{'directory':str(folder),'status':result['status']})
        print({'status':result['status'],'directory':str(folder),'rounds':len(result['rounds'])},flush=True)

if __name__=='__main__':main()
