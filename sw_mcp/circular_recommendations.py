"""Read-only geometric ranking. Scores are NOT design-intent or DOF probabilities."""
import math,time

def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def norm(a):return math.sqrt(dot(a,a))
def unit(a):
    if len(a)!=3 or any(not math.isfinite(x) for x in a) or norm(a)<1e-12:raise ValueError('invalid axis')
    return [x/norm(a) for x in a]
def axis_gap(a,b):
    u=unit(a['axis_global']);d=sub(b['reference_point_global_m'],a['reference_point_global_m'])
    return norm([d[i]-dot(d,u)*u[i] for i in range(3)])
def same_axis(a,b):return abs(dot(unit(a['axis_global']),unit(b['axis_global'])))>1-1e-10 and axis_gap(a,b)<1e-7

def recommend(rows,mates,complete,model_id,limit=5,focus='',context_complete=True):
    excluded_arcs=sum(r.get("edge_sweep_rad",0)<math.pi-1e-6 and r.get("full_circle") is not True for r in rows)
    rows=[r for r in rows if r.get("full_circle") is True or r.get("edge_sweep_rad",0)>=math.pi-1e-6]
    groups=[]
    for row in sorted(rows,key=lambda r:r['entity_id']):
        # Different references remain distinct. Grouping only reduces duplicate suggestions.
        group=next((g for g in groups if g[0]['component_id']==row['component_id'] and same_axis(g[0],row)),None)
        if group is None:groups.append([row])
        else:group.append(row)
    candidates=[];excluded=[];evaluated=0;pair_limit=20000;ranking_complete=True
    for i,ga in enumerate(groups):
        for gb in groups[i+1:]:
            a,b=ga[0],gb[0]
            if a['component_id']==b['component_id'] or a['fixed_component'] and b['fixed_component']:continue
            if focus and not any(focus.casefold() in r['instance'].casefold() for r in (a,b)):continue
            if evaluated>=pair_limit:ranking_complete=False;break
            evaluated+=1
            angle=math.degrees(math.acos(min(1,abs(dot(unit(a['axis_global']),unit(b['axis_global']))))))
            gap=axis_gap(a,b)*1000
            if angle>5 or gap>2:continue
            pair={a['component_id'],b['component_id']};related=[];already=[]
            for mate in mates:
                refs=mate.get('entities',[])
                if {r.get('component_id') for r in refs}!=pair:continue
                related.append(mate.get('name'))
                if mate.get('type_name')!='swMateCONCENTRIC':continue
                if len(refs)==2 and all(r.get('geometry') for r in refs):
                    matched=all(any(r['component_id']==c['component_id'] and same_axis(r['geometry'],c) for r in refs) for c in (a,b))
                    if matched:already.append(mate.get('name'))
            if already:
                excluded.append({'instances':[a['instance'],b['instance']],'reason':'observed_existing_concentric_on_same_axis_review_only','mates':already});continue
            # Choose the actual edge pair with the closest axial centers; never substitute faces.
            a,b=min(((x,y) for x in ga for y in gb),key=lambda xy:(norm(sub(xy[0]['reference_point_global_m'],xy[1]['reference_point_global_m'])),xy[0]['entity_id'],xy[1]['entity_id']))
            alignment='aligned' if dot(unit(a['axis_global']),unit(b['axis_global']))>=0 else 'anti_aligned'
            radius_difference=abs(a['circle_radius_m']-b['circle_radius_m'])/max(a['circle_radius_m'],b['circle_radius_m'])
            score=gap+angle*.2+radius_difference*.1+min(norm(sub(a['reference_point_global_m'],b['reference_point_global_m']))*1000,1000)*.001
            candidates.append({'instances':[a['instance'],b['instance']],'references':[a,b],
                'geometry':{'axis_angle_deg':angle,'axis_gap_mm':gap,'radii_mm':[a['circle_radius_m']*1000,b['circle_radius_m']*1000]},
                'radius_similarity_used_for_ranking_only':True,'equivalent_axis_edge_counts':[len(ga),len(gb)],'existing_pair_mates':related,
                'warnings':(['EXISTING_PAIR_CONSTRAINTS_REVIEW_REQUIRED'] if related else [])+([] if context_complete else ['MATE_CONTEXT_INCOMPLETE']),
                'reason':'两零件圆边轴线接近；按轴线偏差和边线中心距离排序。半径相近仅用于推荐排序，不据此判断公差或设计意图。',
                'rank_cost':round(score,9),'preview_arguments':{'model_id':model_id,'entity_a':a['entity_id'],'entity_b':b['entity_id'],
                    'mate_type':'concentric','alignment':alignment,'lock_rotation':False},'motion_preserved':None})
        if not ranking_complete:break
    candidates.sort(key=lambda r:(r['rank_cost'],r['instances'],r['preview_arguments']['entity_a']))
    complete=complete and ranking_complete
    ambiguous=len(candidates)>1 and candidates[1]['rank_cost']-candidates[0]['rank_cost']<.1
    status=('no_nearby_candidate' if complete and context_complete else 'incomplete_search') if not candidates else 'selection_required' if ambiguous or not complete or not context_complete else 'ranked_proposal_ready'
    return {'model_id':model_id,'recommendation_status':status,'geometry_complete':complete,'mate_context_complete':context_complete,
        'candidate_pair_count':len(candidates),'ranking_complete':ranking_complete,'pair_evaluation_budget':pair_limit,'evaluated_pairs':evaluated,
        'recommendations':candidates[:limit],'truncated':len(candidates)>limit,'excluded_existing_count':len(excluded),'excluded_existing':excluded[:5],
        'requires_geometric_selection':bool(candidates) and (ambiguous or not complete or not context_complete),
        'selection_question':'确认推荐零件对；若用途不同，只需说出运动件或支座名称，无需抄entity_id。' if candidates else '查询或排序未完整，尚不能判定有无可用组合；可说明目标零件名称缩小范围。' if not complete or not context_complete else '没有接近的圆边组合，请说明目标零件对；不自动移动或放宽位置预算。',
        'recommendation_geometry_scope':'native_circular_edges_at_least_half_circle','excluded_arc_or_unknown_count':excluded_arcs,'requires_write_confirmation':True,'automatic_mate_application':False,'automatic_rotation_lock':False,
        'ranking_policy':{'max_axis_gap_mm':2,'max_axis_angle_deg':5,'selection_tie_cost':.1,'scope':'near_current_pose_not_general_assembly_intent'},
        'claim':'geometric_recommendation_not_missing_constraint_proof_or_solver_prediction'}

