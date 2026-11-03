"""Bounded Motion drivers for an existing screw linkage, never extra mates.

The two allowed translations are sampled native Motion solves. Forbidden
directions continue to use the assembly solver. Every temporary study is
removed by verified restoration before another direction is attempted.
"""
import csv,math,uuid
from . import core,mate_motion
from .. import assembly_constraints as a,connection_trials as trials,coupled_connections


def choose(goal,faces):
    axis=a.unit(goal['axis_global'])
    choices=[f for f in faces if f.get('component_id')==goal['component_a'] and f.get('kind')=='planar_normal'
             and abs(a.dot(a.unit(f['axis_global']),axis))>1-1e-8]
    if not choices:raise core.StopBatch('MOTION_POSE_EVIDENCE_UNAVAILABLE','已有联动找不到与确认直线方向平行的原生驱动面；未试用其他方向。')
    choices.sort(key=lambda f:(-f.get('area_m2',0),f['entity_id']))
    face=choices[0]
    return {'drive':face,'reference_component_id':goal['component_b'],
            'positive_trial_reverse':a.dot(a.unit(face['axis_global']),axis)<0,
            'duration_s':1,'output_fps':30,'speed_mm_s':trials.TRANSLATION_STEP_M*1000,
            'translation_step_m':trials.TRANSLATION_STEP_M,'temporary_study_restored_after_each_direction':True,
            'temporary_distance_or_angle_mate_added':False,'scope':'existing_linkage_bounded_motion_not_full_travel'}


def samples(path,poses,frames=31,fps=30):
    grid={}
    with path.open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            index=int(row['frame']);cid=row['component_id']
            if not 0<=index<frames or cid not in poses or cid in grid.setdefault(index,{}):raise ValueError('coupled_motion_pose_grid_invalid')
            if abs(float(row['time_s'])-index/fps)>1e-7:raise ValueError('coupled_motion_time_grid_invalid')
            p=[float(row['r'+str(i)+str(j)]) for i in range(3) for j in range(3)]+[float(row[k]) for k in ('x_m','y_m','z_m')]+[1,0,0,0]
            trials.validate(p);grid[index][cid]=p
    if sorted(grid)!=list(range(frames)) or any(set(v)!=set(poses) for v in grid.values()):raise ValueError('coupled_motion_pose_grid_incomplete')
    return [grid[i] for i in range(frames)]


def audit(grid,poses,bounds,selected,coupled,trial):
    from .motion_tasks import require_same_poses
    from . import geometry_audit as g
    initial=require_same_poses({k:v[:12] for k,v in poses.items()},{k:v[:12] for k,v in grid[0].items()},'coupled_motion_actual_frame_zero')
    results=[];signs=set()
    for index,frame in enumerate(grid):
        checks=[trials.measure(b,frame) for b in bounds];link=coupled_connections.audit(coupled,frame)
        if link['observed_signed_relation'] is not None:signs.add(link['observed_signed_relation'])
        travel=checks[selected]['axial_displacement_m'];expected=trial['requested']*index/(len(grid)-1)
        caps=[]
        for cid,p in poses.items():
            now=frame[cid]
            q=g.quat(g.mm(g.transpose(trials.rotation(p)),trials.rotation(now)))
            angle=2*math.atan2(g.norm(q[1:]),abs(q[0]))
            caps.append(math.dist(p[9:12],now[9:12])<=.005 and angle<=math.pi/180)
        passed=all(c['passed'] for c in checks) and link['passed'] and all(caps) and abs(travel-expected)<=trials.POSITION_TOLERANCE_M
        results.append({'frame':index,'passed':passed,'actual_travel_m':travel,'expected_travel_m':expected,
                        'connection_checks':checks,'coupled_motion_checks':link,'all_component_pose_caps_passed':all(caps)})
    return {'passed':initial['passed'] and all(r['passed'] for r in results) and len(signs)==1,
            'trial':trial['label'],'backend':'temporary_native_motion_study',
            'frames':len(grid),'pose_rows':len(grid)*len(poses),'actual_travel':results[-1]['actual_travel_m'],
            'requested_travel':trial['requested'],'observed_signed_relation':next(iter(signs)) if len(signs)==1 else None,
            'initial_pose_scope_matches':True,'sample_audits':results,
            'temporary_mates_added':0,'native_motion_study_solved':True,'whole_travel_certified':False}


