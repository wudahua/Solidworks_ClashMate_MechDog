"""Freeze exact per-batch payloads under one declared whole-assembly plan."""
import hashlib,json,uuid,re

MAX_TOTAL_GOALS=128
MAX_TOTAL_MATES=512
MAX_BATCH_GOALS=8
MAX_BATCH_MATES=64

def prepare(proposal):
    goals=proposal['goals'];actions=proposal['actions'];changes=proposal.get('fixed_state_changes',[])
    if not 1<=len(goals)<=MAX_TOTAL_GOALS or len(actions)>MAX_TOTAL_MATES:raise ValueError('whole_assembly_transaction_budget_exceeded')
    seen=set();owned=set();payloads=[];summaries=[]
    for g in goals:
        key=frozenset((g['component_a'],g['component_b']))
        if key in seen:raise ValueError('duplicate_transaction_goal_pair')
        seen.add(key)
    if any(frozenset((a['component_a'],a['component_b'])) not in seen for a in actions):raise ValueError('action_outside_transaction_goals')
    release_ids={c['component_id'] for c in changes}
    if len(release_ids)!=len(changes):raise ValueError('duplicate_transaction_fixed_change')
    for offset in range(0,len(goals),MAX_BATCH_GOALS):
        selected=goals[offset:offset+MAX_BATCH_GOALS];pairs={frozenset((g['component_a'],g['component_b'])) for g in selected}
        targets={g['component_a'] for g in selected};a=[a for a in actions if frozenset((a['component_a'],a['component_b'])) in pairs]
        c=[c for c in changes if c['component_id'] in targets and c['component_id'] not in owned];owned.update(x['component_id'] for x in c)
        if len(a)>MAX_BATCH_MATES:raise ValueError('native_batch_mate_budget_exceeded')
        payload={'goals':selected,'actions':a,'fixed_state_changes':c,'group_bindings':proposal.get('group_bindings',[])}
        if offset==0 and proposal.get('initial_translation') is not None:payload['initial_translation']=proposal['initial_translation']
        text=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False);payloads.append(text)
        summaries.append({'batch_index':len(payloads)-1,'goal_range_start':offset,'goal_range_end_exclusive':offset+len(selected),
                          'goals':len(selected),'added_mates':len(a),'release_fixed_components':[x['instance'] for x in c]})
    if owned!=release_ids:raise ValueError('fixed_change_without_executable_transaction_goal')
    return {'transaction_id':uuid.uuid4().hex,'batch_count':len(payloads),'global_goal_count':len(goals),
            'payload_hashes':[hashlib.sha256(p.encode()).hexdigest() for p in payloads],'payloads':payloads,'batches':summaries,
            'all_or_restore_import_checkpoint':True,'execute_replay_allowed':False}

def request(transaction,index,signature):
    if not isinstance(signature,str) or not re.fullmatch(r'state_[a-f0-9]{24}',signature):raise ValueError('full_mate_plan_signature_domain_required_not_query_signature')
    text=transaction['payloads'][index]
    if hashlib.sha256(text.encode()).hexdigest()!=transaction['payload_hashes'][index]:raise ValueError('transaction_payload_hash_mismatch')
    return {'reference_state_signature':signature,'batch_payload_json':text,
            'batch_transaction':{k:transaction[k] for k in ('transaction_id','batch_count','global_goal_count','payload_hashes')}|{'batch_index':index}}