def state_change_diagnostics(initial,observed,phase):
    # Already captured observations only. No extra COM call, retries or guard relaxation.
    before=initial.get('state_observation');after=observed.get('state_observation');differences=[];count=0;categories=[]
    labels={'revision':'model_revision','configuration':'configuration','files':'saved_file_bytes','documents':'loaded_document_state','components':'component_identity_and_fixed_state','poses':'component_pose','studies':'motion_study_state'}
    def walk(a,b,path):
        nonlocal count
        if type(a) is not type(b):
            count+=1
            if len(differences)<12:differences.append({'path':path,'before':a,'after':b})
        elif isinstance(a,dict):
            for k in sorted(set(a)|set(b)):
                if k not in a or k not in b:
                    count+=1
                    if len(differences)<12:differences.append({'path':path+'/'+str(k),'before_present':k in a,'after_present':k in b})
                else:walk(a[k],b[k],path+'/'+str(k))
        elif isinstance(a,list):
            if len(a)!=len(b):
                count+=1
                if len(differences)<12:differences.append({'path':path+'/length','before':len(a),'after':len(b)})
            for i,(x,y) in enumerate(zip(a,b)):walk(x,y,path+'/'+str(i))
        elif a!=b:
            count+=1
            if len(differences)<12:differences.append({'path':path,'before':a,'after':b})
    if isinstance(before,dict) and isinstance(after,dict):
        for key in sorted(set(before)|set(after)):
            if key not in before or key not in after or before[key]!=after[key]:categories.append(labels.get(key,key))
        walk(before,after,'')
    return {'schema':'circular-state-change-1.0','phase':phase,'initial_signature':initial.get('signature'),
        'observed_signature':observed.get('signature'),'initial_revision':initial.get('model_revision'),'observed_revision':observed.get('model_revision'),
        'observation_available':isinstance(before,dict) and isinstance(after,dict),'changed_categories':categories,
        'differences':differences,'difference_count':count,'differences_truncated':count>len(differences),
        'state_evidence':{'before':initial.get('state_evidence'),'after':observed.get('state_evidence')},'evidence_read_errors':[x['evidence_read_error'] for x in (initial,observed) if x.get('evidence_read_error')],'root_cause_proven':False,'automatic_retry':False,'guard_relaxed':False,
        'next_action':{'action':'end_owned_session_and_collect','message':'停止使用本轮推荐；结束本次专用CAD会话并交回自动诊断，无需重新求解。'}}

def captured_observation(state,bridge):
    if isinstance(state.get('state_observation'),dict):return state
    value=dict(state)
    if bridge is None or not state.get('state_evidence'):return value
    try:
        from pathlib import Path
        import hashlib,json,re
        signature=state['signature'];evidence=state['state_evidence']
        if not re.fullmatch('query_[a-f0-9]{24}',signature):raise ValueError('invalid_state_id')
        expected='runs/circular-query-states/'+signature+'.json'
        if evidence['path']!=expected:raise ValueError('invalid_state_evidence_path')
        root=Path(bridge.root).resolve();path=root/expected
        for part in [path,*list(path.parents)[:3]]:
            if part.is_symlink() or (hasattr(part,'is_junction') and part.is_junction()):raise ValueError('linked_state_evidence')
        if not path.resolve().is_relative_to(root) or path.stat().st_size>4*1024*1024:raise ValueError('state_evidence_boundary_or_size')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=evidence['sha256'].replace('-','').lower():raise ValueError('state_evidence_hash_mismatch')
        value['state_observation']=json.loads(data.decode('utf-8-sig'))
    except Exception as error:value['evidence_read_error']=str(error)
    return value

