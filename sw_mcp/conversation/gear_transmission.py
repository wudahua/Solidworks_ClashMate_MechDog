"""Named pump template: six moving components, two rigid rotors, prescribed 1:1.

No contact or force evidence. Initial setup is a separate authorized assembly
operation, not a motion-preservation test. All writes use native plan/checkpoint.
"""
import csv,math,shutil,uuid
from pathlib import Path
from . import core,geometry_audit as g,concentric_card as card

SCOPE='named_pump_two_rigid_rotors_prescribed_external_1_to_1_not_contact'
ROLES={'body','input_shaft','input_gear','input_key','output_shaft','output_gear','output_key'}

def validate_roles(value):
    roles=value.get('roles',{})
    if set(roles)!=ROLES or len({r['component_id'] for r in roles.values()})!=7:
        raise core.StopBatch('GEAR_ROLE_SELECTION_REQUIRED','没有完整且互异的轴、键、齿轮及泵体角色。')
    if value.get('gear_ratio',{}).get('expected_output_over_input')!=-1 or value.get('scope')!=SCOPE:
        raise core.StopBatch('GEAR_PUMP_SCOPE_UNSUPPORTED')

def discover(session):
    session.initial_inspection=session.call('inspect_model',model_id=session.model,detail_level='full')
    session.state('recommending','正在核对泵的两根轴、两把键、两个齿轮及支承轴线…')
    value=session.call('_preview_gear_transmission',model_id=session.model);validate_roles(value)
    session.gear_candidate=value;core.write(session.folder/'齿轮传动推荐.json',value)
    session.state('recommended','已推荐完整1∶1反向比例传动；需确认角色、解除固定与副本装配方案。')
    return {'gear_transmission':value}

def propose(engine,t,candidate,initial_state,alignment_mode,moving_hint,reference_hint):
    engine._require_session(t['task_id'])
    if t['phase']!='proposal_ready':raise core.StopBatch('TASK_NOT_READY_FOR_PLAN')
    if candidate not in {'','candidate-1'}:raise core.StopBatch('INVALID_TASK_CANDIDATE')
    if initial_state!='saved' or alignment_mode!='strict' or moving_hint or reference_hint:
        raise core.StopBatch('GEAR_PUMP_SCOPE_UNSUPPORTED','首版泵模板使用保存初态及已推荐角色，不静默忽略额外选项。')
    def operation():
        s=engine.sessions[t['task_id']]
        value=s.call('_preview_gear_transmission',model_id=s.model);validate_roles(value)
        if {k:r['component_id'] for k,r in value['roles'].items()}!={k:r['component_id'] for k,r in s.gear_candidate['roles'].items()}:
            raise core.StopBatch('GEAR_PLAN_STALE','两次只读观察的角色不同。')
        t.update(phase='awaiting_confirmation',plan_token=uuid.uuid4().hex,
            proposal={**value,'motion':t['motion_parameters'],'rigid_group_connection':'shaft_key_gear_rigid_mates_not_key_contact',
                'one_input_motor_only':True,'finish_policy':'restore_import_checkpoint_then_close',
                'requires_explicit_component_unfix_and_nine_constraint_confirmation':True},
            next_action={'tool':'execute_mechanism_task','arguments':{'task_id':t['task_id'],'plan_token':None},
                'instruction':'说明两侧轴—键—齿轮分组、六个运动件、解除指定固定、9项约束、1∶1反向比例及最多0.01mm装配位移；只驱动长轴。明确同意完整方案后一次执行，不声称齿面接触或对齐前运动保留。'})
        t['next_action']['arguments']['plan_token']=t['plan_token'];core.write(s.folder/'完整传动待确认方案.json',t['proposal'])
    return engine._submit(t,'planning',operation)

def angles(data,cid,body,axis):
    reference=data[0,body];local_axis=g.unit(g.mv(g.rotation(reference),axis))
    initial=g.mm(g.rotation(data[0,cid]),g.transpose(g.rotation(reference)))
    out=[];previous=None;unwrapped=0
    for f in sorted({k[0] for k in data}):
        relative=g.mm(g.rotation(data[f,cid]),g.transpose(g.rotation(data[f,body])))
        q=g.quat(g.mm(g.transpose(relative),initial));angle=math.degrees(2*math.atan2(g.dot(q[1:],local_axis),q[0]))
        if previous is not None:
            step=(angle-previous+180)%360-180
            if abs(step)>45:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED','转角采样混叠。')
            unwrapped+=step
        previous=angle;out.append(unwrapped)
    return out

