"""Restricted 12rpm/1s rotation comparison. No arbitrary intent or edge->face substitution."""
from pathlib import Path
import csv,math,shutil,uuid
from . import core,concentric_card

def unit(v):
    if not isinstance(v,(list,tuple)) or len(v)!=3 or any(type(x) not in (int,float) or not math.isfinite(x) for x in v):raise core.StopBatch('INVALID_MOTION_AXIS')
    n=math.sqrt(sum(x*x for x in v))
    if n<1e-12:raise core.StopBatch('INVALID_MOTION_AXIS')
    return [x/n for x in v]

def bind_drive(plan,components,faces):
    refs=[plan['reference_a'],plan['reference_b']];fixed={c['component_id']:c['fixed_component'] for c in components}
    if any(r['component_id'] not in fixed for r in refs):raise core.StopBatch('MOTION_COMPONENT_NOT_OBSERVED')
    moving=[r for r in refs if fixed[r['component_id']] is False]
    if len(moving)!=1 or not any(fixed[r['component_id']] is True for r in refs):raise core.StopBatch('MOTION_REQUIRES_ONE_FLOATING_ONE_FIXED','本预览仅验证一个运动件相对一个固定件的旋转。')
    edge=moving[0];axis=unit(edge['axis_global']);point=edge['reference_point_global_m'];matches=[]
    for face in faces:
        if face['component_id']!=edge['component_id'] or face['kind']!='cylindrical_axis':continue
        a=unit(face['axis_global']);dot=sum(x*y for x,y in zip(axis,a))
        delta=[x-y for x,y in zip(face['reference_point_global_m'],point)];along=sum(x*y for x,y in zip(delta,axis))
        gap=math.sqrt(sum((x-along*y)**2 for x,y in zip(delta,axis)))
        if abs(dot)>=1-1e-10 and gap<=1e-7:matches.append((dot,face))
    if not matches:raise core.StopBatch('NO_CYLINDRICAL_DRIVE_ON_SELECTED_AXIS','找不到所选圆边同一轴线的原生圆柱面；未创建马达。')
    # Collinear cylinder patches describe the SAME directed axis; choose largest face deterministically.
    # Never swap the mate's native edge; the face is used ONLY as a motor/measurement reference.
    matches.sort(key=lambda x:(x[0]<0,-x[1].get('area_m2',0),x[1]['entity_id']))
    drive=matches[0][1];reference=next(r for r in refs if fixed[r['component_id']] is True)
    return {'drive':drive,'reference':reference,'collinear_native_faces':len(matches),'axis_global':drive['axis_global'],
        'axis_binding':'native_cylinder_face_same_moving_component_and_selected_edge_axis','mate_edge_substitution':False,
        'speed_rpm':12,'duration_s':1,'output_fps':30,'minimum_travel_deg':71.9,'expected_travel_deg':72,
        'scope':'selected_component_rotation_relative_fixed_peer_only_not_whole_mechanism_or_DOF'}