def run(s,goal,trial,poses,bounds,selected,coupled):
    from .motion_tasks import require_same_poses,pose_snapshot
    driver=goal['coupled_motion_driver'];face=driver['drive'];study='Coupled_'+uuid.uuid4().hex[:10]
    label=trial['label'];before=s.call('_connection_reference_state',model_id=s.model,verification_details=True)
    checkpoint=s.result_checkpoint;receipt={};proof=None
    require_same_poses({k:v[:12] for k,v in poses.items()},pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components']),'coupled_before_create')
    try:
        s.state('coupled_motion_trial','正在用临时运动驱动验证已有丝杆联动，未增加距离配合…',trial=label)
        reverse=driver['positive_trial_reverse'] if trial['requested']>0 else not driver['positive_trial_reverse']
        receipt['created']=s.call('create_motion_study',model_id=s.model,study=study,component_id=goal['component_a'],entity_id=face['entity_id'],
            motor_type='linear',speed=driver['speed_mm_s'],reverse_direction=reverse,reference_component_id=goal['component_b'],duration_s=1,output_fps=30)
        require_same_poses({k:v[:12] for k,v in poses.items()},pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components']),'coupled_after_create')
        run_id=uuid.uuid4().hex
        result=s.call('verify_motion_preservation',model_id=s.model,study=study,component_id=goal['component_a'],entity_id=face['entity_id'],
            expected_motion='linear',minimum_travel=driver['translation_step_m']*1000*.99,duration_s=1,output_fps=30,
            reference_component_id=goal['component_b'],run_id=run_id,plan_id='')
        receipt['native_verification']=result
        if result.get('run_id')!=run_id or result.get('assertion')!='pass' or result.get('restoration_status')!='restored' or result.get('source_files_unchanged') is not True or result.get('error_code'):
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','已有联动的临时运动驱动未通过；保留证据，不改用其他驱动重复求解。',result)
        path=core.no_links(s.runtime/'runs'/run_id/'component-poses.csv');path.relative_to(s.runtime.resolve())
        grid=samples(path,poses);proof=audit(grid,poses,bounds,selected,coupled,trial)
        proof['artifact']={'path':str(path),'sha256':core.digest(path),'run_id':run_id}
        moved=s.call('_connection_reference_state',model_id=s.model,verification_details=True)
        if any(moved.get(k)!=before.get(k) for k in ('mate_parameters_signature','native_mate_count','fixed_states')) or not before.get('mate_parameters_signature'):
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','临时运动驱动改变了已有配合参数或数量。')
    except (ValueError,KeyError,TypeError) as error:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','已有联动的采样证据不完整或与确认范围不符。',{'reason':str(error),'trial':label,'solve_retried':False}) from error
    finally:
        core.write(s.folder/('已有联动运动-'+label+'.json'),receipt)
        if not s.unknown:
            restored=s.call('restore_model_checkpoint',model_id=s.model,checkpoint_id=checkpoint)
            core.write(s.folder/('已有联动恢复-'+label+'.json'),restored)
            if not core.restored_ok(restored):raise core.StopBatch('RESTORE_NOT_VERIFIED')
            after=s.call('_connection_reference_state',model_id=s.model,verification_details=True)
            if any(after.get(k)!=before.get(k) for k in ('mate_parameters_signature','native_mate_count','study_states','fixed_states')):
                raise core.StopBatch('RESTORE_NOT_VERIFIED','已有配合、临时算例移除或历史时钟恢复未通过。')
            require_same_poses({k:v[:12] for k,v in poses.items()},pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components']),'coupled_after_restore')
    if proof is None:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED')
    proof.update(all_poses_restored=True,original_mates_parameters_unchanged=True,historical_study_states_restored=True)
    return proof