def audit(path,roles,axis,settings,initial_components,native_axes):
    try:data=g.load(path)
    except (ValueError,KeyError,OSError) as error:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED','姿态证据无法完整解析。',{'cause':str(error)}) from error
    ids={c['component_id'] for c in initial_components};frames=round(settings['duration_s']*settings['output_fps'])+1
    expected={(f,c) for f in range(frames) for c in ids}
    if data.keys()!=expected:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED','姿态组件或时间网格不完整。')
    if any(abs(float(r['time_s'])-f/settings['output_fps'])>1e-7 for (f,c),r in data.items()):raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED','采样时间不匹配。')
    initial={c['component_id']:card.pose_row(c) for c in initial_components};first_t=first_r=fixed_t=fixed_r=rigid_t=rigid_r=0
    moving={roles[k] for k in ROLES-{'body'}}
    for cid in ids:
        first_t=max(first_t,g.norm(g.sub(g.origin(data[0,cid]),g.origin(initial[cid]))));first_r=max(first_r,card.rotation_distance(data[0,cid],initial[cid]))
    for f in range(frames):
        for cid in ids-moving:
            fixed_t=max(fixed_t,g.norm(g.sub(g.origin(data[f,cid]),g.origin(data[0,cid]))));fixed_r=max(fixed_r,card.rotation_distance(data[f,cid],data[0,cid]))
        for side in ('input','output'):
            parent=roles[side+'_shaft']
            for child in (roles[side+'_key'],roles[side+'_gear']):
                def relative(frame):
                    a,b=data[frame,parent],data[frame,child]
                    return g.mv(g.rotation(a),g.sub(g.origin(b),g.origin(a))),g.mm(g.rotation(b),g.transpose(g.rotation(a)))
                p0,r0=relative(0);p1,r1=relative(f)
                rigid_t=max(rigid_t,g.norm(g.sub(p1,p0)))
                rigid_r=max(rigid_r,math.acos(max(-1,min(1,(sum(r0[i][j]*r1[i][j] for i in range(3) for j in range(3))-1)/2))))
    values={role:angles(data,cid,roles['body'],axis) for role,cid in roles.items() if role!='body'}
    ratio=max(abs(a+b) for a,b in zip(values['input_shaft'],values['output_shaft']))
    sign=-1 if settings['reverse_direction'] else 1
    target=max(abs(a-sign*settings['speed']*6*f/settings['output_fps']) for f,a in enumerate(values['input_shaft']))
    # Measure native cylinder centers/axes, not component origins (which may orbit).
    axial=tilt=radial=0
    for side in ('input','output'):
        bound=g.binding({'reference_a':native_axes['shaft_axes'][side],'reference_b':native_axes['support_axes'][side]},data,roles[side+'_shaft'],roles['body'])
        series=g.series(data,bound);axial=max(axial,max(abs(r['axial_displacement_mm'])/1000 for r in series))
        radial=max(radial,max(r['axis_radial_offset_mm']/1000 for r in series));tilt=max(tilt,max(math.radians(r['axis_tilt_deg']) for r in series))
    passed=first_t<=1e-7 and first_r<=1e-6 and fixed_t<=1e-7 and fixed_r<=1e-6 and rigid_t<=1e-7 and rigid_r<=1e-6 and ratio<=1e-4 and target<=.1 and tilt<=1e-6 and axial<=1e-7 and radial<=1e-7
    result={'passed':passed,'rows':len(data),'frames':frames,'components':len(ids),'maximum_first_frame_translation_m':first_t,
        'maximum_first_frame_rotation_rad':first_r,'maximum_fixed_translation_m':fixed_t,'maximum_fixed_rotation_rad':fixed_r,
        'maximum_rigid_group_relative_translation_m':rigid_t,'maximum_rigid_group_relative_rotation_rad':rigid_r,
        'maximum_external_ratio_error_deg':ratio,'maximum_input_target_error_deg':target,'maximum_shaft_axis_tilt_rad':tilt,
        'maximum_shaft_axial_displacement_m':axial,'maximum_shaft_radial_offset_m':radial,
        'signed_final_degrees':{k:v[-1] for k,v in values.items()},'angles_by_role':values,
        'contact_or_tooth_geometry_validated':False,'ratio_source':'confirmed_prescribed_1_to_1_gear_mate_not_tooth_contact'}
    if not passed:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED',diagnostics=result)
    return result

