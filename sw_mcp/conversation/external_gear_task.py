"""Formal two-axis external gear task, with recommendation and ratio provenance."""
import csv,json,math,shutil,uuid
from pathlib import Path
from . import core,external_gears as eg,gear_transmission as gt,geometry_audit as g,concentric_card as card,task_execution,task_progress,component_constraints
from .. import assembly_constraints,assembly_completion


def discover(s):
    s.initial_inspection=s.call('inspect_model',model_id=s.model,detail_level='full')
    scope=component_constraints.inventory(s.initial_inspection['components'],s.initial_inspection['mates'])
    core.write(s.folder/'组件约束分类.json',scope)
    component_constraints.require_import_health(getattr(s,'import_preflight',None),s.folder/'导入.json')
    s.state('recommending','正在读取齿轮设计参数、两轴及固定支承，推荐缺失配合与传动比…')
    survey=s.call('_survey_external_gear_pair',model_id=s.model);s.external_survey=survey
    core.write(s.folder/'两轴齿轮原生证据.json',survey)
    review=assembly_constraints.analyze(survey['components'],survey['mates'],inventory_complete=survey.get('inventory_complete',False),structural_relations=survey.get('structural_relations'))
    core.write(s.folder/'装配约束检查与配合缺口.json',review)
    core.write(s.folder/'组件约束分类.json',component_constraints.inventory(survey['components'],survey['mates']))
    try:value=eg.recommend(survey,s.moving_hint,s.reference_hint)
    except core.StopBatch as error:
        if error.code=='EXTERNAL_GEAR_SCOPE_UNSUPPORTED':
            if error.diagnostics.get('proposed_motion_groups'):
                review=assembly_constraints.analyze(survey['components'],survey['mates'],error.diagnostics['proposed_motion_groups'],inventory_complete=survey.get('inventory_complete',False),structural_relations=survey.get('structural_relations'))
                core.write(s.folder/'装配约束检查与配合缺口.json',review)
            value={'proposals':[],'requires_selection':False,'requires_stationary_scope_review':True,'blocking_code':error.code,'scope':eg.SCOPE,
                   'scope_review':error.diagnostics,'assembly_constraint_review':assembly_constraints.summary(review),'write_dispatched':False}
            s.external_recommendation=value;core.write(s.folder/'两轴齿轮推荐.json',value)
            return {'external_gear_pair':value}
        if error.code not in {'EXTERNAL_GEAR_SELECTION_REQUIRED','EXTERNAL_GEAR_RATIO_AMBIGUOUS'}:raise
        value={'proposals':[],'requires_selection':True,'scope':eg.SCOPE,'mechanical_clarification':{
            'code':error.code,'question':str(error),'details':error.diagnostics},'write_dispatched':False}
    s.external_recommendation=value;core.write(s.folder/'两轴齿轮推荐.json',value)
    return {'external_gear_pair':value}