def require_same_state(initial,observed,phase,bridge=None):
    from .bridge import CadError
    if initial.get('signature')!=observed.get('signature') or initial.get('model_revision')!=observed.get('model_revision'):
        raise CadError('MATE_RECOMMENDATION_STALE','推荐读取期间状态改变，已停止后续配合写入；变更项见自动诊断。','not_required',state_change_diagnostics(captured_observation(initial,bridge),captured_observation(observed,bridge),phase))

def discover(bridge,model_id,focus='',limit=3,budget_seconds=60,maximum_queries=64):
    from .bridge import CadError
    started=time.monotonic();initial=bridge.request('_circular_reference_state',model_id=model_id)
    inspection=bridge.request('inspect_model',model_id=model_id,detail_level='full')
    require_same_state(initial,bridge.request('_circular_reference_state',model_id=model_id),'inspect_existing_mates',bridge)
    components=[c for c in inspection.get('components',[]) if not c.get('suppressed')]
    if components and all(c.get('fixed_component') is True for c in components):
        value=recommend([],inspection.get('mates',[]),False,model_id,limit,focus,False)
        value.update(recommendation_status='all_components_fixed',selection_question='当前活动零件全部固定。先明确哪个零件需要运动；本助手不自动解除固定，不据此判断圆边缺失。',
            setup_required=True,fixed_component_count=len(components),geometry_scan_attempted=False,query_count=0,
            geometry_complete=False,reference_state_signature=initial['signature'],read_only=True,automatic_native_calculate=False,
            setup_suggestions=[{'component_id':c['component_id'],'instance':c['instance']} for c in components if any(hint in c['instance'].casefold() for hint in ('轴','shaft','滑块','slider','rotor'))][:5])
        return value
    def priority(c):
        return (bool(c.get('fixed_component')),not (focus and focus.casefold() in c['instance'].casefold()),not any(word in c['instance'].casefold() for word in ('泵体','机体','housing','support','支架','轴承','导轨')),c['instance'])
    rows={};queries=[];pending=[(c['component_id'],0) for c in sorted(components,key=priority)];seen=set();complete=True
    while pending and len(queries)<maximum_queries and time.monotonic()-started<budget_seconds:
        component,offset=pending.pop(0)
        if (component,offset) in seen:complete=False;break
        seen.add((component,offset));cursor=''
        while True:
            page=bridge.request('list_mate_references',model_id=model_id,component_id=component,kind='circular_edge',limit=50,
                cursor=cursor,detail_level='compact',face_offset=0,mate_context_budget_s=10,geometry_scan_budget_s=5,edge_offset=offset)
            require_same_state(initial,{'signature':page['reference_state_signature'],'model_revision':page.get('model_revision',initial.get('model_revision')),'state_evidence':page.get('reference_state_evidence')},'circular_edge_scan',bridge)
            queries.append({'component_id':component,'edge_offset':offset,'cursor_page':bool(cursor),'geometry_complete':page['geometry_complete']})
            rows.update({r['entity_id']:r for r in page['entities']})
            if page.get('skipped_component_count'):complete=False
            if not cursor:
                scan=page['geometry_scan']
                if scan.get('next_queries_truncated'):
                    # Preserve siblings; restart remaining components individually, without claiming absent geometry.
                    for c in inspection['components']:
                        task=(c['component_id'],0)
                        if task not in seen and task not in pending:pending.append(task)
                else:
                    for task in scan['next_queries']:
                        task=(task['component_id'],task['edge_offset'])
                        if task not in pending:pending.append(task)
            cursor=page.get('next_cursor','')
            if not cursor:break
            if len(queries)>=maximum_queries or time.monotonic()-started>=budget_seconds:complete=False;break
    if pending:complete=False
    final=bridge.request('_circular_reference_state',model_id=model_id)
    require_same_state(initial,final,'finish_recommendation',bridge)
    mates=inspection.get('mates',[])
    context_complete=all(all(e.get('component_id') and e.get('geometry') for e in m.get('entities',[])) and len(m.get('entities',[]))==2 for m in mates)
    value=recommend(list(rows.values()),mates,complete,model_id,limit,focus,context_complete)
    # Return compact usable references; full query evidence remains in the native request journal.
    for item in value['recommendations']:
        item['references']=[{k:r[k] for k in ('entity_id','component_id','instance','kind')} for r in item['references']]
    value.update(reference_state_signature=final['signature'],queries=queries[:5],query_count=len(queries),pending_query_count=len(pending),
        elapsed_s=round(time.monotonic()-started,3),read_budget_s=budget_seconds,maximum_queries=maximum_queries,read_only=True,automatic_native_calculate=False)
    return value

