"""Explicit developer CAD card: supplied copies, ratio provenance and same-owner reuse.

Run only in a clean installed candidate. Assembly files are supplied locally and
never distributed by the source package. This is not a human WorkBuddy result.
"""
import argparse,json,os,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dialogue_client import Client
from sw_mcp.conversation import core,external_gears as eg
from sw_mcp.conversation.task_engine import ConversationSession
from sw_mcp.conversation.motion_tasks import pose_snapshot,require_same_poses
from sw_mcp.conversation.owner_transport import OwnerClient,source_manifest
from sw_mcp.conversation.host_scheduler import spec_for,control
from sw_mcp.conversation.process_identity import same_process


class ObservedClient(Client):
    """Poll only the task owner; every native call is issued once by the task."""
    def wait(self,task_id,maximum_s=650):
        deadline=time.monotonic()+maximum_s
        while time.monotonic()<deadline:
            state=self.tool('get_mechanism_task',task_id=task_id)
            observation={k:state.get(k) for k in ('task_id','busy','phase','native_stage','round_index','round_total','progress','updated_at')}
            with (self.folder.parent/'task-progress.jsonl').open('a',encoding='utf8') as stream:
                stream.write(json.dumps(observation,ensure_ascii=False)+'\n')
            if not state['busy']:return state
            time.sleep(1)
        raise core.StopBatch('ACCEPTANCE_WAIT_EXPIRED','仅停止等待，未结束任务或原生进程。')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--assembly',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--runtime-base',type=Path,required=True)
    parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    assert not (ROOT/'runs/executor-state.json').exists(),'Use a clean isolated installation; retain historical journals.'
    folder=core.no_links(args.output);folder.mkdir(parents=True,exist_ok=False);work=folder/'work'
    sources=[core.no_links(p) for p in args.assembly];before={str(p):core.fixture_hashes(p) for p in sources}
    result={'status':'running','version':core.VERSION,'sources_sha256':source_manifest(),'source_files':before,
        'local_real_CAD':True,'human_WorkBuddy_tested':False,'force_termination':False,'rounds':[],
        'confirmation_source':'user_authorized_local_development_card_not_human_client_confirmation'}
    c=None;tid=None;s=None
    try:
        if args.rollback:
            class RollbackSession(ConversationSession):
                def rescan(self,hint=''):
                    self.initial_inspection=self.call('inspect_model',model_id=self.model,detail_level='full')
                    self.survey=self.call('_survey_external_gear_pair',model_id=self.model)
                    return eg.recommend(self.survey)['proposals'][0]
            prior=os.environ.get('SW_MCP_FAULT_TESTS');os.environ['SW_MCP_FAULT_TESTS']='1'
            try:
                s=RollbackSession(ROOT,folder/'rollback',args.runtime_base);rec=s.discover(sources[0]);ratio=rec['gear_ratio']
                p=s.call('_preview_external_gear_pair',model_id=s.model,recommendation_json=json.dumps(rec),numerator=ratio['numerator'],denominator=ratio['denominator'])
                try:s.call('_test_external_gear_rollback',plan_id=p['plan_id']);raise AssertionError('controlled rollback missing')
                except Exception as error:
                    assert getattr(error,'code',None)=='GEAR_APPLY_ROLLED_BACK',str(error);result['controlled_rollback']={'code':error.code,'diagnostics':error.diagnostics}
                assert not s.unknown
                after=s.call('inspect_model',model_id=s.model,detail_level='full')
                result['rollback_pose']=require_same_poses(pose_snapshot(s.initial_inspection['components']),pose_snapshot(after['components']),'external_rollback')
                assert len(after['mates'])==len(s.initial_inspection['mates'])
                assert {r['component_id']:r['fixed_component'] for r in after['components']}=={r['component_id']:r['fixed_component'] for r in s.initial_inspection['components']}
                s.restore();result['rollback_cleanup']=s.close();s=None
            finally:
                if prior is None:os.environ.pop('SW_MCP_FAULT_TESTS',None)
                else:os.environ['SW_MCP_FAULT_TESTS']=prior
        c=ObservedClient(ROOT,work,args.runtime_base,folder/'frontend1',entry=ROOT/'motion_server.py')
        assert len(c.rpc('tools/list',{})['tools'])==30
        owner=None
        for index,source in enumerate(sources):
            reverse=index%2==1
            print('EXTERNAL GEAR ROUND',index+1,str(source),flush=True)
            tid=c.tool('prepare_mechanism_task',assembly_path=str(source),task_kind='external_gear_pair',reverse_direction=reverse)['task_id']
            prepared=c.wait(tid);assert prepared['phase']=='proposal_ready',prepared
            c.tool('plan_mechanism_task',task_id=tid);planned=c.wait(tid);core.write(folder/f'round-{index+1}-plan.json',planned)
            assert planned['phase']=='awaiting_confirmation',planned
            if owner is None:
                owner=planned['server_instance_id'];assert c.close();c=ObservedClient(ROOT,work,args.runtime_base,folder/'frontend2',entry=ROOT/'motion_server.py')
                assert c.tool('get_mechanism_task',task_id=tid)['plan_token']==planned['plan_token']
            assert planned['server_instance_id']==owner
            try:c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True);raise AssertionError('missing scope confirmation accepted')
            except core.StopBatch as error:assert error.code=='CONFIRMATION_REQUIRED'
            assert c.tool('get_mechanism_task',task_id=tid).get('execution_consumed') is not True
            try:c.tool('execute_mechanism_task',task_id=tid,plan_token='0'*32,confirmed=True,scope_confirmed=True);raise AssertionError('wrong token accepted')
            except core.StopBatch as error:
                assert error.code=='PLAN_TOKEN_MISMATCH' and error.diagnostics['diagnostics']['current_plan_still_valid']
                assert error.diagnostics['next_action']['readback_required'] and error.diagnostics['next_action']['requires_new_plan'] is False
                core.write(folder/f'round-{index+1}-token-refusal.json',error.diagnostics)
            readback=c.tool('get_mechanism_task',task_id=tid)
            assert readback['phase']=='awaiting_confirmation' and not readback.get('execution_consumed')
            assert readback['plan_token']==planned['plan_token'] and readback['proposal']==planned['proposal']
            c.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
            verified=c.wait(tid);core.write(folder/f'round-{index+1}-verified.json',verified)
            assert verified['phase']=='verified' and verified['verification']['declared_scope_passed'],verified
            v=verified['verification'];assert v['repeatability']['passed'] and not v['contact_or_tooth_geometry_validated']
            ratio=v['gear_ratio']['numerator']/v['gear_ratio']['denominator'];target=v['motion']['signed_target_travel_deg']
            for run in v['runs']:
                a=run['audit'];assert a['passed']
                assert abs(a['signed_final_degrees'][v['roles']['input_shaft']]-target)<.1
                assert abs(a['signed_final_degrees'][v['roles']['output_shaft']]+target*ratio)<.1
            try:c.tool('execute_mechanism_task',task_id=tid,plan_token='0'*32,confirmed=True,scope_confirmed=True);raise AssertionError('duplicate accepted')
            except core.StopBatch as error:assert error.code=='TASK_ALREADY_EXECUTED'
            keep=index==len(sources)-1
            c.tool('finish_mechanism_task',task_id=tid,keep_result=keep);closed=c.wait(tid)
            assert closed['closed'] and closed['finish']['source_files_unchanged'],closed
            assert closed['finish']['native_exit']['native_process_exited'] and closed['finish']['executor_exit']['executor_exit_code']==0
            if not keep:assert closed['finish']['restoration']['restoration_status']=='restored' and closed['finish']['cleanup_status']=='pass'
            else:result['saved_assembly']=closed['finish']['result_assembly_path']
            result['rounds'].append(closed);core.write(folder/'result.json',result);tid=None
        # Reopen and plan without execution: persisted native gear ratio and
        # healthy constraints must all be reused, with zero new mate actions.
        tid=c.tool('prepare_mechanism_task',assembly_path=result['saved_assembly'],task_kind='external_gear_pair')['task_id']
        reopened=c.wait(tid);assert reopened['phase']=='proposal_ready',reopened
        c.tool('plan_mechanism_task',task_id=tid);replanned=c.wait(tid);assert replanned['phase']=='awaiting_confirmation',replanned
        p=replanned['proposal'];assert p['expected_added_mates']==0 and p['existing_gear_feature_id'] is not None,p
        assert p['ratio_provenance']['source']=='existing_native_gear_mate'
        result['saved_reopen_plan']=replanned
        c.tool('finish_mechanism_task',task_id=tid);closed=c.wait(tid);assert closed['closed'],closed;tid=None
        result['saved_reopen_cleanup']=closed
        assert all(core.fixture_hashes(p)==before[str(p)] for p in sources)
        result['evidence']=c.tool('get_mechanism_task',collect_evidence=True);assert c.close();c=None
        result['owner_shutdown']=OwnerClient(ROOT,work,args.runtime_base).call('shutdown_idle')
        identity=core.read(work/'owner.json')['identity'];deadline=time.monotonic()+20
        while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        assert same_process(identity)['status']!='same';spec=spec_for(work)
        result['registration_removed']=control(spec,'unregister');assert not result['registration_removed']['registered']
        observations=[json.loads(line) for line in (folder/'task-progress.jsonl').read_text(encoding='utf8').splitlines()]
        active=[v for v in observations if v['busy'] and v.get('round_index') and v['phase'] in {'running','verified'} and not v.get('progress',{}).get('verification_passed')]
        assert {v['round_index'] for v in active}=={1,2},'both independent rounds must be visible'
        assert all(v['phase']=='running' for v in active),'per-round native results cannot mark the whole task verified'
        records=[v['progress'] for v in active if v.get('progress',{}).get('native_progress_observed')]
        assert records and any(v['stage']=='native_calculate' for v in records)
        assert all(v['overall_fraction'] is None and v['estimated_remaining_s'] is None and not v['heartbeat_proves_native_progress'] for v in records)
        result['progress_acceptance']={'observations':len(observations),'rounds_observed':[1,2],
            'native_stages':sorted({v['stage'] for v in records}),'task_not_prematurely_verified':True,'no_native_progress_inferred_from_heartbeat':True}
        result.update(status='pass',same_owner=True,source_files_unchanged=True)
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
        core.write(folder/'result.json',result);print({'status':result['status'],'directory':str(folder)},flush=True)


if __name__=='__main__':main()