def propose(engine,t,candidate,initial_state,alignment_mode,moving,reference,ratio_numerator,ratio_denominator,role_hints,stationary_hints=None,assembly_intent=None):
    engine._require_session(t['task_id'])
    if stationary_hints is not None and not isinstance(stationary_hints,list):raise core.StopBatch('EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE','静止侧声明须为名称列表。')
    if t['phase'] not in {'proposal_ready','scope_review_required'}:raise core.StopBatch('TASK_NOT_READY_FOR_PLAN')
    if initial_state!='saved' or alignment_mode!='strict':raise core.StopBatch('EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE','普通两轴任务使用保存初态；不借用圆边小幅对齐授权。')
    for x in (ratio_numerator,ratio_denominator):
        if type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1000:raise core.StopBatch('EXTERNAL_GEAR_RATIO_INVALID')
    if bool(ratio_numerator)!=bool(ratio_denominator):raise core.StopBatch('EXTERNAL_GEAR_RATIO_INVALID','比例分子、分母须一起提供或同时留0使用推荐。')
    s=engine.sessions[t['task_id']]
    if assembly_intent is not None:
        if stationary_hints is not None:raise core.StopBatch('EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE','配合补齐的运动分组与固定简化声明不能混用。')
        try:
            if set(assembly_intent)!={'stationary','input','output'}:raise ValueError('external_pair_requires_three_named_groups')
            intent_groups=assembly_completion.declared_groups(s.external_survey['components'],assembly_intent)
        except (ValueError,TypeError) as error:raise core.StopBatch('EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE','AI须给出完整、互不重叠且精确匹配的静止/输入/输出机械分组。',{'reason':str(error)}) from error
        def completion_operation():
            s.state('planning','正在读取补约束参考；复用原配合和阵列，不批量固定附件…')
            survey=s.call('_survey_external_gear_pair',model_id=s.model,include_completion_references=True)
            core.write(s.folder/'补约束原生参考.json',survey)
            if survey['reference_state_signature']!=s.external_survey['reference_state_signature']:raise core.StopBatch('GEAR_PLAN_STALE')
            recommendation=eg.recommend(survey,moving or s.moving_hint,reference or s.reference_hint,role_hints,assembly_intent['stationary'],intent_groups)
            cards=recommendation['proposals'];matches=[r for r in cards if r['candidate_id']==candidate] if candidate else cards
            if len(matches)!=1:raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','运动分组仍不能唯一确定两轴组合。')
            selected=matches[0];roles=selected['roles']
            supplements=assembly_completion.plan(survey,intent_groups,{'stationary':roles['body'],'input':roles['input_shaft'],'output':roles['output_shaft']})
            core.write(s.folder/'最小补约束规划.json',supplements)
            if supplements['uncompleted_components']:raise core.StopBatch('EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW','仍有不能由当前受支持参考补齐的组件，未部分写入。',{'completion_plan':supplements})
            selected['constraint_completion']=supplements
            n,d=(ratio_numerator,ratio_denominator) if ratio_numerator else (selected['gear_ratio'].get('numerator'),selected['gear_ratio'].get('denominator'))
            if not n or not d:raise core.StopBatch('EXTERNAL_GEAR_RATIO_REQUIRED')
            motion=dict(t['motion_parameters']);motion['native_grid_policy']='exact_grid_or_exact_native_subset'
            from ..native_grid import recommend_exact_native_subset
            imported=core.read(s.folder/'导入.json')
            rates=[state.get('fps') for state in imported.get('checkpoint',{}).get('studies',[]) if state.get('type')==4]
            try:grid=recommend_exact_native_subset(motion['duration_s'],motion['output_fps'],len(survey['components']),rates)
            except ValueError as error:raise core.StopBatch('EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE','已知原生高帧率无法在当前时长和姿态预算内精确采样，须显式调整方案。',{'reason':str(error)}) from error
            if grid:
                motion['output_fps']=grid['recommended_sampling_fps'];motion['native_grid_recommendation']=grid
            ratio_abs=n/d;requested=motion['speed'];safe=min(60,40*motion['output_fps']/(6*max(1,ratio_abs)))
            motion['speed']=min(requested,safe);motion.update(signed_target_travel_deg=motion['speed']*motion['duration_s']*6*(-1 if motion['reverse_direction'] else 1),
                expected_travel=motion['speed']*motion['duration_s']*6,requested_speed_rpm=requested,speed_recommendation_changed=motion['speed']!=requested,
                speed_recommendation_reason='avoid_output_angle_aliasing_with_declared_sampling_grid')
            native=s.call('_preview_external_gear_pair',model_id=s.model,recommendation_json=json.dumps(selected,ensure_ascii=False),numerator=n,denominator=d)
            t.pop('blocking_code',None)
            t.update(phase='awaiting_confirmation',requires_stationary_scope_review=False,plan_token=uuid.uuid4().hex,
                proposal={**native,'recommendation':eg.public_card(selected),'ratio_provenance':selected['gear_ratio'] if not ratio_numerator else {'source':'explicit_plan_ratio_override','numerator':n,'denominator':d},
                          'motion':motion,'one_input_motor_only':True,'constraint_strategy':'minimum_independent_supplements_keep_original_mates_and_fixed_flags',
                          'pre_setup_motion_preservation_certified':False},
                next_action={'tool':'execute_mechanism_task','arguments':{'task_id':t['task_id'],'plan_token':None},
                    'instruction':'AI说明机械分组、每项补充配合、保留的原配合与阵列，以及副本采用保存姿态建立新算例初态、舍弃副本非零历史算例、核验进入模型标签建立模型级配合的明确范围；原文件与原检查点保留。AI说明native_grid_policy的原生精确时间点采样规则；若方案含native_grid_recommendation，明确说明请求与推荐采样帧率、原生结果帧率可能更高，以及只选精确已有原生时间点、不插值的规则。补齐不等于固定零件或已证明运动。确认完整方案后才一次execute，失败不重放。'})
            t['next_action']['arguments']['plan_token']=t['plan_token'];core.write(s.folder/'两轴齿轮待确认方案.json',t['proposal'])
        return engine._submit(t,'planning',completion_operation)
    recommendation=eg.recommend(s.external_survey,moving or s.moving_hint,reference or s.reference_hint,role_hints,stationary_hints) if moving or reference or any(role_hints.values()) or stationary_hints else s.external_recommendation
    if recommendation.get('requires_stationary_scope_review'):
        raise core.StopBatch('EXTERNAL_GEAR_SCOPE_UNSUPPORTED','先澄清静止附件的机械归属；名称线索不能代替静止侧范围声明。',recommendation['scope_review'])
    cards=recommendation['proposals']
    matches=[r for r in cards if r['candidate_id']==candidate] if candidate else cards
    if len(matches)!=1:raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','存在多个两轴组合，AI按零件用途澄清后选择推荐方案。',{'choices':cards,'mechanical_clarification':recommendation.get('mechanical_clarification')})
    selected=matches[0];ratio=selected['gear_ratio']
    n,d=(ratio_numerator,ratio_denominator) if ratio_numerator else (ratio.get('numerator'),ratio.get('denominator'))
    if not n or not d:raise core.StopBatch('EXTERNAL_GEAR_RATIO_REQUIRED',ratio.get('question','请确认希望采用的两轴比例。'),{'ratio_recommendation':ratio,'fields':['gear_ratio_numerator','gear_ratio_denominator']})
    ratio_abs=n/d
    # A proposed slower validation speed is visible in the plan and requires the
    # same explicit confirmation. It never silently changes an executed request.
    motion=dict(t['motion_parameters']);requested_speed=motion['speed'];safe=min(60,40*motion['output_fps']/(6*max(1,ratio_abs)))
    if motion['speed']>safe:motion['speed']=safe;motion['signed_target_travel_deg']=safe*motion['duration_s']*6*(-1 if motion['reverse_direction'] else 1)
    motion.update(expected_travel=motion['speed']*motion['duration_s']*6,
                  requested_speed_rpm=requested_speed,speed_recommendation_changed=motion['speed']!=requested_speed,
                  speed_recommendation_reason='avoid_output_angle_aliasing_with_declared_sampling_grid')
    def operation():
        native=s.call('_preview_external_gear_pair',model_id=s.model,recommendation_json=json.dumps(selected,ensure_ascii=False),numerator=n,denominator=d)
        t.pop('blocking_code',None)
        t.update(requires_stationary_scope_review=False,scope_review_status='declaration_planned_awaiting_write_confirmation')
        t.update(phase='awaiting_confirmation',plan_token=uuid.uuid4().hex,proposal={**native,'recommendation':eg.public_card(selected),
            'ratio_provenance':ratio if not ratio_numerator else {'source':'explicit_plan_ratio_override','numerator':n,'denominator':d},
            'motion':motion,'one_input_motor_only':True,'requires_explicit_assembly_and_ratio_confirmation':True,
            'constraint_strategy':'reuse_supports_retain_suppress_verified_rotor_pair_mates_and_add_one_rigid_where_needed','pre_setup_motion_preservation_certified':False},
            next_action={'tool':'execute_mechanism_task','arguments':{'task_id':t['task_id'],'plan_token':None},
                'instruction':'AI须逐项说明stationary_scope中的拟固定组件；静止侧声明不是写入授权，仍须确认当前完整方案。AI说明推荐输入/输出轴、齿轮、键和支承及比例依据，逐项列出复用/新增配合、转子组既有配合的保留压缩及刚性替换、支承旋转锁修改、解除固定及0.01mm预算；若建议降低试算转速明确说明前后值。取得具体方案授权后一次执行，不声称接触或任意齿轮已支持。'})
        t['next_action']['arguments']['plan_token']=t['plan_token'];core.write(s.folder/'两轴齿轮待确认方案.json',t['proposal'])
    return engine._submit(t,'planning',operation)


