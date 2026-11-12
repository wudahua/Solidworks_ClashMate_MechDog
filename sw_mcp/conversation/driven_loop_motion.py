"""Primary-driven loop trials: actual full-grid Motion, never independent-joint claims."""
import math,uuid
from . import core,coupled_motion,geometry_audit as g
from .. import connection_trials as trials


def audit(grid,poses,bounds,review,requested):
    from .motion_tasks import require_same_poses
    if len(grid)!=31 or not poses:raise ValueError('driven_loop_complete_31_frame_grid_required')
    initial=require_same_poses({k:v[:12] for k,v in poses.items()},{k:v[:12] for k,v in grid[0].items()},'driven_loop_actual_frame_zero')
    primary=review['primary_goal_index'];results=[];outputs={cid:[] for cid in review['output_components']}
    if not outputs or not review['target_action_spans_equal']:raise ValueError('driven_loop_review_incomplete')
    for index,frame in enumerate(grid):
        if set(frame)!=set(poses):raise ValueError('driven_loop_frame_scope_mismatch')
        checks=[trials.measure(bound,frame) for bound in bounds]
        caps=[];stationary=[]
        for cid,p in poses.items():
            now=frame[cid];trials.validate(now)
            q=g.quat(g.mm(g.transpose(trials.rotation(p)),trials.rotation(now)))
            angle=2*math.atan2(g.norm(q[1:]),abs(q[0]));travel=math.dist(p[9:12],now[9:12])
            caps.append(travel<=.005 and angle<=math.pi/180)
            if cid in review['grounded_components']:stationary.append(travel<=trials.POSITION_TOLERANCE_M and angle<=trials.ANGLE_TOLERANCE_RAD)
            if cid in outputs:outputs[cid].append({'translation_m':travel,'rotation_rad':angle})
        expected=requested*index/30;actual=checks[primary]['axial_displacement_m']
        results.append({'frame':index,'expected_input_m':expected,'actual_input_m':actual,'joint_checks':checks,
                        'all_component_caps_passed':all(caps),'grounded_components_static':all(stationary),
                        'passed':all(c['passed'] for c in checks) and all(caps) and all(stationary) and abs(actual-expected)<=trials.POSITION_TOLERANCE_M})
    output_checks=[{'component_id':cid,'maximum_translation_m':max(p['translation_m'] for p in values),
                    'maximum_rotation_rad':max(p['rotation_rad'] for p in values),
                    'passed':any(p['translation_m']>5*trials.POSITION_TOLERANCE_M or p['rotation_rad']>5*trials.ANGLE_TOLERANCE_RAD for p in values)}
                   for cid,values in outputs.items()]
    return {'passed':initial['passed'] and all(r['passed'] for r in results) and all(r['passed'] for r in output_checks),
            'backend':'temporary_native_primary_driven_motion_study','frames':31,'pose_rows':31*len(poses),
            'requested_input_m':requested,'actual_input_m':results[-1]['actual_input_m'],
            'all_declared_joint_count':len(bounds),'sample_audits':results,'output_checks':output_checks,
            'native_motion_study_solved':True,'independent_joint_actuation_certified':False,'global_DOF_certified':False,'whole_travel_certified':False}


def run(s,goals,poses,bounds,review):
    from .motion_tasks import require_same_poses,pose_snapshot
    goal=goals[review['primary_goal_index']];driver=goal['driven_loop_driver'];face=driver['drive'];proofs=[]
    for sign in (1,-1):
        checkpoint=s.result_checkpoint;label='primary_'+str(sign);study='Loop_'+uuid.uuid4().hex[:10];receipt={};proof=None
        before=s.call('_connection_reference_state',model_id=s.model,verification_details=True)
        require_same_poses({k:v[:12] for k,v in poses.items()},pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components']),'driven_loop_before_create')
        try:
            s.state('driven_loop_motion_trial','正在按中央输入验证整机闭环、全部关节及输出，并逐次恢复…',direction=sign)
            reverse=driver['positive_trial_reverse'] if sign>0 else not driver['positive_trial_reverse']
            receipt['created']=s.call('create_motion_study',model_id=s.model,study=study,component_id=goal['component_a'],entity_id=face['entity_id'],
                motor_type='linear',speed=driver['speed_mm_s'],reverse_direction=reverse,reference_component_id=goal['component_b'],duration_s=1,output_fps=30)
            require_same_poses({k:v[:12] for k,v in poses.items()},pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components']),'driven_loop_after_create')
            run_id=uuid.uuid4().hex
            result=s.call('verify_motion_preservation',model_id=s.model,study=study,component_id=goal['component_a'],entity_id=face['entity_id'],
                expected_motion='linear',minimum_travel=driver['translation_step_m']*1000*.99,duration_s=1,output_fps=30,reference_component_id=goal['component_b'],run_id=run_id,plan_id='')
            receipt['native_verification']=result
            if result.get('run_id')!=run_id or result.get('assertion')!='pass' or result.get('restoration_status')!='restored' or result.get('source_files_unchanged') is not True or result.get('error_code'):
                raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','主驱动闭环运动未通过；保留证据，不改参数重复求解。',result)
            path=core.no_links(s.runtime/'runs'/run_id/'component-poses.csv');path.relative_to(s.runtime.resolve())
            grid=coupled_motion.samples(path,poses);proof=audit(grid,poses,bounds,review,sign*driver['translation_step_m'])
            proof['artifact']={'path':str(path),'sha256':core.digest(path),'run_id':run_id}
            core.write(s.folder/('整机主驱动采样-'+label+'.json'),{**proof,'all_poses_restored':False,'cleanup_status':'pending'})
            moved=s.call('_connection_reference_state',model_id=s.model,verification_details=True)
            if any(moved.get(k)!=before.get(k) for k in ('mate_parameters_signature','native_mate_count','fixed_states')) or not before.get('mate_parameters_signature'):
                raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','主驱动试验改变已有配合参数、数量或固定标志。')
        except (ValueError,KeyError,TypeError) as error:
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','主驱动闭环采样不完整或与声明目标不符。',{'reason':str(error),'direction':sign}) from error
        finally:
            core.write(s.folder/('整机主驱动运动-'+label+'.json'),receipt)
            if not s.unknown:
                preparation=s.call('_prepare_owned_snapshot_restore',model_id=s.model)
                core.write(s.folder/('整机主驱动恢复准备-'+label+'.json'),preparation)
                if preparation.get('model_context_verified') is not True or preparation.get('source_files_unchanged') is not True:
                    s.unknown=True;raise core.StopBatch('RESTORE_NOT_VERIFIED')
                restored=s.call('restore_model_checkpoint',model_id=s.model,checkpoint_id=checkpoint)
                core.write(s.folder/('整机主驱动恢复-'+label+'.json'),restored)
                if not core.restored_ok(restored):raise core.StopBatch('RESTORE_NOT_VERIFIED')
                after=s.call('_connection_reference_state',model_id=s.model,verification_details=True)
                if any(after.get(k)!=before.get(k) for k in ('mate_parameters_signature','native_mate_count','study_states','fixed_states')):
                    raise core.StopBatch('RESTORE_NOT_VERIFIED','整机临时算例移除、旧配合或时钟恢复未通过。')
                require_same_poses({k:v[:12] for k,v in poses.items()},pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components']),'driven_loop_after_restore')
        if proof is None:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED')
        proof.update(all_poses_restored=True,original_mates_parameters_unchanged=True,historical_study_states_restored=True)
        proofs.append(proof);core.write(s.folder/'整机主驱动逐帧审计.json',proofs)
        if not proof['passed']:break
    return proofs