def execute(engine,t,token,confirmed,scope_confirmed,alignment_confirmed):
    engine._require_session(t['task_id'])
    if confirmed is not True or scope_confirmed is not True:raise core.StopBatch('CONFIRMATION_REQUIRED','须明确同意完整泵轴系准备、解除固定及比例传动验证。')
    if alignment_confirmed is not False:raise core.StopBatch('INVALID_ALIGNMENT_MODE','本方案的装配位移预算在完整轴系方案中确认，不借用单圆边对齐令牌。')
    from . import task_execution,task_progress
    task_execution.require_plan_token(t,token)
    t['execution_consumed']=True;t['confirmation']={'confirmed':True,'scope_confirmed':True,'assembly_setup_confirmed':True};engine.save(t)
    def operation():
        s=engine.sessions[t['task_id']];p=t['motion_parameters'];proposal=t['proposal'];validate_roles(proposal)
        s.state('assembling','正在副本准备两侧轴—键—齿轮、支承及已确认的1∶1齿轮配合…');s.import_restored=False
        applied=s.call('_apply_gear_transmission',plan_id=proposal['plan_id'],confirmed=True);core.write(s.folder/'完整轴系创建.json',applied)
        roles={k:r['component_id'] for k,r in proposal['roles'].items()}
        if applied['roles']!=roles or not applied['native_parameters']['verified']:raise core.StopBatch('GEAR_PARAMETERS_UNVERIFIED')
        s.committed=True;s.applied_plan=proposal['plan_id'];drive=applied['drive'];axis=applied['axis_global']
        if abs(g.dot(g.unit(drive['axis_global']),g.unit(axis)))<1-1e-10:raise core.StopBatch('GEAR_PARAMETERS_UNVERIFIED')
        reverse=p['reverse_direction']^(g.dot(g.unit(drive['axis_global']),g.unit(axis))<0)
        from .motion_tasks import pose_snapshot,require_same_poses
        before_motor=s.call('inspect_model',model_id=s.model,detail_level='components')['components']
        study='Gear_'+uuid.uuid4().hex[:8]
        created=s.call('create_motion_study',model_id=s.model,study=study,component_id=roles['input_shaft'],entity_id=drive['entity_id'],
            reference_component_id=roles['body'],motor_type='rotary',speed=p['speed'],reverse_direction=reverse,duration_s=p['duration_s'],output_fps=p['output_fps'])
        core.write(s.folder/'长轴唯一马达.json',created)
        inspection=s.call('inspect_model',model_id=s.model,detail_level='full');components=inspection['components']
        core.write(s.folder/'完整传动马达起点门禁.json',require_same_poses(pose_snapshot(before_motor),pose_snapshot(components),'gear_single_motor_create'))
        if len(inspection['mates'])!=9 or {c['component_id'] for c in components if not c['fixed_component']}!=set(roles.values())-{roles['body']}:
            raise core.StopBatch('GEAR_FIXED_STATE_UNVERIFIED')
        s.capture_applied_result();runs=[]
        for number in (1,2):
            task_progress.start_round(engine,t,number,2)
            s.state('solving',f'第{number}/2轮独立求解：核对完整比例传动六个运动件及固定件…')
            run=s.call('run_user_study',model_id=s.model,study=study,duration_s=p['duration_s'],output_fps=p['output_fps'],run_id=uuid.uuid4().hex)
            core.write(s.folder/f'完整传动求解-{number}.json',run)
            if run.get('result_validity')!='verified' or run.get('restoration_status')!='restored' or run.get('source_files_unchanged') is not True or run.get('error_code'):
                raise core.StopBatch(run.get('error_code') or 'GEAR_MOTION_EVIDENCE_FAILED',diagnostics=run)
            source=s.runtime/'runs'/run['run_id']/'component-poses.csv';target=s.folder/f'完整传动-{number}.csv';shutil.copyfile(source,target)
            proof=audit(target,roles,axis,p,components,applied);core.write(s.folder/f'完整传动独立验证-{number}.json',proof)
            runs.append({'run_id':run['run_id'],'path':str(target),'sha256':core.digest(target),'audit':proof})
        repeat=core.compare_pose_files(runs[0]['path'],runs[1]['path'])
        if not repeat['passed']:raise core.StopBatch('GEAR_MOTION_EVIDENCE_FAILED',diagnostics=repeat)
        curve=s.folder/'传动链转角.csv'
        with curve.open('w',encoding='utf-8-sig',newline='') as out:
            names=list(runs[0]['audit']['angles_by_role']);writer=csv.writer(out);writer.writerow(['time_s',*[k+'_deg' for k in names]])
            for f in range(runs[0]['audit']['frames']):writer.writerow([f/p['output_fps'],*[runs[0]['audit']['angles_by_role'][k][f] for k in names]])
        t.update(phase='verified',verification={'declared_scope_passed':True,'scope':SCOPE,'runs':runs,'repeatability':repeat,
            'baseline_run_id':runs[0]['run_id'],'after_run_id':runs[1]['run_id'],'roles':roles,'applied_plan_id':proposal['plan_id'],
            'curve':{'path':str(curve),'sha256':core.digest(curve),'quantity':'signed_rotation_deg_about_common_native_shaft_axis_relative_body'},
            'contact_or_tooth_geometry_validated':False,'whole_mechanism_or_DOF_certified':False,
            'pre_setup_motion_preservation_certified':False},next_action={'tool':'finish_mechanism_task','arguments':{'task_id':t['task_id']},
                'instruction':'报告六件联动、反向1∶1、固定件、重复性和曲线；这是齿轮配合强制比例联动。默认恢复导入检查点并核对退出；明确要求时才保留成果。'})
    return engine._submit(t,'running',operation)
