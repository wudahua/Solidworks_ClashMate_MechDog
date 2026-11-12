"""Reuse a kept, verified flat mechanism for finite, sampled working-stroke checks.

The original 0.1mm assembly trial is unchanged. No inferred design end stops,
contact, force, global DOF or whole-travel certification belongs to this module.
"""
import copy,math,re
from pathlib import Path
from . import core,coupled_motion,geometry_audit as g,source_integrity
from .. import connection_trials as trials,assembly_constraints as a

MAX_INPUT_M=.02
MAX_COMPONENT_TRAVEL_M=.05
MAX_COMPONENT_ROTATION_RAD=math.pi/12


def require(condition,reason):
    if not condition:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','不能复用整机成果进行工作行程验证；未重建配合或自动放宽范围。',{'reason':reason})


def audit(grid,poses,bounds,review,requested,duration_s=1,output_fps=30):
    from .motion_tasks import require_same_poses
    require(type(requested) in (int,float) and math.isfinite(requested) and 0<abs(requested)<=MAX_INPUT_M,'working_stroke_input_outside_20mm_policy')
    require(type(duration_s) in (int,float) and math.isfinite(duration_s) and 0<duration_s<=5 and type(output_fps) is int and 5<=output_fps<=120,'working_stroke_invalid_time_grid')
    from sw_mcp.native_grid import require_grid
    require_grid(duration_s,output_fps)
    frames=round(duration_s*output_fps)+1
    require(len(grid)==frames and 2<=frames<=601 and 1<=len(poses)<=128,'working_stroke_complete_grid_required')
    require(set(poses)==set().union(*(set((b['component_a'],b['component_b'])) for b in bounds)),'working_stroke_target_coverage_incomplete')
    require(set(review['grounded_components'])<=set(poses) and bool(review['grounded_components']),'working_stroke_grounded_scope_invalid')
    outputs=review['output_components'];primary=review['primary_goal_index']
    require(len(outputs)==len(set(outputs)) and 1<=len(outputs)<=16 and set(outputs)<=set(poses),'working_stroke_outputs_invalid')
    require(type(primary) is int and 0<=primary<len(bounds) and bounds[primary]['kind']=='prismatic' and review['target_action_spans_equal'] is True,'working_stroke_primary_invalid')
    initial=require_same_poses({k:v[:12] for k,v in poses.items()},{k:v[:12] for k,v in grid[0].items()},'working_stroke_actual_frame_zero')
    maxima={'component_translation_m':0.,'component_rotation_rad':0.,'grounded_translation_m':0.,'grounded_rotation_rad':0.,'input_error_m':0.}
    moved={cid:False for cid in outputs};rows=[]
    for index,frame in enumerate(grid):
        require(set(frame)==set(poses),'working_stroke_frame_scope_mismatch')
        checks=[trials.measure(b,frame) for b in bounds];caps=True;static=True
        for cid,p in poses.items():
            now=frame[cid];trials.validate(now)
            q=g.quat(g.mm(g.transpose(trials.rotation(p)),trials.rotation(now)))
            angle=2*math.atan2(g.norm(q[1:]),abs(q[0]));travel=math.dist(p[9:12],now[9:12])
            maxima['component_translation_m']=max(maxima['component_translation_m'],travel)
            maxima['component_rotation_rad']=max(maxima['component_rotation_rad'],angle)
            caps &= travel<=MAX_COMPONENT_TRAVEL_M and angle<=MAX_COMPONENT_ROTATION_RAD
            if cid in review['grounded_components']:
                static &= travel<=trials.POSITION_TOLERANCE_M and angle<=trials.ANGLE_TOLERANCE_RAD
                maxima['grounded_translation_m']=max(maxima['grounded_translation_m'],travel)
                maxima['grounded_rotation_rad']=max(maxima['grounded_rotation_rad'],angle)
            if cid in moved:moved[cid] |= travel>5*trials.POSITION_TOLERANCE_M or angle>5*trials.ANGLE_TOLERANCE_RAD
        expected=requested*index/(frames-1);actual=checks[primary]['axial_displacement_m'];error=abs(actual-expected)
        maxima['input_error_m']=max(maxima['input_error_m'],error)
        rows.append({'frame':index,'time_s':index/output_fps,'expected_input_m':expected,'actual_input_m':actual,
            'joint_checks':checks,'component_envelope_passed':bool(caps),'grounded_static':bool(static),
            'passed':all(c['passed'] for c in checks) and bool(caps) and bool(static) and error<=trials.POSITION_TOLERANCE_M})
    return {'passed':initial['passed'] and all(r['passed'] for r in rows) and all(moved.values()),
        'frames':frames,'components':len(poses),'pose_rows':frames*len(poses),'joint_targets':len(bounds),
        'requested_input_m':requested,'actual_input_m':rows[-1]['actual_input_m'],'output_motion_checks':moved,
        'maximum_observed':maxima,'sample_audits':rows,'component_translation_cap_m':MAX_COMPONENT_TRAVEL_M,
        'component_rotation_cap_rad':MAX_COMPONENT_ROTATION_RAD,'position_tolerance_m':trials.POSITION_TOLERANCE_M,
        'angle_tolerance_rad':trials.ANGLE_TOLERANCE_RAD,'scope':'sampled_declared_mechanism_working_stroke',
        'design_end_stops_known':False,'whole_travel_certified':False,'global_DOF_certified':False,'contact_or_force_validated':False}


