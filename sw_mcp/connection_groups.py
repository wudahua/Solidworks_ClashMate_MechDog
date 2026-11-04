"""Expand explicitly declared rigid groups; never infer mechanical ownership."""
import copy
from . import constraint_graph,assembly_constraints,assembly_hierarchy


class GroupIntentError(ValueError):
    def __init__(self,reason,**diagnostics):
        self.diagnostics=diagnostics;super().__init__(reason)


def _local_pattern_scope(survey,ids,patterns,label):
    """Admit only complete, observed local seed chains in one declared group.

    This verifies dependency identity, not rigidity. Every derived member stays
    a verification binding; native seeds receive ordinary minimum complements.
    """
    structure=survey.get('structural_relations') or {};by={c['component_id']:c for c in survey['components']}
    def stop(reason,**details):raise GroupIntentError('pattern_group_requires_seed_scope_review',group=label,scope_reason=reason,**details)
    observed=structure.get('components',[]);features=structure.get('patterns',[])
    if structure.get('feature_inventory_truncated') is not False or structure.get('issues')!=[]:
        stop('structural_inventory_incomplete_or_unresolved')
    rows={r['component_id']:r for r in observed}
    if len(rows)!=len(observed) or set(rows)!=set(by) or any(type(r.get('is_pattern_instance')) is not bool for r in observed):
        stop('structural_component_inventory_mismatch')
    feature_rows={r['native_feature_id']:r for r in observed}
    native={r['native_feature_id']:r for r in features}
    if len(feature_rows)!=len(rows) or len(native)!=len(features) or set(feature_rows)&set(native):stop('structural_feature_identity_ambiguous')
    reviewed={}
    def visit(cid,path):
        if cid not in ids:stop('seed_outside_declared_group',required_seed_instances=[by[cid]['instance']] if cid in by else [],unresolved_seed_ids=[] if cid in by else [cid])
        if cid not in patterns:return
        if cid in path:stop('cyclic_pattern_seed_dependency',instance=by[cid]['instance'])
        if cid in reviewed:return
        row=rows[cid];fid=row['native_feature_id'];parents={p['native_feature_id'] for p in row.get('parent_features',[])}
        if len(row.get('parent_features',[]))>=64:stop('pattern_parent_scan_limit_reached',instance=by[cid]['instance'])
        matched=[p for k,p in native.items() if k in parents or any(c['native_feature_id']==fid for c in p.get('child_features',[]))]
        if not matched:stop('pattern_feature_not_identified',instance=by[cid]['instance'])
        seeds=set()
        for p in matched:
            if p.get('suppressed') is not False or p.get('type') not in {'LocalLPattern','LocalCirPattern'}:
                stop('native_pattern_type_or_suppression_requires_review',instance=by[cid]['instance'])
            if not p.get('seed_component_ids'):stop('pattern_seed_identity_unavailable',instance=by[cid]['instance'])
            if len(p.get('child_features',[]))>=256:stop('pattern_child_scan_limit_reached',instance=by[cid]['instance'])
            if p['native_feature_id'] not in parents or not any(c['native_feature_id']==fid for c in p.get('child_features',[])):
                stop('pattern_parent_child_observations_disagree',instance=by[cid]['instance'])
            seeds.update(p['seed_component_ids'])
        # Preserve additional observed component dependencies, never drop a
        # foreign/omitted seed to manufacture an apparently closed chain.
        seeds.update(feature_rows[k]['component_id'] for k in parents if k in feature_rows)
        if cid in seeds:stop('cyclic_pattern_seed_dependency',instance=by[cid]['instance'])
        for seed in sorted(seeds):visit(seed,path|{cid})
        reviewed[cid]={'component_id':cid,'instance':by[cid]['instance'],'seed_component_ids':sorted(seeds),
            'pattern_feature_ids':sorted(p['native_feature_id'] for p in matched),
            'native_pattern_preserved':True,'individual_mate_write_allowed':False,'rigid_motion_proven':False}
    for cid in sorted(set(ids)&patterns):visit(cid,set())
    return list(reviewed.values())


