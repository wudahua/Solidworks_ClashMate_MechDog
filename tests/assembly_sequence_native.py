"""Actual formal MCP sequence acceptance on explicit copied CAD fixture truth."""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

bootstrap=argparse.ArgumentParser(add_help=False);bootstrap.add_argument('--project-root',type=Path)
option,_=bootstrap.parse_known_args();ROOT=(option.project_root or Path(__file__).resolve().parents[1]).absolute()
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from dialogue_client import Client
from sw_mcp.conversation import core
from sw_mcp.conversation.owner_transport import OwnerClient,source_manifest
from sw_mcp.conversation.host_scheduler import control
from sw_mcp.conversation.process_identity import same_process


def require(condition,message):
    if not condition:raise core.StopBatch('ACCEPTANCE_ASSERTION_FAILED',message)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project-root',type=Path)
    parser.add_argument('--fixture',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--runtime-base',type=Path,required=True);parser.add_argument('--flat-card',type=Path);parser.add_argument('--include-stop-check',action='store_true');args=parser.parse_args()
    out=core.no_links(args.output);out.mkdir(exist_ok=False,parents=True)
    truth=core.read(args.fixture);source=Path(truth['assembly']);before=core.fixture_hashes(source)
    require(truth['document_count']==3 and truth['initial_total_mates']==0,'fixture truth mismatch')
    work=out/'work';client=None;tid=None;owner=None
    result={'status':'running','source_manifest':source_manifest(),'source_hashes_before':before,
            'human_WorkBuddy_tested':False,'real_user_multilayer_model':False,'force_termination':False,
            'confirmation_source':'user_authorized_local_development_goals_not_human_client_confirmation',
            'rounds':[],'native_exit_warnings':[],'extra_cases':[]}
    def wait(label):
        value=client.wait(tid,1800);core.write(out/(label+'.json'),value)
        require(value.get('phase')!='failed','task failed: '+str((value.get('error') or {}).get('code')))
        return value
    def closed(label,keep=True):
        client.tool('finish_mechanism_task',task_id=tid,keep_result=keep)
        value=wait(label);f=value['finish'];require(value['closed'] and f['next_round_allowed'],'native finish not settled')
        require(f['source_files_unchanged'] and f['executor_exit']['executor_exit_code']==0,'source/executor finish mismatch')
        require(f['native_exit']['native_process_exited'] and not f['native_exit']['force_kill'],'native exit unknown')
        if not f['native_exit']['normal_zero_exit']:
            result['native_exit_warnings'].append({'task_id':tid,'exit_code':f['native_exit']['exit_code'],'cause':'not_proven'})
        return value
    try:
        client=Client(ROOT,work,args.runtime_base,out/'frontend1',entry=ROOT/'motion_server.py')
        tools=client.rpc('tools/list',{})['tools'];require(len(tools)==30,'formal tool count changed')
        plan=next(t for t in tools if t['name']=='plan_mechanism_task')
        require('assembly_sequence' in plan['inputSchema']['properties'],'sequence schema missing')
        for round_index in range(2):
            tid=client.tool('prepare_mechanism_task',assembly_path=str(source),task_kind='assembly_constraints')['task_id']
            ready=wait(f'r{round_index+1}-prepared')
            if owner is None:owner=ready['server_instance_id']
            require(ready['server_instance_id']==owner,'owner changed')
            client.tool('plan_mechanism_task',task_id=tid,assembly_sequence='start')
            ready=wait(f'r{round_index+1}-sequence-start')
            route=ready['assembly_sequence'];require(len(route['steps'])==3,'expected two internal documents and root')
            require(route['steps'][0]['instance'].endswith('/carrier-1'),'deep scope order mismatch')
            record={'sequence_id':route['sequence_id'],'steps':[]};result['rounds'].append(record)
            for step_index in range(3):
                label=f'r{round_index+1}-s{step_index+1}'
                if step_index:
                    previous=tid;reply=client.tool('plan_mechanism_task',task_id=previous,assembly_sequence='continue')
                    tid=reply['task_id'];require(tid!=previous,'new layer reused prior task')
                    duplicate=client.tool('plan_mechanism_task',task_id=previous,assembly_sequence='continue')
                    require(duplicate.get('existing_next_task') and duplicate['task_id']==tid,'duplicate continuation dispatched again')
                    ready=wait(label+'-prepared')
                step=ready['assembly_sequence']['steps'][step_index]
                require(ready['assembly_sequence_step']==step_index,'sequence task index mismatch')
                names=(('marker-1','shaft-1'),('carrier-1','base-1'),('rigid_tree-1','outer_base-1'))[step_index]
                goal={'component_a':names[0],'component_b':names[1],'kind':'rigid'}
                client.tool('plan_mechanism_task',task_id=tid,connection_intent=[goal],completion_scope='whole_assembly')
                planned=wait(label+'-planned')
                require(planned['phase']=='awaiting_confirmation','layer plan not concrete')
                require(planned['proposal']['expected_added_mates']==3,'unexpected minimal mate count')
                client.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
                verified=wait(label+'-verified');proof=verified['verification']
                require(proof['declared_scope_passed'] and proof['whole_assembly_declared_targets_passed'],'declared layer goals not verified')
                require(proof['completed_trials']==6 and all(t['passed'] for t in proof['trials']),'bounded trial mismatch')
                try:
                    client.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
                except core.StopBatch as error:require(error.code=='TASK_ALREADY_EXECUTED','wrong replay refusal')
                else:raise core.StopBatch('ACCEPTANCE_ASSERTION_FAILED','write token replay accepted')
                ended=closed(label+'-closed')
                require(ended['assembly_sequence']['steps'][step_index]['status']=='completed','saved layer not recorded')
                record['steps'].append({'task_id':tid,'added_mates':3,'bounded_trials':6,
                                        'finish':ended['finish'],'scope_instance':step['instance']})
                result['last_task']=tid;core.write(out/'result.json',result)
                if round_index==0 and step_index==0:
                    require(client.close(),'frontend EOF failed');client=None
                    client=Client(ROOT,work,args.runtime_base,out/'frontend2',entry=ROOT/'motion_server.py')
                    resumed=client.tool('get_mechanism_task',task_id=tid)
                    require(resumed['server_instance_id']==owner and resumed['assembly_sequence']['sequence_id']==record['sequence_id'],'reconnect lost sequence')
                    result['frontend_reconnected_same_owner']=True
            route=ended['assembly_sequence']
            require(route['all_supported_documents_completed'] and route['all_layers_completed'],'whole route coverage incomplete')
            record['last_verified_result']=route['last_verified_result'];record['completed']=True
            require(core.fixture_hashes(source)==before,'original fixture changed')
        # Re-import actual saved outer assembly and read all three document mate counts.
        tid=client.tool('prepare_mechanism_task',assembly_path=record['last_verified_result'],task_kind='assembly_constraints')['task_id']
        reopened=wait('saved-root-reopened')
        require(reopened['connection_review']['mate_count']==3,'saved root mate count mismatch')
        require(all(r['internal_mates']==3 for r in reopened['assembly_layers']['layers']),'saved internal mates not preserved')
        closed('saved-root-closed',keep=False);tid=None
        result['actual_saved_root_reopened']=True
        def execute_extra(label,intents,added,trial_count,whole=False):
            client.tool('plan_mechanism_task',task_id=tid,connection_intent=intents,completion_scope='whole_assembly' if whole else 'declared')
            plan=wait(label+'-planned');require(plan['phase']=='awaiting_confirmation','extra concrete plan missing')
            require(plan['proposal']['expected_added_mates']==added,'extra mate count differs')
            client.tool('execute_mechanism_task',task_id=tid,plan_token=plan['plan_token'],confirmed=True,scope_confirmed=True)
            verified=wait(label+'-verified');require(verified['verification']['declared_scope_passed'] and verified['verification']['completed_trials']==trial_count,'extra bounded verification mismatch')
        if args.flat_card:
            flat=core.read(args.flat_card)[0];flat_source=Path(flat['assembly']);flat_before=core.fixture_hashes(flat_source)
            tid=client.tool('prepare_mechanism_task',assembly_path=str(flat_source),task_kind='assembly_constraints')['task_id']
            wait('flat-prepared');client.tool('plan_mechanism_task',task_id=tid,assembly_sequence='start')
            flat_ready=wait('flat-sequence-start');require(flat_ready['phase']=='constraint_review_ready','root-only sequence phase not ready')
            require(len(flat_ready['assembly_sequence']['steps'])==1,'flat model invented an internal layer')
            page=client.tool('plan_mechanism_task',task_id=tid)['connection_draft'];candidates=list(page['candidates']);pages=[page];seen=set()
            while page.get('next_cursor'):
                cursor=page['next_cursor'];require(cursor not in seen,'draft cursor repeated');seen.add(cursor)
                page=client.tool('get_mechanism_task',task_id=tid,draft_cursor=cursor)['connection_draft'];pages.append(page);candidates.extend(page['candidates'])
            intents=[]
            for wanted in flat['draft_goals']:
                candidate=next(c for c in candidates if {c['instance_a'],c['instance_b']}=={wanted['component_a'],wanted['component_b']})
                choices=[o for o in candidate['options'] if o['kind']==wanted['kind']]
                require(not candidate['blocker'] and len(choices)==1,'flat mechanical ambiguity must not be guessed')
                intents.append(choices[0]['connection_intent'])
            core.write(out/'flat-automatic-draft.json',{'pages':pages,'actual_public_intents':intents})
            execute_extra('flat',intents,2,14);ended=closed('flat-closed',False)
            require(ended['assembly_sequence']['status']=='stopped_current_layer_restored','flat restore incorrectly completed sequence')
            require(core.fixture_hashes(flat_source)==flat_before,'flat source changed')
            result['extra_cases'].append({'label':'flat','task_id':tid,'trials':14,'source':str(flat_source),'source_hashes_before':flat_before});tid=None
        if args.include_stop_check:
            tid=client.tool('prepare_mechanism_task',assembly_path=str(source),task_kind='assembly_constraints')['task_id'];wait('partial-prepared')
            client.tool('plan_mechanism_task',task_id=tid,assembly_sequence='start');wait('partial-s1-prepared')
            execute_extra('partial-s1',[{'component_a':'marker-1','component_b':'shaft-1','kind':'rigid'}],3,6,True)
            first=closed('partial-s1-closed');saved=Path(first['finish']['result_assembly_path'])
            saved_before=core.fixture_hashes(saved);parent_id=tid
            tid=client.tool('plan_mechanism_task',task_id=parent_id,assembly_sequence='continue')['task_id']
            second=wait('partial-s2-prepared');require(second['connection_review']['mate_count']==0,'parent no longer missing expected mates')
            require(any(r['instance'].endswith('/carrier-1') and r['internal_mates']==3 for r in second['assembly_layers']['layers']),'earlier internal result missing')
            stopped=client.tool('plan_mechanism_task',task_id=tid,assembly_sequence='stop');require(stopped['native_calls'] is False,'stop made native call')
            ended=closed('partial-s2-closed',False);route=ended['assembly_sequence']
            require(route['status']=='stopped_current_layer_restored' and not route['all_layers_completed'],'partial restore claimed full completion')
            require(route['last_verified_result']==str(saved) and core.fixture_hashes(saved)==saved_before,'restoring parent damaged earlier kept result')
            result['extra_cases'].extend([{'label':'partial-s1','task_id':parent_id,'trials':6},{'label':'partial-s2','task_id':tid,'trials':0}]);tid=None
        result['evidence']=client.tool('get_mechanism_task',collect_evidence=True)
        require(client.close(),'frontend close failed');client=None
        result['owner_shutdown']=OwnerClient(ROOT,work,args.runtime_base).call('shutdown_idle')
        identity=core.read(work/'owner.json')['identity'];deadline=time.monotonic()+20
        while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        require(same_process(identity)['status']!='same','owner still running')
        result['registration_removed']=control(core.read(work/'host-registration.json')['spec'],'unregister')
        require(not result['registration_removed']['registered'],'host registration remains')
        require(core.fixture_hashes(source)==before,'source hashes changed')
        result.update(status='pass',formal_tasks=7+len(result['extra_cases']),bounded_trials=36+sum(c['trials'] for c in result['extra_cases']),total_added_across_copied_rounds=18+(2 if args.flat_card else 0)+(3 if args.include_stop_check else 0),
                      same_owner=True,source_files_unchanged=True,
                      native_lifecycle_all_zero=not result['native_exit_warnings'])
    except Exception as error:
        result.update(status='failed',error_code=getattr(error,'code',type(error).__name__),error=str(error),traceback=traceback.format_exc(),active_task=tid)
        if client and tid:
            try:
                value=client.tool('get_mechanism_task',task_id=tid);core.write(out/'failed-task.json',value)
                if not value.get('busy') and not (value.get('error') or {}).get('native_unknown'):
                    client.tool('finish_mechanism_task',task_id=tid);result['failure_cleanup']=client.wait(tid,1800)
            except Exception as cleanup:result['cleanup_error']=str(cleanup)
        raise
    finally:
        if client:client.close()
        core.write(out/'result.json',result)
        print(json.dumps({k:result.get(k) for k in ('status','formal_tasks','bounded_trials','error_code')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