def imported_components(session,task,original,expected_files):
    """Exact importer source SHA/copy path + occurrence identity, then all poses.

    Flat external parts only, no geometry-based or name-suffix-only guessing.
    """
    base=core.no_links(session.runtime/'experiments/user_assemblies'/session.model[5:])
    evidence_path=base/'import-evidence.json';evidence=core.read(evidence_path);manifest=core.read(base/'model.json')
    require(manifest['Id']==session.model and set(evidence['copy_paths'])==set(manifest['Files']),'working_stroke_import_manifest_mismatch')
    expected={str(core.no_links(p)):source_integrity.normalized_hash(h) for p,h in expected_files.items()}
    observed={str(core.no_links(p)):source_integrity.normalized_hash(h) for p,h in evidence['source_hashes'].items()}
    require(expected==observed and all(expected.values()),'working_stroke_saved_dependency_hash_mismatch')
    current=session.initial_inspection['components'];require(len(current)==len(original),'working_stroke_component_count_changed')
    by_path={};by_name={c['instance']:c for c in original}
    for source,h in expected.items():
        p=core.no_links(source);require(p.is_file() and core.digest(p)==h,'working_stroke_result_source_changed')
        if p.suffix.lower()!='.sldprt':continue
        matches=[core.no_links(q) for q in evidence['copy_paths'] if Path(q).name.casefold()==p.name.casefold() or Path(q).name.casefold().endswith('_'+p.name.casefold())]
        require(len(matches)==1 and core.digest(matches[0])==h,'working_stroke_part_copy_identity_invalid')
        require(str(matches[0]).casefold() not in by_path,'working_stroke_duplicate_part_copy')
        by_path[str(matches[0]).casefold()]=p
    mapping={};proof=[]
    for now in current:
        require(not now.get('subassembly') and now.get('loaded') is True and not now.get('suppressed') and not now.get('speedpak'),'working_stroke_requires_flat_loaded_parts')
        copied=core.no_links(now['path']);source=by_path.get(str(copied).casefold())
        require(source is not None and now['instance'].startswith(copied.stem+'-'),'working_stroke_component_copy_not_bound')
        ordinal=now['instance'][len(copied.stem):];require(re.fullmatch('-[1-9][0-9]*',ordinal),'working_stroke_occurrence_invalid')
        old=by_name.get(source.stem+ordinal)
        require(old is not None and Path(old['path']).name.casefold()==source.name.casefold() and old['component_id'] not in mapping,'working_stroke_occurrence_not_unique')
        require(now.get('configuration')==old.get('configuration') and now.get('fixed_component') is old.get('fixed_component'),'working_stroke_configuration_or_fixed_changed')
        mapping[old['component_id']]=now['component_id'];proof.append({'original_component_id':old['component_id'],'component_id':now['component_id'],'instance':now['instance'],'source_path':str(source),'copied_path':str(copied)})
    require(len(mapping)==len(original),'working_stroke_identity_incomplete')
    return mapping,{'path':str(evidence_path),'sha256':core.digest(evidence_path),'components':proof}