def expand(survey,intents,groups=None,release_names=None,whole_assembly=False):
    cs=survey['components'];by={c['component_id']:c for c in cs};names={}
    hierarchy=assembly_hierarchy.analyze(cs)
    if not hierarchy['supported_for_connection_writes']:raise GroupIntentError('flexible_subassembly_scope_unsupported')
    for goal in intents:
        for key in ('component_a','component_b'):assembly_hierarchy.require_top_level_target(goal[key],hierarchy)
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
        if hierarchy['parents'][cid] is not None:raise GroupIntentError('nested_component_fixed_release_unsupported',instance=by[cid]['instance'])
        if by[cid].get('fixed_component') is not True:raise GroupIntentError('release_target_not_observed_fixed',instance=by[cid]['instance'])
        if cid in patterns:raise GroupIntentError('pattern_member_fixed_release_unsupported',instance=by[cid]['instance'])
    if released and not any(c.get('fixed_component') is True and hierarchy['parents'][c['component_id']] is None and c['component_id'] not in released for c in cs):
        raise GroupIntentError('fixed_release_requires_an_existing_fixed_reference_to_remain')
    moving={g['component_a'] for g in intents if g['kind']!='rigid'}
    memberships={};normalized=[];group_names=set();pattern_reviews=[]
    for raw in groups or []:
        if not isinstance(raw,dict) or set(raw)-{'name','members','anchor'}:raise GroupIntentError('invalid_rigid_group_fields')
        label=raw.get('name');members=raw.get('members');anchor_name=raw.get('anchor','')
        if not isinstance(label,str) or not label.strip() or len(label)>64 or label.casefold() in group_names:raise GroupIntentError('invalid_or_duplicate_group_name')
        group_names.add(label.casefold())
        maximum_members=128 if whole_assembly else 32
        if not isinstance(members,list) or not 2<=len(members)<=maximum_members:raise GroupIntentError('rigid_group_member_budget',group=label,maximum_members=maximum_members)
        ids=[identify(n) for n in members]
        for cid in ids:assembly_hierarchy.require_top_level_target(cid,hierarchy)
        if len(set(ids))!=len(ids) or any(cid in memberships for cid in ids):raise GroupIntentError('duplicate_or_overlapping_group_members',group=label)
        for cid in ids:memberships[cid]=label
        if any(g['kind']!='rigid' and g['component_a'] in ids and g['component_b'] in ids for g in intents):raise GroupIntentError('mobile_joint_inside_declared_rigid_group',group=label)
        if any(cid in patterns for cid in ids):
            if not whole_assembly:pattern_reviews.extend(_local_pattern_scope(survey,ids,patterns,label))
            deps={r['component_id']:r for r in assembly_constraints.analyze(cs,survey['mates'],structural_relations=survey.get('structural_relations'))['pattern_dependencies']}
            def valid_seed(cid,seen):
                if cid not in ids:return False
                if cid not in patterns:return True
                if cid in seen:return False
                row=deps.get(cid,{})
                return bool(row.get('seed_component_ids')) and all(valid_seed(p,seen|{cid}) for p in row['seed_component_ids'])
            if not all(valid_seed(cid,set()) for cid in ids if cid in patterns):raise GroupIntentError('pattern_seed_group_scope_unresolved',group=label)
        anchor=identify(anchor_name) if anchor_name else min((cid for cid in ids if cid not in patterns),key=lambda cid:(0 if cid in moving else 1 if by[cid].get('fixed_component') and cid not in released else 2,cid))
        if anchor not in ids:raise GroupIntentError('group_anchor_not_a_member',group=label)
        if anchor in patterns:raise GroupIntentError('pattern_instance_cannot_be_group_anchor',group=label)
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
    graph=constraint_graph.model(virtual);bindings=[];active=list(copy.deepcopy(intents));skipped=[];references=[]
    seen={frozenset((g['component_a'],g['component_b'])):g['kind'] for g in active}
    for group in normalized:
        anchor=group['anchor'];connected={anchor};members=group['members']
        if whole_assembly:
            # Keep the declared group anchor for verification; build through
            # already connected native neighbors when anchor geometry cannot
            # supply an independent constraint. Do not invent datum geometry.
            depth={anchor:0};queue=[anchor]
            for peer in queue:
                for cid in sorted(graph.adj[peer]):
                    if cid in members and cid not in depth:depth[cid]=depth[peer]+1;queue.append(cid)
            members=sorted(members,key=lambda cid:(depth.get(cid,129),cid))
        for cid in members:
            if cid==anchor:continue
            binding={'kind':'rigid','component_a':cid,'component_b':anchor,'instance_a':by[cid]['instance'],'instance_b':by[anchor]['instance'],
                'group_name':group['name'],'reference_point_global_m':None,'axis_global':None}
            bindings.append(binding);key=frozenset((cid,anchor))
            if cid in patterns:
                skipped.append({'component_a':cid,'component_b':anchor,'reason':'native_pattern_dependency_preserve_and_verify_only_not_rigid_proof'});continue
            if key in seen:
                if seen[key]!='rigid':raise GroupIntentError('conflicting_expanded_joint_and_group')
                connected.add(cid)
                continue
            if graph.rank(cid,anchor)==6 and cid not in released:
                skipped.append({'component_a':cid,'component_b':anchor,'reason':'supported_indirect_rigidity_already_present_not_finite_motion_proof'});connected.add(cid);continue
            reference=anchor
            if whole_assembly:
                from . import assembly_connections as joints
                def available(peer):
                    candidates=joints._candidates(by[cid],by[peer],graph.origin,graph.scale)
                    return len(joints.ac.basis(graph.relative(cid,peer)['rows']+[r for item in candidates for r in item[4]]))
                if available(anchor)<6:
                    choices=[peer for peer in sorted(graph.adj[cid]&connected) if peer not in patterns and available(peer)==6 and frozenset((cid,peer)) not in seen]
                    if choices:
                        reference=min(choices,key=lambda peer:(-graph.rank(cid,peer),by[peer]['instance']))
                        references.append({'component':by[cid]['instance'],'declared_anchor':by[anchor]['instance'],'construction_reference':by[reference]['instance'],
                            'evidence':'native_neighbor_in_same_declared_group_already_connected_to_anchor_with_sufficient_current_geometry',
                            'membership_inferred_from_name':False})
            active.append({'component_a':cid,'component_b':reference,'kind':'rigid'});seen[frozenset((cid,reference))]='rigid';connected.add(cid)
    permitted={g['component_a'] for g in active}|{b['component_a'] for b in bindings}
    if set(released)-permitted:raise GroupIntentError('fixed_release_not_bound_to_a_declared_moving_target_or_group_member')
    limit=128 if whole_assembly else 8
    if len(active)>limit:return {'status':'group_goal_budget_review_required','expanded_goals':active,'expanded_goal_count':len(active),'maximum_goals':limit,
        'write_dispatched':False,'executable':False,'instruction':'完整声明超过本次有界验证预算，未部分提交。AI按独立机械组拆分方案并分别验证，不截断或默认丢弃成员。'}
    if whole_assembly:active.sort(key=lambda g:g['kind']!='rigid')
    return {'status':'group_expanded' if active else 'supported_groups_need_no_write',
        'goals':active,'planning_survey':virtual,'group_bindings':bindings,'rigid_groups':normalized,'skipped_existing_pairs':skipped,
        'construction_reference_choices':references,
        'pattern_scope_reviews':pattern_reviews,
        'fixed_state_changes':[{'component_id':cid,'instance':by[cid]['instance'],'before':True,'after':False,'action':'release_fixed','reason':'explicit_declared_motion_or_rigid_group_target'} for cid in released],
        'unassigned_components':[c['instance'] for c in cs if c['component_id'] not in assembly_hierarchy.inherited_coverage(set(memberships)|{g[k] for g in active for k in ('component_a','component_b')},hierarchy)[0]],
        'mechanical_ownership_of_unassigned_components_inferred':False,'write_dispatched':False}