def audit(path,roles,groups,axis,settings,initial_components,native_axes,ratio_abs):
    try:data=g.load(path)
    except (ValueError,KeyError,OSError) as error:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED','两轴姿态证据不完整。',{'cause':str(error)}) from error
    ids={c['component_id'] for c in initial_components};frames=round(settings['duration_s']*settings['output_fps'])+1
    if data.keys()!={(f,c) for f in range(frames) for c in ids} or any(abs(float(r['time_s'])-f/settings['output_fps'])>1e-7 for (f,c),r in data.items()):raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED','组件或时间网格不匹配。')
    moving=set(groups['input']+groups['output']);initial={c['component_id']:card.pose_row(c) for c in initial_components}
    first_t=first_r=fixed_t=fixed_r=rigid_t=rigid_r=axial=radial=tilt=0
    for cid in ids:
        first_t=max(first_t,g.norm(g.sub(g.origin(data[0,cid]),g.origin(initial[cid]))));first_r=max(first_r,card.rotation_distance(data[0,cid],initial[cid]))
    values={cid:gt.angles(data,cid,roles['body'],axis) for cid in moving}
    group_errors={};support_evidence={}
    for side in ('input','output'):
        shaft=roles[side+'_shaft'];relative_angle=0
        for child in groups[side]:
            relative_angle=max(relative_angle,max(abs(a-b) for a,b in zip(values[child],values[shaft])))
            def relative(f):
                a,b=data[f,shaft],data[f,child]
                return g.mv(g.rotation(a),g.sub(g.origin(b),g.origin(a))),g.mm(g.rotation(b),g.transpose(g.rotation(a)))
            p0,r0=relative(0)
            for f in range(frames):
                p1,r1=relative(f);rigid_t=max(rigid_t,g.norm(g.sub(p1,p0)))
                rigid_r=max(rigid_r,math.acos(max(-1,min(1,(sum(r0[i][j]*r1[i][j] for i in range(3) for j in range(3))-1)/2))))
        group_errors[side]=relative_angle
        try:
            support_id=native_axes['support_axes'][side]['component_id']
            if support_id in moving:raise ValueError('SUPPORT_BELONGS_TO_MOVING_GROUP')
            bound=g.binding({'reference_a':native_axes['shaft_axes'][side],'reference_b':native_axes['support_axes'][side]},data,shaft,support_id,
                            allow_observed_stationary=native_axes.get('constraint_completion') is True)
            support_evidence[side]=bound['reference_stationarity_evidence']
            series=g.series(data,bound)
        except (ValueError,KeyError,TypeError) as error:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED','材料轴线或支承证据无法核验。',{'cause':str(error),'side':side}) from error
        axial=max(axial,max(abs(r['axial_displacement_mm'])/1000 for r in series));radial=max(radial,max(r['axis_radial_offset_mm']/1000 for r in series));tilt=max(tilt,max(math.radians(r['axis_tilt_deg']) for r in series))
    for f in range(frames):
        for cid in ids-moving:
            fixed_t=max(fixed_t,g.norm(g.sub(g.origin(data[f,cid]),g.origin(data[0,cid]))));fixed_r=max(fixed_r,card.rotation_distance(data[f,cid],data[0,cid]))
    ratio=max(abs(b+ratio_abs*a) for a,b in zip(values[roles['input_shaft']],values[roles['output_shaft']]))
    sign=-1 if settings['reverse_direction'] else 1
    target=max(abs(a-sign*settings['speed']*6*f/settings['output_fps']) for f,a in enumerate(values[roles['input_shaft']]))
    passed=first_t<=1e-7 and first_r<=1e-6 and fixed_t<=1e-7 and fixed_r<=1e-6 and rigid_t<=1e-7 and rigid_r<=1e-6 and ratio<=1e-4 and target<=.1 and axial<=1e-7 and radial<=1e-7 and tilt<=1e-6
    proof={'passed':passed,'rows':len(data),'frames':frames,'components':len(ids),'maximum_first_frame_translation_m':first_t,'maximum_first_frame_rotation_rad':first_r,
        'maximum_fixed_translation_m':fixed_t,'maximum_fixed_rotation_rad':fixed_r,'maximum_rigid_group_relative_translation_m':rigid_t,
        'maximum_rigid_group_relative_rotation_rad':rigid_r,'maximum_external_ratio_error_deg':ratio,'maximum_input_target_error_deg':target,
        'maximum_shaft_axial_displacement_m':axial,'maximum_shaft_radial_offset_m':radial,'maximum_shaft_axis_tilt_rad':tilt,
        'expected_output_over_input':-ratio_abs,'signed_final_degrees':{cid:v[-1] for cid,v in values.items()},'angles_by_component':values,
        'rotor_relative_angle_errors_deg':group_errors,'support_stationarity_evidence':support_evidence,'contact_or_tooth_geometry_validated':False}
    if not passed:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED',diagnostics=proof)
    return proof


