"""Developer-only real MCP/native CAD acceptance; supplied copies, one owner.

Cards declare concrete local test intent. This is not a human WorkBuddy result.
No termination, native write retry, user model upload, or UI automation.
"""
import argparse,json,sys,time,traceback
from pathlib import Path
bootstrap=argparse.ArgumentParser(add_help=False);bootstrap.add_argument('--project-root',type=Path)
project_option,_=bootstrap.parse_known_args()
ROOT=(project_option.project_root or Path(__file__).resolve().parents[1]).absolute();sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from dialogue_client import Client
from sw_mcp.conversation import core
from sw_mcp.conversation.owner_transport import OwnerClient,source_manifest
from sw_mcp.conversation.host_scheduler import control
from sw_mcp.conversation.process_identity import same_process


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cards',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--runtime-base',type=Path,required=True)
    parser.add_argument('--project-root',type=Path);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();folder=core.no_links(args.output);folder.mkdir(parents=True,exist_ok=args.resume)
    cards=core.read(core.no_links(args.cards));work=folder/'work'
    assert not (ROOT/'runs/executor-state.json').exists(),'Use a clean isolated candidate installation.'
    before={str(core.no_links(Path(c['assembly']))):core.fixture_hashes(Path(c['assembly'])) for c in cards}
    result={'status':'running','version':core.VERSION,'local_real_CAD':True,'human_WorkBuddy_tested':False,
        'source_manifest':source_manifest(),'cards_sha256':core.digest(args.cards),'sources_before':before,
        'confirmation_source':'user_authorized_local_development_cards_not_human_client_confirmation','cases':[],'force_termination':False}
    def verified_finish(closed,card):
        finish=closed['finish'];assert closed['closed'] and finish['session']['ended'] and finish['executor_exit']['confirmed'] and finish['native_exit']['native_process_exited']
        if card.get('keep_result'):
            assert finish['restoration_status']=='not_requested_result_preserved' and finish['includes_test_motion_study'] is False
        else:assert finish['session']['import_checkpoint_restored'] is True and core.restored_ok(finish['restoration'])
        return finish
    client=None;tid=None;owner=None;reconnected=False;start=0
    try:
        if args.resume:
            prior=core.read(folder/'result.json')
            assert prior['source_manifest']==source_manifest() and prior['cards_sha256']==result['cards_sha256'] and prior['sources_before']==before,'Changed product/card/source; do not reuse old native conclusions.'
            backup=folder/('result-before-resume-'+str(time.time_ns())+'.json');core.write(backup,prior)
            result['resumed_evidence']=[];result['prior_result_record']=str(backup)
            for index,card in enumerate(cards):
                closed_path=folder/f'{index+1}-closed.json'
                if not closed_path.exists():break
                closed=core.read(closed_path);finish=verified_finish(closed,card)
                assert closed['source']==card['assembly'] and closed['task_kind']=='assembly_constraints'
                if owner is None:owner=closed['server_instance_id']
                assert closed['server_instance_id']==owner
                case={'label':card['label'],'task_id':closed['task_id'],'finish':finish,'source_files_unchanged':True,'resumed_from_closed_receipts':True,'native_calls_repeated':0}
                if not card.get('read_only'):
                    proof=closed['verification'];planned=core.read(folder/f'{index+1}-plan.json')
                    assert proof['declared_scope_passed'] and proof['completed_trials']==card['expected_trials'] and all(v['passed'] for v in proof['trials'])
                    assert planned['proposal']['expected_added_mates']==card['expected_added_mates']
                    case.update(verification=proof,added_mates=planned['proposal']['expected_added_mates'])
                result['cases'].append(case);result['resumed_evidence'].append(str(closed_path));start=index+1
            reconnected=(folder/'frontend2/handshake.json').exists()
        result['harness_sha256']=core.digest(Path(__file__))
        client=Client(ROOT,work,args.runtime_base,folder/('frontend-resume-'+str(time.time_ns()) if args.resume else 'frontend1'),entry=ROOT/'motion_server.py')
        assert len(client.rpc('tools/list',{})['tools'])==30
        assert client.tool('get_mechanism_task')['active_task'] is None,'Read and finish the existing task; never automatically prepare over it.'
        for index,card in enumerate(cards[start:],start):
            print('CASE',index+1,card['label'],flush=True)
            tid=client.tool('prepare_mechanism_task',assembly_path=card['assembly'],task_kind='assembly_constraints')['task_id']
            state=client.wait(tid,1800);core.write(folder/f'{index+1}-prepared.json',state)
            assert state['phase']=='constraint_review_ready',state
            if owner is None:owner=state['server_instance_id']
            assert owner==state['server_instance_id']
            case={'label':card['label'],'task_id':tid,'prepared_record':str(folder/f'{index+1}-prepared.json')}
            if not card.get('read_only'):
                intents=card.get('connection_intent')
                if card.get('draft_goals'):
                    draft_reply=client.tool('plan_mechanism_task',task_id=tid)
                    page=draft_reply['connection_draft'];pages=[page];candidates=list(page['candidates']);seen=set()
                    while page.get('next_cursor'):
                        cursor=page['next_cursor'];assert cursor not in seen;seen.add(cursor)
                        page=client.tool('get_mechanism_task',task_id=tid,draft_cursor=cursor)['connection_draft']
                        assert page['snapshot_id']==pages[0]['snapshot_id']
                        assert page['search']['pair_range_start']==pages[-1]['search']['pair_range_end_exclusive']
                        pages.append(page);candidates.extend(page['candidates'])
                    assert len({c['candidate_id'] for c in candidates})==len(candidates)
                    intents=[];selected=[]
                    for wanted in card['draft_goals']:
                        candidate=next(c for c in candidates if {c['instance_a'],c['instance_b']}=={wanted['component_a'],wanted['component_b']})
                        assert not candidate['blocker']
                        choices=[o for o in candidate['options'] if o['kind']==wanted['kind']]
                        assert len(choices)==1,'Mechanical axis ambiguity must not be guessed by the harness'
                        intents.append(choices[0]['connection_intent'])
                        selected.append({'candidate':candidate,'selected_option':choices[0]})
                    core.write(folder/f'{index+1}-automatic-draft.json',{'pages':pages,'selected':selected,'actual_public_intents':intents,
                        'scope':'developer_declared_mechanical_goals_not_live_LLM_intent_inference','axis_hint_supplied_in_card':False})
                    case['automatic_draft_record']=str(folder/f'{index+1}-automatic-draft.json')
                client.tool('plan_mechanism_task',task_id=tid,connection_intent=intents)
                planned=client.wait(tid,1800);core.write(folder/f'{index+1}-plan.json',planned)
                assert planned['phase']=='awaiting_confirmation',planned
                assert planned['proposal']['expected_added_mates']==card['expected_added_mates'],planned['proposal']
                if not reconnected:
                    assert client.close();client=Client(ROOT,work,args.runtime_base,folder/'frontend2',entry=ROOT/'motion_server.py')
                    recovered=client.tool('get_mechanism_task',task_id=tid)
                    assert recovered['plan_token']==planned['plan_token'] and recovered['server_instance_id']==owner
                    reconnected=True
                for token,confirmed,scope,expected in [(planned['plan_token'],True,False,'CONFIRMATION_REQUIRED'),('0'*32,True,True,'PLAN_TOKEN_MISMATCH')]:
                    try:client.tool('execute_mechanism_task',task_id=tid,plan_token=token,confirmed=confirmed,scope_confirmed=scope);raise AssertionError('refusal missing')
                    except core.StopBatch as error:assert error.code==expected,(error.code,expected)
                    assert client.tool('get_mechanism_task',task_id=tid).get('execution_consumed') is not True
                client.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True)
                verified=client.wait(tid,1800);core.write(folder/f'{index+1}-verified.json',verified)
                assert verified['phase']=='verified',verified
                proof=verified['verification'];assert proof['declared_scope_passed'] and not proof['native_motion_study_solved']
                assert all(v['passed'] and v['all_poses_restored'] for v in proof['trials'])
                assert proof['completed_trials']==card['expected_trials']
                case.update(verification=proof,added_mates=planned['proposal']['expected_added_mates'])
                try:client.tool('execute_mechanism_task',task_id=tid,plan_token=planned['plan_token'],confirmed=True,scope_confirmed=True);raise AssertionError('execution replay accepted')
                except core.StopBatch as error:assert error.code=='TASK_ALREADY_EXECUTED'
            elif card.get('expected_plan_code'):
                try:client.tool('plan_mechanism_task',task_id=tid,connection_intent=card['connection_intent']);raise AssertionError('read-only scope refusal missing')
                except core.StopBatch as error:
                    assert error.code==card['expected_plan_code'],error.code;case['scope_refusal']=error.diagnostics
            client.tool('finish_mechanism_task',task_id=tid,keep_result=card.get('keep_result',False))
            closed=client.wait(tid,1800);core.write(folder/f'{index+1}-closed.json',closed);assert closed['closed'],closed
            finish=verified_finish(closed,card)
            case['finish']=finish;case['source_files_unchanged']=core.fixture_hashes(Path(card['assembly']))==before[card['assembly']]
            assert case['source_files_unchanged'];result['cases'].append(case);core.write(folder/'result.json',result);tid=None
        result['evidence']=client.tool('get_mechanism_task',collect_evidence=True);assert client.close();client=None
        result['owner_shutdown']=OwnerClient(ROOT,work,args.runtime_base).call('shutdown_idle')
        identity=core.read(work/'owner.json')['identity'];deadline=time.monotonic()+20
        while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
        assert same_process(identity)['status']!='same'
        result['registration_removed']=control(core.read(work/'host-registration.json')['spec'],'unregister')
        assert not result['registration_removed']['registered']
        result.update(status='pass',same_owner=True,reconnected_without_replaying_write=reconnected,source_files_unchanged=True)
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc(),active_task=tid)
        if client and tid:
            try:
                state=client.tool('get_mechanism_task',task_id=tid);result['failed_task']=state
                if not state.get('busy') and not (state.get('error') or {}).get('native_unknown'):
                    client.tool('finish_mechanism_task',task_id=tid);result['failure_cleanup']=client.wait(tid,1800)
            except Exception as cleanup:result['cleanup_error']=str(cleanup)
        raise
    finally:
        if client:client.close()
        core.write(folder/'result.json',result);print({'status':result['status'],'directory':str(folder)},flush=True)


if __name__=='__main__':main()