def audit_poses(path,moving,reference,axis,component_count):
    """Independent CSV audit using trace angles, cross-basis signed increments and row-basis SW transforms."""
    data={}
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            frame=int(row['frame']);cid=row['component_id'];key=(frame,cid)
            if key in data:raise core.StopBatch('DUPLICATE_POSE_SAMPLE')
            values=[float(row[k]) for k in ['time_s','x_m','y_m','z_m',*['r'+str(i)+str(j) for i in range(3) for j in range(3)]]]
            if any(not math.isfinite(x) for x in values):raise core.StopBatch('NONFINITE_POSE_SAMPLE')
            data[key]=row
    frames=sorted({f for f,c in data});ids={c for f,c in data}
    if frames!=list(range(31)) or len(ids)!=component_count or len(data)!=31*component_count or any((f,c) not in data for f in frames for c in ids):raise core.StopBatch('POSE_GRID_INCOMPLETE')
    if moving not in ids or reference not in ids:raise core.StopBatch('POSE_COMPONENT_MISSING')
    def matrix(row):return [[float(row['r'+str(i)+str(j)]) for j in range(3)] for i in range(3)]
    def angle(a,b):return math.degrees(math.acos(max(-1,min(1,(sum(a[i][j]*b[i][j] for i in range(3) for j in range(3))-1)/2))))
    def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    axis=unit(axis);travel=signed=off_axis=0;intervals=[];max_other_translation=max_other_rotation=max_moving_translation=0
    first={c:data[0,c] for c in ids}
    for frame in frames:
        for cid in ids:
            row=data[frame,cid]
            if abs(float(row['time_s'])-frame/30)>1e-7:raise core.StopBatch('POSE_TIME_GRID_CHANGED')
            a,b=first[cid],row;distance=math.sqrt(sum((float(a[k])-float(b[k]))**2 for k in ('x_m','y_m','z_m')))
            if cid==moving:max_moving_translation=max(max_moving_translation,distance)
            else:max_other_translation=max(max_other_translation,distance);max_other_rotation=max(max_other_rotation,angle(matrix(a),matrix(b)))
        if frame:
            a,b=matrix(data[frame-1,moving]),matrix(data[frame,moving]);delta=angle(a,b)
            vector=[sum(cross(a[i],b[i])[j] for i in range(3))/2 for j in range(3)]
            projection=sum(x*y for x,y in zip(vector,axis));increment=math.copysign(delta,projection);intervals.append(increment);signed+=increment;travel+=delta
            norm=math.sqrt(sum(x*x for x in vector));alignment=projection/norm if norm>1e-12 else 0
            off_axis+=delta*math.sqrt(max(0,1-alignment*alignment))
    maximum_interval_error=max(abs(abs(x)-2.4) for x in intervals)
    passed=abs(travel-72)<=.1 and abs(abs(signed)-72)<=.1 and maximum_interval_error<=.01 and off_axis<=.1 and max_other_translation<=1e-7 and max_other_rotation<=math.degrees(1e-6)
    return {'passed':passed,'rows':len(data),'frames':31,'components':len(ids),'travel_deg':travel,'signed_travel_about_recorded_axis_deg':signed,
        'maximum_other_component_translation_m':max_other_translation,'maximum_other_component_rotation_deg':max_other_rotation,
        'maximum_moving_origin_translation_m':max_moving_translation,'moving_origin_translation_is_not_rotation_failure':True,'off_axis_travel_deg':off_axis,'expected_travel_deg':72,'travel_tolerance_deg':.1,
        'signed_intervals_deg':intervals,'maximum_interval_magnitude_error_deg':maximum_interval_error,'interval_magnitude_tolerance_deg':.01,
        'direction_scope':'signed_observation_about_native_motor_axis_not_designer_intent','all_component_trajectories_checked':True}

def snapshot_csv(session,run_id,label,binding):
    if len(run_id)!=32 or any(c not in '0123456789abcdef' for c in run_id):raise core.StopBatch('INVALID_RUN_ID')
    source=core.no_links(session.runtime/'runs'/run_id/'component-poses.csv');target=session.folder/('运动-'+label+'.csv')
    shutil.copyfile(source,target)
    return {'path':str(target),'sha256':core.digest(target),'run_id':run_id,
        'audit':audit_poses(target,binding['drive']['component_id'],binding['reference']['component_id'],binding['axis_global'],binding['component_count'])}

