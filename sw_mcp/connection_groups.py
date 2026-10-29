"""Expand explicitly declared rigid groups; never infer mechanical ownership."""
import copy
from . import constraint_graph


class GroupIntentError(ValueError):
    def __init__(self,reason,**diagnostics):
        self.diagnostics=diagnostics;super().__init__(reason)


def expand(survey,intents,groups=None,release_names=None):
    cs=survey['components'];by={c['component_id']:c for c in cs};names={}
    for c in cs:names.setdefault(c['instance'].casefold(),[]).append(c['component_id'])
    def identify(name):
        if not isinstance(name,str) or not name.strip() or len(name)>512:raise GroupIntentError('invalid_component_name')
        matches=names.get(name.casefold(),[])
        if len(matches)!=1:raise GroupIntentError('group_component_name_not_unique',name=name,matches=[by[x]['instance'] for x in matches])
        return matches[0]
    if groups is not None and (not isinstance(groups,list) or not 1<=len(groups)<=8):raise GroupIntentError('one_to_8_rigid_groups_required')
    if release_names is not None and (not isinstance(release_names,list) or not 1<=len(release_names)<=16):raise GroupIntentError('one_to_16_explicit_fixed_releases_required')
    released=[identify(n) for n in release_names or []]
    if len(set(released))!=len(released):raise GroupIntentError('duplicate_fixed_release')
    patterns={c['component_id'] for c in (survey.get('structural_relations') or {}).get('components',[]) if c.get('is_pattern_instance') is True}
    for cid in released:
        if by[cid].get('fixed_component') is not True:raise GroupIntentError('release_target_not_observed_fixed',instance=by[cid]['instance'])
        if cid in patterns:raise GroupIntentError('pattern_member_fixed_release_unsupported',instance=by[cid]['instance'])
    if released and not any(c.get('fixed_component') is True and c['component_id'] not in released for c in cs):
        raise GroupIntentError('fixed_release_requires_an_existing_fixed_reference_to_remain')
    moving={g['component_a'] for g in intents if g['kind']!='rigid'}
    memberships={};normalized=[];group_names=set()
    for raw in groups or []:
        if not isinstance(raw,dict) or set(raw)-{'name','members','anchor'}:raise GroupIntentError('invalid_rigid_group_fields')
        label=raw.get('name');members=raw.get('members');anchor_name=raw.get('anchor','')
        if not isinstance(label,str) or not label.strip() or len(label)>64 or label.casefold() in group_names:raise GroupIntentError('invalid_or_duplicate_group_name')
        group_names.add(label.casefold())
        if not isinstance(members,list) or not 2<=len(members)<=32:raise GroupIntentError('rigid_group_requires_2_to_32_members',group=label)
        ids=[identify(n) for n in members]
        if len(set(ids))!=len(ids) or any(cid in memberships for cid in ids):raise GroupIntentError('duplicate_or_overlapping_group_members',group=label)
        for cid in ids:memberships[cid]=label
        if any(g['kind']!='rigid' and g['component_a'] in ids and g['component_b'] in ids for g in intents):raise GroupIntentError('mobile_joint_inside_declared_rigid_group',group=label)
        if any(cid in patterns for cid in ids):raise GroupIntentError('pattern_group_requires_seed_scope_review',group=label)
        anchor=identify(anchor_name) if anchor_name else min(ids,key=lambda cid:(0 if cid in moving else 1 if by[cid].get('fixed_component') and cid not in released else 2,cid))
        if anchor not in ids:raise GroupIntentError('group_anchor_not_a_member',group=label)
        normalized.append({'name':label,'members':ids,'instances':[by[x]['instance'] for x in ids],'anchor':anchor,'anchor_instance':by[anchor]['instance'],
            'anchor_source':'explicit_name' if anchor_name else 'declared_moving_endpoint_then_existing_fixed_then_stable_coordinate_choice',
            'mechanical_membership_source':'explicit_user_goal_via_AI_not_geometry_or_name_inference'})
    required=set(moving)
    for group in normalized:
        if moving.intersection(group['members']):required.update(group['members'])
    missing=[cid for cid in sorted(required) if by[cid].get('fixed_component') is True and cid not in released]
    if missing:
        return {'status':'fixed_release_review_required','write_dispatched':False,'executable':False,
            'suggested_release_fixed_components':[by[cid]['instance'] for cid in missing],
            'instruction':'这些固定标志妨碍已声明的运动组。AI说明需解除固定的具体名单；仅在机械目标已明确时重新plan传名单，实际写入仍须确认具体方案。解除固定不证明可运动，也不自动调整旧配合。'}
    virtual=copy.deepcopy(survey)
    for c in virtual['components']:
        if c['component_id'] in released:
            c['fixed_component']=False;c['constraint_state']={'status':'pending_explicit_fixed_release_native_readback','fully_constrained':None,'remaining_DOF':None}
    graph=constraint_graph.model(virtual);bindings=[];active=list(copy.deepcopy(intents));skipped=[]
    seen={frozenset((g['component_a'],g['component_b'])):g['kind'] for g in active}
    for group in normalized:
        anchor=group['anchor']
        for cid in group['members']:
            if cid==anchor:continue
            binding={'kind':'rigid','component_a':cid,'component_b':anchor,'instance_a':by[cid]['instance'],'instance_b':by[anchor]['instance'],
                'group_name':group['name'],'reference_point_global_m':None,'axis_global':None}
            bindings.append(binding);key=frozenset((cid,anchor))
            if key in seen:
                if seen[key]!='rigid':raise GroupIntentError('conflicting_expanded_joint_and_group')
                continue
            if graph.rank(cid,anchor)==6:
                skipped.append({'component_a':cid,'component_b':anchor,'reason':'supported_indirect_rigidity_already_present_not_finite_motion_proof'});continue
            active.append({'component_a':cid,'component_b':anchor,'kind':'rigid'});seen[key]='rigid'
    permitted={g['component_a'] for g in active}|{b['component_a'] for b in bindings}
    if set(released)-permitted:raise GroupIntentError('fixed_release_not_bound_to_a_declared_moving_target_or_group_member')
    if len(active)>8:return {'status':'group_goal_budget_review_required','expanded_goals':active,'expanded_goal_count':len(active),'maximum_goals':8,
        'write_dispatched':False,'executable':False,'instruction':'完整声明超过本次有界验证预算，未部分提交。AI按独立机械组拆分方案并分别验证，不截断或默认丢弃成员。'}
    return {'status':'group_expanded' if active else 'supported_groups_need_no_write',
        'goals':active,'planning_survey':virtual,'group_bindings':bindings,'rigid_groups':normalized,'skipped_existing_pairs':skipped,
        'fixed_state_changes':[{'component_id':cid,'instance':by[cid]['instance'],'before':True,'after':False,'action':'release_fixed','reason':'explicit_declared_motion_or_rigid_group_target'} for cid in released],
        'unassigned_components':[c['instance'] for c in cs if c['component_id'] not in memberships],
        'mechanical_ownership_of_unassigned_components_inferred':False,'write_dispatched':False}
