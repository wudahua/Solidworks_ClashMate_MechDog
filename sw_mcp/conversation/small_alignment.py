"""Separately authorized translation, then sampled post-alignment rotation.

This is a construction scope, NOT the strict pre/post mate preservation card.
No tilt correction, unfixing, geometry substitution or tolerance relaxation.
"""
import copy,math,uuid
from . import core,geometry_audit as g,concentric_card as card,mate_motion

SCHEMA='concentric-small-translation-1.0'
LIMIT_MM=.01

def proposal(plan,components,signature):
    try:card.create(plan,components,signature)
    except card.CardError as error:
        if error.code!='CARD_REQUIRES_ALIGNED_INITIAL_AXES_NO_REPOSITIONING':raise
    refs=[plan['reference_a'],plan['reference_b']]
    moving=next(r for r in refs if r['fixed_component'] is False);fixed=next(r for r in refs if r['fixed_component'] is True)
    initial={(0,c['component_id']):card.pose_row(c) for c in components}
    bound=g.binding(plan,initial,moving['component_id'],fixed['component_id']);start=g.series(initial,bound)[0]
    diagnostics={'observed_radial_offset_mm':start['axis_radial_offset_mm'],'maximum_translation_mm':LIMIT_MM,
        'observed_axis_tilt_deg':start['axis_tilt_deg'],'maximum_rotation_deg':math.degrees(card.TOL['rotation_rad']),
        'constraint_write_dispatched':False}
    if math.radians(start['axis_tilt_deg'])>card.TOL['rotation_rad']:
        raise core.StopBatch('ALIGNMENT_REQUIRES_PARALLEL_AXES',diagnostics=diagnostics)
    if start['axis_radial_offset_mm']>LIMIT_MM:
        raise core.StopBatch('ALIGNMENT_TRANSLATION_LIMIT_EXCEEDED',diagnostics=diagnostics)
    axis=g.unit(fixed['axis_global']);difference=g.sub(fixed['reference_point_global_m'],moving['reference_point_global_m'])
    along=g.dot(difference,axis);shift=[x-along*y for x,y in zip(difference,axis)]
    result={'schema':SCHEMA,'binding':bound,'native_pair':copy.deepcopy(refs),'initial_components':copy.deepcopy(components),
        'reference_state_signature':signature,'expected_translation_world_mm':[x*1000 for x in shift],
        'expected_translation_mm':g.norm(shift)*1000,'maximum_translation_mm':LIMIT_MM,
        'maximum_rotation_rad':card.TOL['rotation_rad'],'post_alignment_radial_tolerance_m':card.TOL['translation_m'],
        'axis_tilt_correction_allowed':False,'only_selected_component_may_translate':moving['instance'],
        'other_components_must_remain_fixed':True,'separate_alignment_confirmation_required':True,
        'motion_test':{'speed_rpm':12,'duration_s':1,'output_fps':30,'independent_runs':2,
            'expected_signed_twist_deg_each_run':72,'direction':'positive_about_selected_moving_edge_axis'},
        'scope':'bounded_initial_translation_then_post_alignment_rotation_repeatability',
        'pre_alignment_motion_preservation_certified':False,'whole_mechanism_or_DOF_certified':False}
    result['card_id']=card.seal(result);return result

def validate(value):
    if (value.get('schema')!=SCHEMA or value.get('card_id')!=card.seal(value) or value.get('maximum_translation_mm')!=LIMIT_MM
        or value.get('maximum_rotation_rad')!=card.TOL['rotation_rad'] or value.get('post_alignment_radial_tolerance_m')!=card.TOL['translation_m']):
        raise core.StopBatch('ALIGNMENT_PROPOSAL_STALE')

