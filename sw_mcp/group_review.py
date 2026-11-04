"""Arbitrary named mechanical-group drafts from complete observed mate links.

Seeds express purposes already supplied in the conversation. Paths propose
membership; they never establish rigidity, permit locking, or authorize writes.
"""
from collections import defaultdict
from . import assembly_constraints as ac,assembly_hierarchy,constraint_graph,assembly_connections as joints


def seed_suggestions(survey,overview):
    """Offer references for AI review, never merge unrelated fixed flags."""
    by={c['instance']:c for c in survey.get('components',[])};used=set();out=[]
    for row in overview.get('observed_rigid_groups',[]):
        names=row['top_level_target_instances'];anchor=row['anchor_instance']
        if anchor not in names:continue
        out.append({'suggested_name':'观察组'+str(len(out)+1),'anchor_instance':anchor,'seed_instances':[anchor],
            'observed_related_instances':names,'source':'supported_internal_rigidity_observation_not_mechanical_purpose',
            'requires_mechanical_goal_review':True})
        used.update(names)
    for name,c in sorted(by.items()):
        if c.get('parent_component_id') is None and c.get('fixed_component') is True and name not in used:
            out.append({'suggested_name':'参考组'+str(len(out)+1),'anchor_instance':name,'seed_instances':[name],
                'observed_related_instances':[name],'source':'single_observed_fixed_reference_not_other_fixed_parts_membership',
                'requires_mechanical_goal_review':True})
    return {'candidates':out,'automatic_seed_selection':False,'write_dispatched':False,
        'instruction':'AI复用用户已说明的机械用途为运动组选择代表件，填写group_seeds只读推荐附件。参考候选不是设计意图；不能把所有固定件或浮动件自动并为一组。'}