def execute(engine,t,token,confirmed,scope_confirmed,alignment_confirmed):
    engine._require_session(t['task_id'])
    if confirmed is not True or scope_confirmed is not True:raise core.StopBatch('CONFIRMATION_REQUIRED','须确认推荐角色、比例、补配合及旋转状态修改。')
    if alignment_confirmed is not False:raise core.StopBatch('EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE')
    task_execution.require_plan_token(t,token)
    t['execution_consumed']=True;t['confirmation']={'confirmed':True,'scope_confirmed':True,'assembly_and_ratio_confirmed':True};engine.save(t)
    def operation():
        s=engine.sessions[t['task_id']];proposal=t['proposal'];p=proposal['motion'];roles=proposal['roles'];groups=proposal['groups']
        s.state('assembling','正在副本复用已有配合、补齐缺失约束并建立已确认比例…');s.import_restored=False
        applied=s.call('_apply_external_gear_pair',plan_id=proposal['plan_id'],confirmed=True);core.write(s.folder/'两轴齿轮配合成果.json',applied)
        if applied['roles']!=roles or applied['groups']!=groups or not applied['native_parameters']['verified']:raise core.StopBatch('GEAR_PARAMETERS_UNVERIFIED')
        s.committed=True;s.applied_plan=proposal['plan_id'];drive=applied['drive'];axis=applied['axis_global']
        from .motion_tasks import pose_snapshot,require_same_poses
        before=s.call('inspect_model',model_id=s.model,detail_level='components')['components']
        reverse=p['reverse_direction']^(g.dot(g.unit(drive['axis_global']),g.unit(axis))<0);study='External_'+uuid.uuid4().hex[:8]
        created=s.call('create_motion_study',model_id=s.model,study=study,component_id=roles['input_shaft'],entity_id=drive['entity_id'],reference_component_id=roles['body'],motor_type='rotary',speed=p['speed'],reverse_direction=reverse,duration_s=p['duration_s'],output_fps=p['output_fps'])
        core.write(s.folder/'两轴唯一马达.json',created)
        current=s.call('inspect_model',model_id=s.model,detail_level='full');components=current['components']
        core.write(s.folder/'两轴马达起点门禁.json',require_same_poses(pose_snapshot(before),pose_snapshot(components),'external_gear_motor_create'))
        flags_ok=({c['component_id']:c['fixed_component'] for c in components}==applied.get('observed_fixed_states')) if applied.get('constraint_completion') else ({c['component_id'] for c in components if not c['fixed_component']}==set(groups['input']+groups['output']))
        if len(current['mates'])!=applied['native_parameters']['reported_mate_count'] or not flags_ok:raise core.StopBatch('GEAR_FIXED_STATE_UNVERIFIED')
        observed_mask={str(m['native_feature_id']):m.get('suppressed') for m in current['mates']}
        if observed_mask!=applied.get('observed_mate_suppression') or any(type(v) is not bool for v in observed_mask.values()):
            raise core.StopBatch('GEAR_PARAMETERS_UNVERIFIED','新算例未保持配合补齐成果的逐项启用状态，未开始求解。',
                {'stage':'new_motion_study_constraint_mask','expected':applied.get('observed_mate_suppression'),'observed':observed_mask,'solve_dispatched':False})
        s.capture_applied_result();runs=[];ratio_abs=proposal['gear_ratio']['numerator']/proposal['gear_ratio']['denominator']
        for n in (1,2):
            task_progress.start_round(engine,t,n,2)
            s.state('solving',f'第{n}/2轮独立求解：核对两侧整组转角、传动比、材料轴线与固定件轨迹…')
            run=s.call('run_user_study',model_id=s.model,study=study,duration_s=p['duration_s'],output_fps=p['output_fps'],run_id=uuid.uuid4().hex,**({'allow_native_grid_subset':True} if p.get('native_grid_policy')=='exact_grid_or_exact_native_subset' else {}))
            core.write(s.folder/f'两轴求解-{n}.json',run)
            if run.get('result_validity')!='verified' or run.get('restoration_status')!='restored' or run.get('source_files_unchanged') is not True or run.get('error_code'):raise core.StopBatch(run.get('error_code') or 'GEAR_MOTION_EVIDENCE_FAILED',diagnostics=run)
            target=s.folder/f'两轴姿态-{n}.csv';shutil.copyfile(s.runtime/'runs'/run['run_id']/'component-poses.csv',target)
            s.state('auditing',f'第{n}/2轮求解已返回，正在独立审计；整项任务尚未通过。')
            proof=audit(target,roles,groups,axis,p,components,applied,ratio_abs);core.write(s.folder/f'两轴独立验证-{n}.json',proof)
            runs.append({'run_id':run['run_id'],'path':str(target),'sha256':core.digest(target),'audit':proof})
        repeat=core.compare_pose_files(runs[0]['path'],runs[1]['path'])
        if not repeat['passed']:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED',diagnostics=repeat)
        curve=s.folder/'两轴传动转角.csv';ids=list(runs[0]['audit']['angles_by_component'])
        with curve.open('w',encoding='utf-8-sig',newline='') as out:
            writer=csv.writer(out);writer.writerow(['time_s',*[cid+'_deg' for cid in ids]])
            for f in range(runs[0]['audit']['frames']):writer.writerow([f/p['output_fps'],*[runs[0]['audit']['angles_by_component'][cid][f] for cid in ids]])
        t['progress'].update(completed_rounds=2,stage='verified',verification_passed=True,
                             stage_source='task_verification',native_progress_observed=False)
        t.update(phase='verified',native_stage='verified',message='两轮求解、独立审计与重复性均通过；等待恢复或保留成果收尾。',verification={'scope':eg.SCOPE,'declared_scope_passed':True,'runs':runs,'repeatability':repeat,'roles':roles,'groups':groups,
            'gear_ratio':proposal['gear_ratio'],'ratio_provenance':proposal['ratio_provenance'],'motion':p,
            'baseline_run_id':runs[0]['run_id'],'after_run_id':runs[1]['run_id'],'curve':{'path':str(curve),'sha256':core.digest(curve),'quantity':'signed_rotation_deg_about_common_native_axis_relative_fixed_reference'},
            'contact_or_tooth_geometry_validated':False,'whole_mechanism_or_DOF_certified':False,'pre_setup_motion_preservation_certified':False},
            next_action={'tool':'finish_mechanism_task','arguments':{'task_id':t['task_id']},'instruction':'报告完整两轴组、比例来源、带符号转角、重复性与曲线；默认恢复，明确请求才保留已验证成果。'})
    return engine._submit(t,'running',operation)