def audit(value,components):
    validate(value);before={c['component_id']:c for c in value['initial_components']};after={c['component_id']:c for c in components}
    if before.keys()!=after.keys():raise core.StopBatch('ALIGNMENT_AUDIT_FAILED','组件集合改变。')
    moving=value['binding']['moving'];axis=g.unit(next(r for r in value['native_pair'] if r['component_id']==moving)['axis_global'])
    other_t=other_r=0;target_t=target_r=0;delta=None
    for cid in before:
        a,b=card.pose_row(before[cid]),card.pose_row(after[cid]);shift=g.sub(g.origin(b),g.origin(a))
        rotation=card.rotation_distance(a,b)
        if before[cid]['fixed_component']!=after[cid]['fixed_component'] or after[cid].get('suppressed'):
            raise core.StopBatch('ALIGNMENT_AUDIT_FAILED','固定或抑制状态改变。')
        if cid==moving:delta=shift;target_t=g.norm(shift);target_r=rotation
        else:other_t=max(other_t,g.norm(shift));other_r=max(other_r,rotation)
    expected=[x/1000 for x in value['expected_translation_world_mm']]
    translation_error=g.norm(g.sub(delta,expected));axial=abs(g.dot(delta,axis))
    sample={(0,c['component_id']):card.pose_row(c) for c in components};geometry=g.series(sample,value['binding'])[0]
    passed=(target_t<=LIMIT_MM/1000 and target_r<=card.TOL['rotation_rad'] and other_t<=card.TOL['translation_m']
        and other_r<=card.TOL['rotation_rad'] and axial<=card.TOL['translation_m'] and translation_error<=card.TOL['translation_m']
        and geometry['axis_radial_offset_mm']<=card.TOL['translation_m']*1000 and math.radians(geometry['axis_tilt_deg'])<=card.TOL['rotation_rad'])
    result={'passed':passed,'target_translation_mm':target_t*1000,'target_rotation_rad':target_r,
        'translation_error_mm':translation_error*1000,'axial_translation_mm':axial*1000,
        'other_components_max_translation_m':other_t,'other_components_max_rotation_rad':other_r,'geometry':geometry}
    if not passed:raise core.StopBatch('ALIGNMENT_AUDIT_FAILED',diagnostics=result)
    return result