def bind(engine,task,session,baseline_task_id,candidate):
    from .motion_tasks import require_same_poses,motion_direction_binding
    require(bool(re.fullmatch('[a-f0-9]{32}',baseline_task_id)) and baseline_task_id!=task['task_id'],'working_stroke_baseline_task_id_invalid')
    old=engine.tasks.get(baseline_task_id);require(old is not None,'working_stroke_verified_task_not_in_history')
    finish=old.get('finish',{});verification=old.get('verification',{})
    require(old.get('closed') is True and old.get('task_kind')=='assembly_constraints' and finish.get('cleanup_status')=='pass' and finish.get('source_files_unchanged') is True,'working_stroke_baseline_not_normally_closed')
    require(verification.get('declared_scope_passed') is True and verification.get('whole_assembly_declared_targets_passed') is True and verification.get('native_motion_study_solved') is True,'working_stroke_whole_mechanism_not_verified')
    proposal=old.get('proposal') or {}
    require(isinstance(proposal,dict) and isinstance(proposal.get('driven_loop_review'),dict) and isinstance(proposal.get('goals'),list) and 1<=len(proposal['goals'])<=128,'working_stroke_requires_verified_driven_loop_scope')
    require(finish.get('session',{}).get('committed_copy_preserved') is True and finish.get('native_exit',{}).get('normal_zero_exit') is True and finish.get('executor_exit',{}).get('confirmed') is True and finish.get('executor_exit',{}).get('executor_exit_code')==0,'working_stroke_baseline_result_not_kept')
    require(finish.get('native_exit',{}).get('force_kill') is False and finish.get('executor_exit',{}).get('force_kill') is False,'working_stroke_baseline_force_exit_or_missing_receipt')
    require(task['motion_parameters']['motion']=='linear' and task['motion_parameters']['expected_travel']*.001<=MAX_INPUT_M,'working_stroke_requires_linear_input_within_20mm')
    source=core.no_links(task['source']);require(source==core.no_links(finish['result_assembly_path']) and core.digest(source)==finish['result_assembly_sha256'],'working_stroke_requires_exact_kept_result_source')
    directory=core.no_links(old['directory']);directory.relative_to(core.no_links(engine.work))
    checkpoint_path=directory/'session/成果检查点.json';saved=core.read(checkpoint_path);snapshot_path=core.no_links(saved['checkpoint']['checkpoint_path']);snapshot=core.read(snapshot_path)
    require(source_integrity.normalized_hash(snapshot['files'].get(str(source)))==finish['result_assembly_sha256'],'working_stroke_result_checkpoint_not_bound')
    original=saved['inspection']['components'];require(1<=len(original)<=128 and len({c['instance'] for c in original})==len(original),'working_stroke_baseline_inventory_invalid')
    require(len(session.initial_inspection['mates'])==len(saved['inspection']['mates']),'working_stroke_native_mate_count_changed')
    mapping,identity=imported_components(session,task,original,snapshot['files'])
    poses={mapping[c['component_id']]:c['transform'] for c in original};current={c['component_id']:c['transform'][:12] for c in session.initial_inspection['components']}
    require_same_poses({k:p[:12] for k,p in poses.items()},current,'working_stroke_saved_result_initial_pose')
    proposal=old['proposal'];bounds=[trials.bind(goal,{c['component_id']:c['transform'] for c in original}) for goal in proposal['goals']]
    for b in bounds:
        for k in ('component_a','component_b'):b[k]=mapping[b[k]]
    review=copy.deepcopy(proposal['driven_loop_review']);require(review['target_action_spans_equal'] is True,'working_stroke_baseline_targets_not_complete')
    for k in ('component_a','component_b'):review['primary'][k]=mapping[review['primary'][k]]
    for k in ('output_components','grounded_components'):review[k]=[mapping[cid] for cid in review[k]]
    primary=review['primary'];require(candidate['drive']['component_id']==primary['component_a'] and candidate['reference']['component_id']==primary['component_b'],'working_stroke_wrong_primary_driver')
    dot=a.dot(a.unit(candidate['drive']['axis_global']),a.unit(review['axis_global']));require(abs(dot)>1-1e-8,'working_stroke_wrong_primary_axis')
    parameters=task['motion_parameters'];sign=motion_direction_binding(candidate['drive'],parameters)['expected_sign_about_selected_native_axis']
    requested=parameters['expected_travel']*.001*sign*(1 if dot>0 else -1)
    artifacts=[directory/'任务状态.json',checkpoint_path,snapshot_path,Path(identity['path'])]
    value={'baseline_task_id':baseline_task_id,'poses':poses,'bounds':bounds,'review':review,'requested_input_m':requested,
        'duration_s':parameters['duration_s'],'output_fps':parameters['output_fps'],'native_import_identity':identity,
        'source_dependencies':{str(p):source_integrity.normalized_hash(h) for p,h in snapshot['files'].items()},
        'evidence_files':[{'path':str(p),'sha256':core.digest(p)} for p in artifacts]}
    path=session.folder/'工作行程验证绑定.json';core.write(path,value)
    return {'baseline_task_id':baseline_task_id,'binding_path':str(path),'binding_sha256':core.digest(path),
        'components':len(poses),'joint_targets':len(bounds),'output_components':len(review['output_components']),
        'requested_input_mm':requested*1000,'maximum_input_mm':MAX_INPUT_M*1000,
        'maximum_component_translation_mm':MAX_COMPONENT_TRAVEL_M*1000,'maximum_component_rotation_deg':math.degrees(MAX_COMPONENT_ROTATION_RAD),
        'scope':'sampled_declared_mechanism_working_stroke','design_end_stops_known':False,'whole_travel_certified':False,'contact_or_force_validated':False}


def load(session,summary):
    path=core.no_links(summary['binding_path']);require(path.parent==core.no_links(session.folder) and core.digest(path)==summary['binding_sha256'],'working_stroke_binding_changed')
    value=core.read(path)
    for row in value['evidence_files']:require(core.digest(core.no_links(row['path']))==row['sha256'],'working_stroke_evidence_changed')
    for p,h in value['source_dependencies'].items():require(core.digest(core.no_links(p))==h,'working_stroke_result_source_changed')
    return value


def verify(session,summary,path):
    value=load(session,summary)
    grid=coupled_motion.samples(path,value['poses'],frames=round(value['duration_s']*value['output_fps'])+1,fps=value['output_fps'])
    result=audit(grid,value['poses'],value['bounds'],value['review'],value['requested_input_m'],value['duration_s'],value['output_fps'])
    result.update(baseline_task_id=value['baseline_task_id'],pose_artifact={'path':str(path),'sha256':core.digest(path)})
    core.write(session.folder/'工作行程逐帧验证.json',result)
    brief={k:v for k,v in result.items() if k!='sample_audits'}
    if not result['passed']:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','原生驱动已完成，但整机工作行程核对未通过；保留全部姿态和失败诊断，不扩大范围或重复求解。',brief)
    return brief
