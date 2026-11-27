"""Explicit state changes to identified existing mates."""
import copy


def prepare(survey,requests,local_goals=None,*,allow_lock_rotation=False):
    if not isinstance(requests,list) or not 1<=len(requests)<=16:raise ValueError('one_to_16_mate_changes_required')
    virtual=copy.deepcopy(survey);by={m['native_feature_id']:m for m in virtual['mates']};seen=set();changes=[]
    local_pairs=None if local_goals is None else {frozenset((g['component_a'],g['component_b'])) for g in local_goals}
    nonlinear={r.get('native_feature_id') for r in survey.get('nonlinear_constraints',[])}
    for request in requests:
        if not isinstance(request,dict) or set(request) not in ({'native_feature_id','suppressed'},{'native_feature_id','lock_rotation'}):
            raise ValueError('invalid_mate_change_fields')
        lock_change='lock_rotation' in request
        if lock_change and not allow_lock_rotation:
            raise ValueError('concentric_lock_rotation_requires_standalone_assembly_repair')
        fid=request['native_feature_id'];after=request['lock_rotation' if lock_change else 'suppressed']
        if type(fid) is not int or fid<=0 or type(after) is not bool or fid in seen:raise ValueError('invalid_or_duplicate_mate_change')
        seen.add(fid);m=by.get(fid)
        if m is None or m.get('type') not in {0,1,2,3,5,6} or fid in nonlinear or 'limit' in (m.get('native_feature_type') or '').lower() or type(m.get('suppressed')) is not bool or type(m.get('error')) is not int or m['error']!=0 or m.get('warning'):
            raise ValueError('mate_change_requires_observed_healthy_basic_mate')
        refs=m.get('entities') or []
        if local_pairs is not None and (len(refs)!=2 or frozenset(e.get('component_id') for e in refs) not in local_pairs):
            raise ValueError('local_mate_change_requires_matching_declared_pair')
        if lock_change:
            state=m.get('rotation_lock_observation') or {}
            if m['type']!=1 or m['suppressed'] or state.get('status')!='observed' or type(state.get('locked')) is not bool:
                raise ValueError('lock_rotation_requires_active_concentric_with_observed_lock_state')
            before=state['locked']
            action='set_lock_rotation'
            m['rotation_lock_observation']={'status':'proposed','locked':after}
        else:
            before=m['suppressed']
            action='set_suppressed'
            m['suppressed']=after
        if before==after:raise ValueError('mate_change_already_in_requested_state')
        changes.append({'native_feature_id':fid,'name':m['name'],'type':m['type'],'before':before,'after':after,'action':action})
    # A prepared constraint-state observation precedes these approved virtual
    # changes; it must not masquerade as the predicted native state afterwards.
    for c in virtual['components']:
        c['constraint_state']={'status':'not_observed_after_proposed_mate_changes','fully_constrained':None}
    return virtual,changes
