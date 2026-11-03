"""First-pass accounting and proposed mechanical goals, never inferred intent.

Only the ordinary planner can certify a supported gap for a proposed goal;
native preview, explicit confirmation, measured motion and restoration remain.
"""
from collections import Counter,defaultdict
from . import assembly_connections as joints,assembly_hierarchy,connection_recommendations as drafts

MAX_DRAFT_PAGES=8
MAX_AUTOMATIC_GOALS=16


def _goal(a,b,kind,axis=None):
    out={'component_a':a,'component_b':b,'kind':kind}
    if axis is not None:out['axis_hint']=axis
    return out


def for_plan(survey,proposal):
    """Classify against concrete proposed targets, not against geometry alone."""
    by={c['component_id']:c for c in survey['components']};refs=defaultdict(list)
    for i,g in enumerate(proposal.get('goals',[])):
        status='supplement_proposed' if g.get('added_action_count',0)>0 else 'existing_relation_sufficient_for_proposed_goal'
        for key in ('component_a','component_b'):refs[g[key]].append({'goal_index':i,'kind':g['kind'],'status':status,'target_role':key})
    hierarchy=assembly_hierarchy.analyze(survey['components'])
    covered,inherited=assembly_hierarchy.inherited_coverage(set(refs),hierarchy)
    for v in inherited:refs[v['component_id']].append({'status':'preserved_rigid_descendant','declared_ancestor':v['declared_ancestor']})
    rows=[]
    for cid,c in sorted(by.items()):
        goals=refs[cid]
        status='mechanical_clarification_required' if not goals else 'supplement_proposed' if any(g['status']=='supplement_proposed' for g in goals) else 'existing_relation_sufficient_for_proposed_goal'
        rows.append({'component_id':cid,'instance':c['instance'],'status':status,'proposed_targets':goals,
                     'mechanical_goal_confirmed':False,'native_verified':False})
    return {'schema_version':1,'status':'concrete_proposed_goal_assessment','observation_stage':'planning_before_confirmation','component_count':len(by),'accounted_component_count':len(rows),
            'accounting_complete':True,'all_components_have_proposed_targets':len(covered)==len(by),'components':rows,
            'category_counts':dict(Counter(v['status'] for v in rows)),'expected_added_mates':len(proposal.get('actions',[])),
            'scope':'proposed_goal_supported_constraints_only_not_complete_design_or_global_DOF',
            'mechanical_intent_inferred':False,'native_preview_completed':False,'native_motion_verified':False,
            'write_dispatched':False,'confirmation_token_created':False}


def readonly(survey,review):
    cs=survey.get('components',[])
    rows=[{'component_id':c['component_id'],'instance':c['instance'],'status':'unsupported_for_writes',
           'reason':'readonly_structure_or_reference_identity_review','mechanical_goal_confirmed':False,'native_verified':False} for c in cs]
    return {'schema_version':1,'status':'readonly_assessment','observation_stage':'readonly_snapshot','component_count':len(cs),'accounted_component_count':len(rows),
            'accounting_complete':bool(rows) and len({v['component_id'] for v in rows})==len(rows) and review.get('component_count',len(rows))==len(rows),'components':rows,
            'category_counts':{'unsupported_for_writes':len(rows)},'write_scope_blockers':review.get('write_scope_blockers',[]),
            'automatic_plan_available':False,'all_components_have_proposed_targets':False,'write_dispatched':False,
            'mechanical_intent_inferred':False,'native_motion_verified':False,'confirmation_token_created':False}