def recommend(survey,seeds):
    cs=survey.get('components',[]);by={c['component_id']:c for c in cs}
    if not survey.get('inventory_complete') or not 1<=len(cs)<=128 or len(by)!=len(cs):raise ValueError('group_review_requires_complete_unique_inventory')
    hierarchy=assembly_hierarchy.analyze(cs)
    if not hierarchy['supported_for_connection_writes']:raise ValueError('group_review_hierarchy_unsupported')
    if any(p is not None for p in hierarchy['parents'].values()):raise ValueError('group_review_requires_flat_or_selected_layer_scope')
    if not isinstance(seeds,dict) or not 1<=len(seeds)<=128:raise ValueError('group_seeds_require_one_to_128_named_groups')
    names=defaultdict(list)
    for c in cs:names[c['instance'].casefold()].append(c['component_id'])
    labels={};normalized={};anchors={};seen_labels=set()
    for label,members in seeds.items():
        if not isinstance(label,str) or not label.strip() or len(label)>64 or label.casefold() in seen_labels:raise ValueError('group_seed_name_invalid_or_duplicate')
        seen_labels.add(label.casefold())
        if not isinstance(members,list) or not 1<=len(members)<=128:raise ValueError('group_seed_members_require_one_to_128_names')
        ids=[]
        for name in members:
            if not isinstance(name,str) or not name.strip() or len(name)>512:raise ValueError('group_seed_component_name_invalid')
            matches=names.get(name.casefold(),[])
            if len(matches)!=1:raise ValueError('group_seed_component_name_not_unique_or_missing:'+name)
            cid=matches[0];assembly_hierarchy.require_top_level_target(cid,hierarchy)
            if cid in labels:raise ValueError('group_seed_members_overlap')
            labels[cid]=label;ids.append(cid)
        normalized[label]=ids;anchors[label]=ids[0]
    graph=constraint_graph.model(survey);adj={cid:set() for cid in by};features=defaultdict(set);unknown=defaultdict(list);health=[];quarantined=set()
    for row in graph.unknown:
        for cid in row['components']:unknown[cid].append(row['native_feature_id'])
        if row['reason'] in {'reference_outside_observed_inventory_or_unverified_root','not_two_distinct_native_references'}:quarantined.update(row['components'])
    for m in survey['mates']:
        if m.get('suppressed') is True:continue
        if m.get('suppressed') is not False or type(m.get('error')) is not int or m['error']!=0 or m.get('warning'):
            health.append(m.get('native_feature_id'));continue
        es=m.get('entities') or [];ids=list(dict.fromkeys(e.get('component_id') for e in es if e.get('component_id') in by))
        if len(es)!=2 or len(ids)!=2:continue
        a,b=ids;key=tuple(sorted(ids))
        # A healthy, identified native reference pair supplies topology even
        # when its equation is not supported. Keep this uncertainty visible;
        # do not erase that link and thereby invent a unique group path.
        adj[a].add(b);adj[b].add(a);features[key].add(m.get('native_feature_id'))
    # A failed/unknown relation is not an absent edge. Do not route membership
    # through its endpoints. Explicit seeds remain proposals, with blockers.
    assigned=dict(labels);evidence={cid:{'kind':'explicit_conversation_seed','rigidity_proven':False} for cid in labels};alternatives={};reasons={};boundary=dict(labels)
    from . import assembly_overview
    for group in assembly_overview.recommend(survey)['observed_rigid_groups']:
        found={labels[cid] for cid in group['members'] if cid in labels}
        if len(found)!=1:continue
        for cid in group['members']:
            if cid in labels or cid in quarantined:continue
            boundary[cid]=assigned[cid]=next(iter(found));evidence[cid]={'kind':'supported_internal_rigidity_observation_connected_to_seed','rigidity_proven':False,'finite_motion_verified':False}
    # Names are a negative ambiguity guard only: no part is assigned from its
    # name. An integral bearing may have a single shaft path but its races have
    # not thereby acquired the shaft's intended motion.
    bearings={cid for cid,c in by.items() if cid not in labels and
        any(word in c['instance'].casefold() for word in ('bearing','轴承','軸承')) and
        not any(word in c['instance'].casefold() for word in ('cover','housing','cap','盖','蓋','座'))}
    for cid in bearings:
        boundary.pop(cid,None);assigned.pop(cid,None);evidence.pop(cid,None)
    quarantined.update(bearings)
    visited=set()
    for start in sorted(set(by)-set(boundary)):
        if start in visited:continue
        if start in quarantined:
            visited.add(start);alternatives[start]=sorted(normalized) if start in bearings else []
            reasons[start]='integral_bearing_motion_intent' if start in bearings else 'unmodelled_constraint_requires_review';continue
        todo=[start];island=set();found=set();mids=set();uncertain_boundary=False
        while todo:
            cid=todo.pop()
            if cid in island:continue
            if cid in boundary:found.add(boundary[cid]);continue
            if cid in quarantined:uncertain_boundary=True;continue
            island.add(cid)
            for peer in adj[cid]:
                mids.update(features[tuple(sorted((cid,peer)))]);todo.append(peer)
        visited.update(island)
        for cid in island:
            alternatives[cid]=sorted(normalized if uncertain_boundary else found)
            if len(found)==1 and not health and not uncertain_boundary:
                assigned[cid]=next(iter(found));evidence[cid]={'kind':'single_seed_group_native_reference_path_hypothesis','native_feature_ids':sorted(mids),
                    'topology_only_native_feature_ids':sorted({x for peer in island for x in unknown[peer]}&mids),'rigidity_proven':False}
            else:reasons[cid]='native_health_blocks_group_recommendation' if health else 'unresolved_bearing_or_reference_boundary' if uncertain_boundary else 'multiple_seed_groups_reachable' if found else 'no_supported_path_to_seed_group'
    # Pattern links are proposals only and cannot resolve conflicting/unknown
    # mate evidence or invent seeds for an otherwise unconnected pattern.
    deps=ac.analyze(cs,survey['mates'],structural_relations=survey.get('structural_relations'))['pattern_dependencies']
    changed=True
    while changed:
        changed=False
        for p in deps:
            cid=p['component_id'];parents=p['seed_component_ids']
            if cid in assigned or cid in quarantined or health:continue
            groups={assigned.get(x) for x in parents}
            if parents and None not in groups and len(groups)==1 and reasons.get(cid)!='multiple_seed_groups_reachable':
                assigned[cid]=next(iter(groups));evidence[cid]={'kind':'observed_pattern_seed_group_hypothesis','seed_component_ids':parents,'rigidity_proven':False,'pattern_motion_proven':False};changed=True
    components=[];pending=[];review_sets=defaultdict(list)
    for cid,c in sorted(by.items()):
        label=assigned.get(cid);rank=graph.rank(cid,anchors[label]) if label and cid!=anchors[label] else None
        row={'component_id':cid,'instance':c['instance'],'proposed_group':label,'explicit_seed':cid in labels,
            'candidate_groups':alternatives.get(cid,[labels[cid]] if cid in labels else []),'evidence':evidence.get(cid),
            'native_fixed_flag':c.get('fixed_component'),'native_relative_rank_to_group_anchor':rank,
            'relative_motion_would_be_constrained_if_group_chosen':bool(label and rank is not None and rank<6),
            'requires_mechanical_confirmation':True,'membership_confirmed':False,'motion_verified':False,
            'unknown_native_feature_ids':unknown.get(cid,[])}
        if label is None:
            row['reason']=reasons.get(cid,'unresolved_pattern_or_membership');pending.append(row)
        elif cid not in labels:review_sets[label].append(row)
        components.append(row)
    groups=[]
    for label in sorted(normalized):
        ids=normalized[label]+sorted((cid for cid,g in assigned.items() if g==label and cid not in normalized[label]),key=lambda x:by[x]['instance'])
        groups.append({'name':label,'anchor':by[anchors[label]]['instance'],'members':[by[x]['instance'] for x in ids],
            'seed_members':[by[x]['instance'] for x in normalized[label]],'membership_confirmed':False,'motion_verified':False})
    question_sets=defaultdict(list)
    for row in pending:question_sets[(row['reason'],tuple(row['candidate_groups']))].append(row['instance'])
    questions=[{'reason':key[0],'candidate_groups':list(key[1]),'instances':values,
        'independent_motion_option_available':True,
        'question':('这些名称提示可能是整件轴承，不能从相邻轴推出内外圈应如何运动。AI复用已确认用途，必要时一次确认这些整件应静止还是随指定组；名称只触发疑问，不用于自动归组。' if key[0]=='integral_bearing_motion_intent' else
        '这些组件的已观察路径涉及多个运动组或证据不足。AI复用已明确用途，只集中澄清它们应随哪组、还是分别保留独立相对运动；不能把剩余件默认静止。')} for key,values in sorted(question_sets.items())]
    reviews=[{'group':label,'instances':[r['instance'] for r in rows],
        'would_constrain_observed_relative_motion':[r['instance'] for r in rows if r['relative_motion_would_be_constrained_if_group_chosen']],
        'instruction':'这是附件归属建议，不是刚性证明。AI结合已有用途核对整组；若要消除这些件现有相对运动，须在具体补齐方案中明确确认。'} for label,rows in sorted(review_sets.items())]
    fragments=[{k:g[k] for k in ('name','members','anchor')} for g in groups if len(g['members'])>=2]
    return {'schema_version':1,'status':'membership_questions_required' if pending or health else 'group_draft_ready_for_mechanical_review',
        'component_count':len(cs),'accounted_component_count':len(components),'accounting_complete':len(components)==len(cs),
        'proposed_component_count':len(assigned),'pending_component_count':len(pending),'seed_group_count':len(normalized),
        'components':components,'rigid_groups_draft':groups,'mechanical_questions':questions,'group_membership_reviews':reviews,
        'question_count':len(questions),'membership_review_group_count':len(reviews),'native_health_issue_feature_ids':health,
        'plan_input_fragment':{'rigid_groups':fragments} if 1<=len(fragments)<=8 else {},
        'plan_fragment_blockers':[{'reason':'ordinary_rigid_group_budget_exceeded','proposed_groups':len(fragments),'maximum_groups':8}] if len(fragments)>8 else [],
        'fragment_requires_complete_mechanical_goal_and_native_plan':True,'fragment_is_executable':False,
        'all_memberships_proposed':not pending,'mechanical_intent_inferred':False,'global_DOF_certified':False,
        'write_dispatched':False,'confirmation_token_created':False,'fixed_state_changes':[],
        'instruction':'AI集中核对组归属和待定用途，沿用已确认目标。随后使用普通connection_intent及经确认的rigid_groups形成具体原生预演；分组片段不补出组间运动目标、不声明整装配完整、不自动解除固定或执行。'}