def component_geometry(session,component_id,kind='cylindrical_axis'):
    rows={};pending=[0];seen=set();queries=0
    while pending:
        offset=pending.pop(0)
        if offset in seen:raise core.StopBatch('MOTION_GEOMETRY_CONTINUATION_LOOP')
        seen.add(offset);cursor=''
        while True:
            queries+=1
            if queries>32:raise core.StopBatch('MOTION_DRIVE_GEOMETRY_BUDGET','圆柱面读取超过32页，未创建马达。')
            args={'model_id':session.model,'kind':kind,'component_id':component_id,'limit':50,'cursor':cursor,'face_offset':offset if kind!='circular_edge' else 0}
            if kind=='circular_edge':args['edge_offset']=offset
            page=session.call('list_mate_references',**args)
            for row in page['entities']:rows[row['entity_id']]=row
            scan=page.get('geometry_scan',{})
            if scan.get('next_queries_truncated') or page.get('skipped_component_count',0):raise core.StopBatch('MOTION_DRIVE_GEOMETRY_INCOMPLETE')
            # A component-scoped query intentionally does NOT claim model-wide completeness.
            # Drain its frozen pages and ONLY this retained component queue, never sibling queues.
            if not cursor:
                next_queries=scan.get('next_queries',[])
                if not page.get('scope_geometry_complete',page.get('geometry_complete')) and not next_queries:raise core.StopBatch('MOTION_DRIVE_GEOMETRY_INCOMPLETE')
                for task in next_queries:
                    if task['component_id']!=component_id:raise core.StopBatch('MOTION_GEOMETRY_SCOPE_CHANGED')
                    pending.append(task['edge_offset' if kind=='circular_edge' else 'face_offset'])
            cursor=page['next_cursor']
            if not cursor:break
    return list(rows.values())

def cylinder_faces(session,component_id):return component_geometry(session,component_id)

def refresh_pair(session,binding,selected):
    for attempt in range(2):
        state=session.call('_circular_reference_state',model_id=session.model);rows=[]
        try:
            for cid in binding['pair_components']:rows.extend(component_geometry(session,cid,'circular_edge'))
            if state!=session.call('_circular_reference_state',model_id=session.model):raise core.StopBatch('MATE_RECOMMENDATION_STALE')
            break
        except Exception as error:
            if attempt or session.unknown or getattr(error,'code',None) not in {'MATE_CURSOR_STALE','MATE_RECOMMENDATION_STALE'}:raise
            core.write(session.folder/'配合后只读续查重启.json',{'code':error.code,'diagnostics':getattr(error,'diagnostics',None),
                'maximum_additional_read_rounds':1,'baseline_run_id':binding['baseline']['run_id'],
                'selected_physical_edges':binding['pair_entities'],'native_write_or_solve_retried':False,
                'old_page_rows_discarded':True,'native_baseline_validation_still_required':True})
    exact={r['entity_id']:r for r in rows}
    if any(e not in exact for e in binding['pair_entities']):raise core.StopBatch('MOTION_PAIR_REDISCOVERY_REQUIRED','原圆边未重新解析；保留基线，不自动换边。')
    # Keep the selected physical edges; refresh only their native geometry, never re-rank/rebind.
    item={**selected,'references':[{k:exact[e][k] for k in ('entity_id','component_id','instance','kind')} for e in binding['pair_entities']]}
    session.recommendation={**session.recommendation,'recommendations':[item],'candidate_pair_count':1,'truncated':False,
        'reference_state_signature':state['signature'],'geometry_complete':False,'scope_geometry_complete':True,
        'ranking_scope':'previously_selected_pair_only_revalidated_after_baseline_not_whole_model_ranking',
        'recommendation_status':'selection_required','requires_geometric_selection':True,
        'selection_question':'已重新核对原来选择的圆边对；仅认证该零件对，不重扫整机。'}
    core.write(session.folder/'推荐.json',session.recommendation)