def build(survey,review,overview,draft,binding=''):
    cs=survey.get('components',[]);by={c['component_id']:c for c in cs};by_name={c['instance']:c for c in cs}
    if review.get('write_scope_allowed') is False:return readonly(survey,review)
    if review.get('mate_health_issues'):
        result=readonly(survey,{'write_scope_blockers':[{'code':'NATIVE_MATE_HEALTH_REVIEW_REQUIRED','native_issues':review['mate_health_issues']}]})
        result.update(status='native_health_blocks_automatic_plan',proposal_review_issues=[{'reason':'native_inventory_or_health_requires_review'}])
        return result
    result={'schema_version':1,'status':'mechanical_review_required','observation_stage':'first_pass_before_native_preview','component_count':len(cs),'accounted_component_count':len(cs),
            'accounting_complete':overview.get('accounting_complete') is True,'automatic_plan_available':False,
            'mechanical_intent_inferred':False,'native_motion_verified':False,'write_dispatched':False,'confirmation_token_created':False,
            'scope':'first_pass_proposed_goals_not_arbitrary_assembly_completion'}
    if not result['accounting_complete'] or len(by)!=len(cs):
        result.update(status='inventory_incomplete',accounting_complete=False,components=[]);return result
    # Keep the bounded search visible; no last-page or missing-candidate claim.
    pages=[];candidates=[];seen=set();page=draft
    for _ in range(MAX_DRAFT_PAGES):
        pages.append(page);candidates.extend(page.get('candidates',[]));cursor=page.get('next_cursor')
        if not cursor:break
        if cursor in seen:raise ValueError('first_pass_draft_cursor_cycle')
        seen.add(cursor)
        if len(pages)==MAX_DRAFT_PAGES:break
        page=drafts.draft(survey,review,cursor=cursor,binding=binding)
    search_complete=bool(pages and pages[-1].get('next_cursor') is None)
    result['candidate_search']={'pages_read':len(pages),'page_budget':MAX_DRAFT_PAGES,'remaining_cursor':pages[-1].get('next_cursor') if pages else None,
        'all_pair_ranges_read':search_complete,'complete_geometric_uniqueness_proven':False,'candidate_count':len(candidates)}
    routes={}
    for row in candidates:
        for option in row.get('options',[]):
            evidence=option.get('existing_coupling_review')
            if not evidence:continue
            key=evidence['screw']['native_feature_id'];priority=(-len(row.get('native_feature_ids',[])),row['instance_a'],row['instance_b'])
            route={'kind':'existing_coupled_joint_review_only','connection_intent':[option['connection_intent']],
                'completion_scope':'declared','whole_assembly_completion_claimed':False,'permanent_mates_added':0,
                'goal_requires_confirmation':True,'native_feature_id':key}
            if key not in routes or priority<routes[key][0]:routes[key]=(priority,route)
    result['scoped_recommendations']=[routes[k][1] for k in sorted(routes)]
    goals=[];pairs=set();issues=[]
    if not search_complete:issues.append({'reason':'automatic_candidate_budget_reached','remaining_cursor':result['candidate_search']['remaining_cursor']})
    def add(g):
        if g['component_a']==g['component_b']:return
        key=frozenset((g['component_a'],g['component_b']))
        if key in pairs:return
        if all(by_name[n].get('fixed_component') for n in key):return
        pairs.add(key);goals.append(g)
    # Existing internal rigid evidence is kept; fixed flags alone never form groups.
    for group in overview.get('observed_rigid_groups',[]):
        members=group['top_level_target_instances'];anchor=group['anchor_instance']
        if anchor not in members:continue
        for name in members:
            if name!=anchor:add(_goal(name,anchor,'rigid'))
    for row in overview.get('observed_joint_recommendations',[]):
        if not all(by[c].get('parent_component_id') is None for c in (row['component_a'],row['component_b'])):continue
        if row['suggested_kind'] in {'revolute','prismatic'} and row.get('supported_direct_rank',0)<5:continue
        add(_goal(row['instance_a'],row['instance_b'],row['suggested_kind'],row.get('axis_global')))
    # Only a unique preferred guide proposal can augment the observed skeleton.
    # It is still a proposed PURPOSE requiring confirmation, not proof of intent.
    covered={g[k] for g in goals for k in ('component_a','component_b')}
    possible=defaultdict(list)
    for row in candidates:
        i=row.get('preferred_option_index')
        if row.get('blocker') or type(i) is not int or not 0<=i<len(row.get('options',[])):continue
        option=row['options'][i]
        missing=option.get('supported_whole_inventory_missing_coordinates_if_goal_chosen')
        if row['instance_a'] not in covered or type(missing) is int and missing>0:possible[row['instance_a']].append(option)
    if search_complete:
        for name,options in sorted(possible.items()):
            if len(options)==1:add(options[0]['connection_intent'])
    pending_pairs=[]
    for row in candidates:
        options=row.get('options') or [];counts=[o.get('supported_whole_inventory_missing_coordinates_if_goal_chosen') for o in options]
        pair=frozenset((row['instance_a'],row['instance_b']))
        if pair in pairs or not counts or not all(type(n) is int and n>0 for n in counts):continue
        pending_pairs.append({'candidate_id':row['candidate_id'],'instance_a':row['instance_a'],'instance_b':row['instance_b'],
            'reason':'unresolved_connection_purpose_even_when_both_components_have_other_targets',
            'native_feature_ids':row.get('native_feature_ids',[]),'options':options,'missing_connection_proven':False})
    result['unresolved_connection_candidates']=pending_pairs
    # Validate the entire suggested combination through the SAME ordinary planner.
    proposal=None
    if goals:
        resolved=[{**g,'component_a':by_name[g['component_a']]['component_id'],'component_b':by_name[g['component_b']]['component_id']} for g in goals]
        if len(resolved)<=MAX_AUTOMATIC_GOALS:
            try:
                proposal=joints.plan(survey,resolved,whole_assembly=len(resolved)>8)
                if proposal.get('status')!='plan_ready':issues.append({'reason':proposal['status']});proposal=None
            except (ValueError,TypeError) as error:issues.append({'reason':str(error)})
        else:issues.append({'reason':'automatic_goal_budget_exceeded','proposed_count':len(goals),'automatic_limit':MAX_AUTOMATIC_GOALS,'ordinary_whole_assembly_limit':128})
    if proposal:
        assessment=for_plan(survey,proposal);result.update({k:v for k,v in assessment.items() if k not in {'schema_version','scope','status'}})
    else:
        technical=any(v['reason'] in {'automatic_goal_budget_exceeded','unsupported_native_lock_trial','unsupported_references','native_inventory_or_health_requires_review','native_fully_constrained_mobile_goal_requires_review'} for v in issues)
        category='unsupported_for_automatic_plan' if technical else 'mechanical_clarification_required'
        result['components']=[{'component_id':c['component_id'],'instance':c['instance'],'status':category,
            'reason':(next((r['reason'] for r in overview.get('components',[]) if r['component_id']==c['component_id']),'unsupported_or_ambiguous_goal')),
            'mechanical_goal_confirmed':False,'native_verified':False} for c in cs]
        result['category_counts']={category:len(cs)};result['all_components_have_proposed_targets']=False
    questions=defaultdict(list)
    unresolved_names={v[k] for v in pending_pairs for k in ('instance_a','instance_b')}
    if pending_pairs:
        for row in result['components']:
            if row['instance'] in unresolved_names and row['status']!='unsupported_for_automatic_plan':
                row.update(status='mechanical_clarification_required',reason='unresolved_connection_purpose')
        result['category_counts']=dict(Counter(v['status'] for v in result['components']))
    for row in result['components']:
        if row['status']=='mechanical_clarification_required' and row.get('reason')!='unresolved_connection_purpose':questions[row.get('reason','component_without_proposed_target')].append(row['instance'])
    result['mechanical_question_groups']=[{'reason':reason,'instances':names,'question':'请集中说明这些组件应随哪一组运动、相对谁静止或保留哪种相对运动。AI复用已说明用途，不要求实体ID。'} for reason,names in sorted(questions.items())]
    if pending_pairs:result['mechanical_question_groups'].append({'reason':'unresolved_connection_purpose','instances':sorted(unresolved_names),
        'pairs':[{'a':v['instance_a'],'b':v['instance_b'],'options':sorted({o['kind'] for o in v['options']})} for v in pending_pairs],
        'question':'组件已有其他连接不代表这些连接已经完善。AI复用已明确用途，只集中澄清这些零件对需要保留的相对运动，不默认改成刚性。'})
    result['proposed_connection_intent']=goals;result['proposal_review_issues']=issues
    if proposal and result['all_components_have_proposed_targets'] and not questions and not pending_pairs and search_complete:
        coupled=any(g.get('coupled_verification_only') for g in proposal['goals'])
        if not coupled:
            result.update(status='automatic_native_preview_available',automatic_plan_available=True,
                suggested_plan_arguments={'connection_intent':goals,'completion_scope':'whole_assembly'},
                confirmation_scope='confirm_proposed_mechanical_goals_and_precise_supplements_before_execute')
        else:result['proposal_review_issues'].append({'reason':'existing_coupling_requires_declared_goal_scope'})
    result['instruction']='AI先给出全部组件的分类及建议连接。候选机械用途需要在具体方案中确认；已有关系足够可以新增0项。未覆盖、未知或超范围不能算完成。只在自动方案可用时auto_plan=true读取原生预演，否则集中澄清后使用普通连接目标。'
    return result
