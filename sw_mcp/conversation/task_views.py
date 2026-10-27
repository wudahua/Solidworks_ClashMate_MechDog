"""Remove repeated diagnostic inventories from presentation, never from admission."""
from . import core


def present(value):
    from .managed_wait import MAX_CALL_WAIT_S
    value['native_wait_policy']={'managed_call_maximum_wait_s':MAX_CALL_WAIT_S,'native_operation_cancelled_on_expiry':False,
        'repeated_dispatch_allowed':False,'heartbeat_is_native_progress_proof':False,'duration_is_estimate':False}
    record=core.Path(value['directory'])/'任务状态.json'
    def pointer(path):return {'full_record_path':str(record),'json_pointer':path,'scope':'presentation_only_full_evidence_retained'}
    scope=value.get('scope_review')
    if isinstance(scope,dict):
        resolved=value.get('requires_stationary_scope_review') is False
        if resolved:
            value['scope_review']={'status':'historical_scope_review_resolved_by_current_plan',
                                   'active_blocker':False,**pointer('/scope_review')}
        else:
            compact={k:v for k,v in scope.items() if k not in {'pair_issues','constraint_inventory','stationary_preparation','assembly_constraint_review'}}
            compact['pair_issues']=[{**{k:r.get(k) for k in ('input','output','code','message')},
                                      'diagnostic_details':pointer('/scope_review/pair_issues/'+str(i)+'/diagnostics')}
                                     for i,r in enumerate(scope.get('pair_issues',[]))]
            inventory=scope.get('constraint_inventory') or {}
            compact['constraint_inventory']={k:v for k,v in inventory.items() if k!='components'}
            compact['constraint_inventory']['components']=[{**{k:c.get(k) for k in ('component_id','instance','fixed_component','category','remaining_DOF','stationary_during_motion_verified')},
                'native_constraint_state':(c.get('constraint_state') or {}).get('native_name')} for c in inventory.get('components',[])]
            compact['constraint_inventory']['full_details']=pointer('/scope_review/constraint_inventory')
            preparation=scope.get('stationary_preparation') or {}
            compact['stationary_preparation']={k:v for k,v in preparation.items() if k!='candidates'}
            compact['stationary_preparation']['candidate_instances']=[c['instance'] for c in preparation.get('candidates',[])]
            compact['full_details']=pointer('/scope_review')
            value['scope_review']=compact
    proposal=value.get('proposal') or {}
    recommendation=proposal.get('recommendation') or {}
    completion=recommendation.get('constraint_completion')
    if isinstance(completion,dict):
        recommendation['constraint_completion']={k:v for k,v in completion.items() if k in {'scope','status','uncompleted_components','write_dispatched','fixed_states_preserved'}}
        recommendation['constraint_completion'].update(action_count=len(completion.get('actions',[])),
            duplicate_detailed_actions_inlined=False,execution_actions_json_pointer='/proposal/actions',
            **pointer('/proposal/recommendation/constraint_completion'))
    if value.get('phase')=='planning' and value.get('blocking_code'):
        value['prior_scope_blocking_code']=value.pop('blocking_code')
        value['scope_review_status']='planning_current_intent_not_a_new_scope_rejection'
    return value