def verdict(binding):
    verification=binding.get('verification',{});comparison=binding.get('trajectory_comparison',{})
    rotation=verification.get('assertion')=='pass' and verification.get('before_after_comparison')=='travel_retained' and all(binding.get(k,{}).get('audit',{}).get('passed') is True for k in ('baseline','after'))
    complete=rotation and comparison.get('passed') is True and verification.get('source_files_unchanged') is True and verification.get('restoration_status')=='restored'
    return {'requested_rotation_retained':rotation,'full_trajectory_equivalent':comparison.get('passed') is True,'passed':complete,
        'status':'pass' if complete else 'requested_rotation_retained_trajectory_changed' if rotation else 'motion_not_verified',
        'maximum_trajectory_translation_difference_mm':comparison.get('maximum_translation_m',0)*1000 if comparison else None,
        'maximum_trajectory_rotation_difference_deg':math.degrees(comparison.get('maximum_rotation_rad',0)) if comparison else None,
        'claim':'selected_rotation_and_sampled_all_component_comparison_not_whole_pump_transmission_or_DOF',
        'next_action':{'action':'collect_existing_evidence_for_AI_review','repeat_solve':False,'reason':'compare_unconstrained_baseline_repeatability_and_constraint_effect' if rotation and not complete else 'read_saved_diagnostics' if not complete else 'restore_or_preserve_copy_then_end_session'},
        'tolerances_automatically_relaxed':False,'root_cause':'not_proven_by_difference_alone'}

def baseline(session,index,confirmed=False,scope_confirmed=False):
    if type(scope_confirmed) is not bool:raise core.StopBatch("INVALID_SCOPE_CONFIRMATION")
    if confirmed is not True:raise core.StopBatch('MOTION_TEST_CONFIRMATION_REQUIRED','请确认在副本创建12rpm、1秒、30fps测试马达并求解。')
    if session.unknown or session.committed or getattr(session,'motion',None):raise core.StopBatch('MOTION_BASELINE_NOT_READY','不重复创建测试马达；已有结果请读取诊断。')
    plan=session.preview(index);selected=session.recommendation['recommendations'][index];session.plan=None
    components=session.call('inspect_model',model_id=session.model,detail_level='components')['components']
    moving=[r for r in [plan['reference_a'],plan['reference_b']] if not r['fixed_component']]
    if len(moving)!=1:raise core.StopBatch('MOTION_REQUIRES_ONE_FLOATING_ONE_FIXED')
    faces=cylinder_faces(session,moving[0]['component_id'])
    binding=bind_drive(plan,components,faces);binding['component_count']=len(components)
    binding['pair_components']=[r['component_id'] for r in [plan['reference_a'],plan['reference_b']]]
    binding['pair_entities']=[plan['reference_a']['entity_id'],plan['reference_b']['entity_id']]
    binding['study']='MateRotation_'+uuid.uuid4().hex[:6];binding['stage']='creating'
    try:
        binding['mechanical_card']=concentric_card.create(plan,components,session.recommendation['reference_state_signature'],scope_confirmed,False)
    except ValueError as error:
        if scope_confirmed:raise core.StopBatch('CONCENTRIC_SCOPE_CARD_NOT_ELIGIBLE',str(error))
        binding['mechanical_card']=None;binding['scope_card_unavailable_reason']=str(error)
    if binding['mechanical_card']:
        core.write(session.folder/'同轴约束测试卡.json',binding['mechanical_card'])
        core.write(session.folder/'测试卡锁定顺序.json',{'card_id':binding['mechanical_card']['card_id'],'before_native_create_motion_study':True,
            'next_native_call_serial':session.serial+1,'study':binding['study'],'model_id':session.model,'card_sha256':core.digest(session.folder/'同轴约束测试卡.json')})

    # Latch before any write: a failed or unknown creation is never automatically replayed.
    session.motion=binding;core.write(session.folder/'运动对照.json',binding)
    session.state('motion_baseline','正在副本创建受限旋转测试并采集配合前轨迹…')
    session.call('create_motion_study',model_id=session.model,study=binding['study'],component_id=binding['drive']['component_id'],entity_id=binding['drive']['entity_id'],motor_type='rotary',speed=12,reverse_direction=False,duration_s=1,output_fps=30)
    run=session.call('run_user_study',model_id=session.model,study=binding['study'],duration_s=1,output_fps=30,run_id=uuid.uuid4().hex)
    binding['baseline']=snapshot_csv(session,run['run_id'],'配合前',binding);binding['baseline_summary']=run
    if not binding['baseline']['audit']['passed']:binding['stage']='baseline_failed';core.write(session.folder/'运动对照.json',binding);raise core.StopBatch('BASELINE_TRAJECTORY_NOT_ACCEPTED','配合前运动未满足测试卡，未创建配合。')
    binding['stage']='baseline_ready';core.write(session.folder/'运动对照.json',binding)
    # Refresh this selected pair, not another expensive whole-model scan; old plan is discarded.
    refresh_pair(session,binding,selected)
    session.preview(0);session.state('previewed','配合前约72°旋转已核对。请核对方向及配合方案，再确认创建。',plan=session.plan,motion=binding)
    return binding