def execute(session,index,value):
    validate(value)
    if session.call('_circular_reference_state',model_id=session.model)['signature']!=value['reference_state_signature']:
        raise core.StopBatch('ALIGNMENT_PROPOSAL_STALE')
    plan=session.preview(index,LIMIT_MM,math.degrees(card.TOL['rotation_rad']))
    if [r['entity_id'] for r in value['native_pair']]!=[plan[k]['entity_id'] for k in ('reference_a','reference_b')]:
        raise core.StopBatch('CONFIRMED_PAIR_CHANGED')
    current=session.call('inspect_model',model_id=session.model,detail_level='components')['components']
    # Audit against the sealed initial poses before any constraint write.
    for old,new in zip(sorted(value['initial_components'],key=lambda c:c['component_id']),sorted(current,key=lambda c:c['component_id'])):
        if old['component_id']!=new['component_id'] or old['fixed_component']!=new['fixed_component'] or max(abs(a-b) for a,b in zip(old['transform'],new['transform']))>1e-9:
            raise core.StopBatch('ALIGNMENT_PROPOSAL_STALE')
    if len(current)!=len(value['initial_components']):raise core.StopBatch('ALIGNMENT_PROPOSAL_STALE')
    applied=session.apply(True)
    components=session.call('inspect_model',model_id=session.model,detail_level='components')['components']
    alignment=audit(value,components);core.write(session.folder/'小幅对齐实测.json',alignment)
    refreshed={}
    for ref in value['native_pair']:
        rows=mate_motion.component_geometry(session,ref['component_id'],'circular_edge')
        matches=[r for r in rows if r['entity_id']==ref['entity_id']]
        if len(matches)!=1:raise core.StopBatch('MOTION_PAIR_REDISCOVERY_REQUIRED')
        refreshed[ref['component_id']]=matches[0]
    refreshed_plan={**plan,**{key:refreshed[plan[key]['component_id']] for key in ('reference_a','reference_b')}}
    moving=value['binding']['moving'];faces=mate_motion.cylinder_faces(session,moving)
    binding=mate_motion.bind_drive(refreshed_plan,components,faces);binding['component_count']=len(components)
    axis=next(r['axis_global'] for r in value['native_pair'] if r['component_id']==moving)
    reverse=g.dot(g.unit(binding['axis_global']),g.unit(axis))<0
    study='Aligned_'+uuid.uuid4().hex[:8]
    created=session.call('create_motion_study',model_id=session.model,study=study,component_id=moving,
        entity_id=binding['drive']['entity_id'],reference_component_id=binding['reference']['component_id'],
        motor_type='rotary',speed=12,reverse_direction=reverse,duration_s=1,output_fps=30)
    core.write(session.folder/'对齐后驱动.json',created)
    current=session.call('inspect_model',model_id=session.model,detail_level='components')['components'];audit(value,current)
    aligned={(0,c['component_id']):card.pose_row(c) for c in components}
    if any(g.norm(g.sub(g.origin(card.pose_row(c)),g.origin(aligned[0,c['component_id']])))>card.TOL['translation_m']
        or card.rotation_distance(card.pose_row(c),aligned[0,c['component_id']])>card.TOL['rotation_rad'] for c in current):
        raise core.StopBatch('INITIAL_POSE_MISMATCH','创建马达改变了对齐后的起点。')
    if hasattr(session,'capture_applied_result'):session.capture_applied_result()
    runs=[]
    for number in (1,2):
        run=session.call('run_user_study',model_id=session.model,study=study,duration_s=1,output_fps=30,run_id=uuid.uuid4().hex)
        core.write(session.folder/f'对齐后求解-{number}.json',run)
        if run.get('result_validity')!='verified' or run.get('restoration_status')!='restored' or run.get('source_files_unchanged') is not True or run.get('error_code'):
            raise core.StopBatch(run.get('error_code') or 'ALIGNMENT_MOTION_NOT_VERIFIED',diagnostics=run)
        saved=mate_motion.snapshot_csv(session,run['run_id'],f'对齐后-{number}',binding)
        data=g.load(saved['path'])
        if data.keys()!={(f,c) for f in range(31) for _,c in aligned}:raise core.StopBatch('POSE_SCOPE_CHANGED')
        series=g.series(data,value['binding']);initial_error=max(g.norm(g.sub(g.origin(data[0,c]),g.origin(aligned[0,c]))) for f,c in aligned)
        initial_rotation_error=max(card.rotation_distance(data[0,c],aligned[0,c]) for f,c in aligned)
        passed=(saved['audit']['passed'] and initial_error<=card.TOL['translation_m']
            and initial_rotation_error<=card.TOL['rotation_rad']
            and all(abs(r['signed_twist_deg']-72*r['time_s'])<=.1 and abs(r['axial_displacement_mm'])<=card.TOL['translation_m']*1000
                and r['axis_radial_offset_mm']<=card.TOL['translation_m']*1000 and math.radians(r['axis_tilt_deg'])<=card.TOL['rotation_rad'] for r in series))
        saved.update(material_axis_passed=passed,initial_translation_error_m=initial_error,initial_rotation_error_rad=initial_rotation_error,material_series=series)
        if not passed:raise core.StopBatch('ALIGNMENT_MOTION_NOT_VERIFIED',diagnostics=saved)
        runs.append(saved)
    comparison=core.compare_pose_files(runs[0]['path'],runs[1]['path'])
    if not comparison['passed']:raise core.StopBatch('ALIGNMENT_MOTION_NOT_VERIFIED',diagnostics=comparison)
    result={'declared_scope_passed':True,'alignment':alignment,'runs':runs,'repeatability':comparison,
        'baseline_run_id':runs[0]['run_id'],'after_run_id':runs[1]['run_id'],'scope':value['scope'],
        'alignment_card_id':value['card_id'],'full_trajectory_equivalent':None,'pre_alignment_motion_preservation_certified':False,
        'whole_mechanism_or_DOF_certified':False,'applied_plan_id':session.applied_plan}
    core.write(session.folder/'小幅对齐与运动验证.json',result);return result
