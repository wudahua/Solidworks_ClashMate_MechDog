"""Complete read-only component accounting; observations do not establish intent."""
import copy
import hashlib
import json
from collections import Counter,defaultdict
from . import constraint_graph as cg,assembly_connections as joints,assembly_constraints as ac


def recommend(survey,review=None):
    cs=survey.get('components',[]);ids=[c.get('component_id') for c in cs]
    if not survey.get('inventory_complete') or not 1<=len(cs)<=128 or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):
        return {'status':'inventory_review_required','component_count':len(cs),'accounting_complete':False,
                'components':[],'write_dispatched':False,'mechanical_intent_proven':False,'omissions_treated_as_complete':False}
    graph=cg.model(survey);by=graph.by_id
    # Common world grounding must not turn unrelated fixed parts into a rotor.
    internal=copy.deepcopy(survey)
    for c in internal['components']:c['fixed_component']=False
    internal['mates']=[m for m in internal['mates'] if not any(e.get('reference_owner_scope')=='assembly_root' for e in m.get('entities',[]))]
    observed_groups=sorted(cg.model(internal).report()['rigid_groups'],key=lambda r:tuple(sorted(r['components'])));groups=[];membership={}
    for n,row in enumerate(observed_groups,1):
        members=row['components'];anchor=min(members,key=lambda x:(not by[x].get('fixed_component'),-len(graph.adj[x]),by[x]['instance']))
        group={'group_id':'observed-group-'+str(n),'members':members,'instances':[by[x]['instance'] for x in members],
               'anchor_instance':by[anchor]['instance'],'evidence':'supported_internal_constraints_without_fixed_flags_or_root_equations',
               'proposed_action':'preserve_observed_internal_relation','mechanical_membership_confirmed':False,'motion_verified':False}
        groups.append(group)
        for cid in members:membership[cid]=group['group_id']
    unknown=defaultdict(list)
    for row in graph.unknown:
        for cid in row['components']:unknown[cid].append(row['native_feature_id'])
    relationships=[];neighbors=defaultdict(list)
    for a,b in sorted(graph.direct):
        rel=graph.relative(a,b);mobility=joints.mobility(rel['rows'],graph.origin,graph.scale);kind=mobility['recommended_joint_type']
        if kind not in joints.KINDS:continue
        if membership.get(a) and membership.get(a)==membership.get(b):continue
        row={'component_a':a,'component_b':b,'instance_a':by[a]['instance'],'instance_b':by[b]['instance'],
             'suggested_kind':kind,'axis_global':mobility.get('axis_global'),'axis_point_global_m':mobility.get('axis_point_global_m'),
             'supported_effective_rank':rel['supported_effective_rank'],'evidence':'supported_current_whole_inventory_projection',
             'mechanical_goal_confirmed':False,'proposed_action':'preserve_observed_mobility','motion_verified':False}
        relationships.append(row)
        neighbors[a].append(row);neighbors[b].append(row)
    patterns={r['component_id']:r for r in ac.analyze(cs,survey['mates'],structural_relations=survey.get('structural_relations'))['pattern_dependencies']}
    ledger=[];questions=defaultdict(list)
    for cid in sorted(graph.ids):
        c=by[cid];linked=bool(graph.links[cid]);group=membership.get(cid);joint_options=neighbors[cid]
        if cid in graph.patterns:
            resolved=bool((patterns.get(cid) or {}).get('seed_component_ids'))
            category='target_recommendation' if resolved else 'clarification_required'
            reason='preserve_pattern_with_observed_seeds_target' if resolved else 'native_pattern_dependency_requires_group_seed_review'
        elif unknown[cid]:
            category='clarification_required';reason='unmodelled_constraint_requires_preservation_review'
        elif group or joint_options:
            category='observed_relation';reason='preserve_existing_relation_subject_to_mechanical_goal'
        elif c.get('fixed_component'):
            category='clarification_required';reason='fixed_flag_is_not_rigid_group_or_stationary_intent'
        else:
            category='clarification_required';reason='insufficient_supported_connection_evidence'
        record={'component_id':cid,'instance':c['instance'],'category':category,'reason':reason,
                'observed_rigid_group_id':group,'observed_joint_options':sorted({r['suggested_kind'] for r in joint_options}),
                'native_fixed_flag':c.get('fixed_component'),'supported_ground_rank':graph.rank(cid),
                'active_native_link_count':len(graph.links[cid]),'unknown_native_feature_ids':unknown[cid],
                'geometry_complete':c.get('geometry_complete',True),'pattern_dependency':patterns.get(cid),
                'suggested_follow_instances':[by[x]['instance'] for x in (patterns.get(cid) or {}).get('seed_component_ids',[])],
                'already_satisfies_user_goal':None,'mechanical_role':None,'motion_verified':False}
        ledger.append(record)
        if category=='clarification_required':questions[reason].append({'component_id':cid,'instance':c['instance']})
    fingerprint=hashlib.sha256(json.dumps(survey,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return {'schema_version':1,'status':'whole_inventory_recommendations_pending_mechanical_goals','component_count':len(cs),
            'accounted_component_count':len(ledger),'accounting_complete':len(ledger)==len(cs),'snapshot_sha256':fingerprint,
            'components':ledger,'category_counts':dict(Counter(r['category'] for r in ledger)),
            'observed_rigid_groups':groups,'observed_joint_recommendations':relationships,
            'mechanical_question_groups':[{'reason':reason,'components':rows,
                'instruction':'AI先结合用户已说明的用途和现有证据归组；只有仍不明确的机械用途集中询问，不逐个询问，不默认全部静止。'} for reason,rows in sorted(questions.items())],
            'complete_pair_geometry_scan_claimed':False,'all_components_mechanically_assigned':False,
            'global_DOF_certified':False,'motion_verified':False,'write_dispatched':False,'confirmation_token_created':False,
            'scope':'complete_component_accounting_with_supported_observations_not_automatic_design_intent',
            'instruction':'AI使用完整组件表、已有内部刚性与转动/滑动线索提出整装配目标，保持合法运动；全固定不代表无需补配合。遗漏或不支持项必须逐项交代，不能把accounting_complete当作补齐或运动通过。'}


def coverage(survey,goals,group_bindings=()):
    """Account for every part against explicit targets, including reference ends."""
    by={c['component_id']:c for c in survey['components']};links=defaultdict(list)
    for i,g in enumerate(goals):
        for key in ('component_a','component_b'):links[g[key]].append({'source':'goal','index':i,'kind':g['kind']})
    for i,g in enumerate(group_bindings):
        for key in ('component_a','component_b'):links[g[key]].append({'source':'group_binding','index':i,'kind':'rigid'})
    if set(links)-set(by):raise ValueError('completion_target_outside_inventory')
    rows=[{'component_id':cid,'instance':c['instance'],'declared_target_coverage':bool(links[cid]),
           'targets':links[cid],'native_motion_verified':False} for cid,c in sorted(by.items())]
    return {'component_count':len(by),'accounted_component_count':len(rows),'accounting_complete':True,
            'declared_component_count':sum(r['declared_target_coverage'] for r in rows),
            'all_components_have_declared_targets':all(r['declared_target_coverage'] for r in rows),
            'unassigned_components':[r['instance'] for r in rows if not r['declared_target_coverage']],
            'components':rows,'motion_verified':False,'scope':'explicit_mechanical_targets_not_global_DOF_or_full_travel'}
