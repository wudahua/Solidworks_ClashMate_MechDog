"""Explicit reversible mask changes; no deletion or inferred compression."""
import copy


def prepare(survey,requests):
    if not isinstance(requests,list) or not 1<=len(requests)<=16:raise ValueError('one_to_16_mate_changes_required')
    virtual=copy.deepcopy(survey);by={m['native_feature_id']:m for m in virtual['mates']};seen=set();changes=[]
    for request in requests:
        if not isinstance(request,dict) or set(request)!={'native_feature_id','suppressed'}:raise ValueError('invalid_mate_change_fields')
        fid=request['native_feature_id'];after=request['suppressed']
        if type(fid) is not int or fid<=0 or type(after) is not bool or fid in seen:raise ValueError('invalid_or_duplicate_mate_change')
        seen.add(fid);m=by.get(fid)
        nonlinear={r.get('native_feature_id') for r in survey.get('nonlinear_constraints',[])}
        if m is None or m.get('type') not in {0,1,2,3,5,6} or fid in nonlinear or 'limit' in (m.get('native_feature_type') or '').lower() or type(m.get('suppressed')) is not bool or type(m.get('error')) is not int or m['error']!=0 or m.get('warning'):
            raise ValueError('mate_change_requires_observed_healthy_basic_mate')
        if m['suppressed']==after:raise ValueError('mate_change_already_in_requested_state')
        changes.append({'native_feature_id':fid,'name':m['name'],'type':m['type'],'before':m['suppressed'],'after':after,'action':'set_suppressed'})
        m['suppressed']=after
    # A prepared constraint-state observation precedes these approved virtual
    # changes; it must not masquerade as the predicted native state afterwards.
    for c in virtual['components']:
        c['constraint_state']={'status':'not_observed_after_proposed_mate_changes','fully_constrained':None}
    return virtual,changes