def verify(session,confirmed=False):
    if confirmed is not True:raise core.StopBatch('MOTION_TEST_CONFIRMATION_REQUIRED')
    binding=getattr(session,'motion',None)
    if session.unknown or not session.committed or not binding or binding.get('stage')!='baseline_ready' or not getattr(session,'applied_plan',None):raise core.StopBatch('MOTION_VERIFY_NOT_READY')
    binding['stage']='verifying';core.write(session.folder/'运动对照.json',binding)
    session.state('motion_verifying','正在求解配合后轨迹并核对全部组件…')
    result=session.call('verify_motion_preservation',model_id=session.model,study=binding['study'],component_id=binding['drive']['component_id'],entity_id=binding['drive']['entity_id'],expected_motion='rotary',minimum_travel=71.9,duration_s=1,output_fps=30,run_id=uuid.uuid4().hex,plan_id=session.applied_plan,reference_component_id=binding['reference']['component_id'])
    binding['verification']=result
    if result.get('assertion')=='pass':
        binding['after']=snapshot_csv(session,result['run_id'],'配合后',binding)
        binding['trajectory_comparison']=core.compare_pose_files(binding['baseline']['path'],binding['after']['path'])
    binding['verdict']=verdict(binding);binding['passed']=binding['verdict']['passed']
    card=binding.get('mechanical_card')
    if card and binding.get('after'):
        binding['scope_verification']=concentric_card.evaluate(card,binding['baseline']['path'],binding['after']['path'])
        binding['scope_verification']['native_result_and_restore_verified']=result.get('assertion')=='pass' and result.get('source_files_unchanged') is True and result.get('restoration_status')=='restored'
        if not binding['scope_verification']['native_result_and_restore_verified']:binding['scope_verification']['scope_acceptance_passed']=False
        binding['scope_verification']['native_run_binding']={'model_id':session.model,'baseline_run_id':binding['baseline']['run_id'],'after_run_id':binding['after']['run_id'],
            'baseline_csv_sha256':binding['baseline']['sha256'],'after_csv_sha256':binding['after']['sha256'],'plan_id':session.applied_plan,'scope':'this_current_session_not_historical_rebinding'}
        core.write(session.folder/'同轴约束分项验证.json',binding['scope_verification'])

    binding['stage']='verified' if binding['passed'] else 'verification_failed';core.write(session.folder/'运动对照.json',binding)
    scope_pass=binding.get('scope_verification',{}).get('scope_acceptance_passed') is True
    session.state('motion_scope_verified' if scope_pass and not binding['passed'] else 'motion_verified' if binding['passed'] else 'motion_not_verified',
        '事先确认的同轴约束范围验证通过；完整轨迹仍不同，分别保留结论。' if scope_pass and not binding['passed'] else '指定旋转与全部组件轨迹对照通过。整泵传动关系未认证。' if binding['passed'] else '运动对照未通过；已保存诊断，不重复求解。',motion=binding)
    return binding
