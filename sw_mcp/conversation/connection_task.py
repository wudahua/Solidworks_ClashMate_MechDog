"""Generic basic joints in the existing conversation task lifecycle."""
import json
import uuid
from . import core,source_integrity,task_execution
from .task_engine import matching_components,mechanical_choices
from .. import assembly_connections as joints,connection_trials as trials,connection_recommendations as recommendations


def discover(s):
    s.state('reviewing_constraints','正在只读核对配合健康、固定状态及局部运动线索…')
    survey=s.call('_survey_assembly_connections',model_id=s.model)
    s.connection_survey=survey;s.initial_inspection=survey if survey.get('inventory_complete') else s.call('inspect_model',model_id=s.model,detail_level='full')
    core.write(s.folder/'通用配合原生调查.json',survey)
    review=joints.review(survey);core.write(s.folder/'通用配合体检.json',review)
    draft=recommendations.draft(survey,review,binding=str(s.folder.parent.absolute()));s.connection_draft=draft
    core.write(s.folder/'装配连接自动草案.json',draft)
    return {'connection_review':review,'connection_draft':draft}


def publish_review(engine,t,value):
    s=engine.sessions[t['task_id']];source_integrity.bind(t,s)
    t.update(model_id=s.model,phase='constraint_review_ready',connection_review=value['connection_review'],connection_draft=value['connection_draft'],
        next_action={'tool':'plan_mechanism_task','arguments':{'task_id':t['task_id']},
            'instruction':'AI先解释原生配合故障、压缩项及局部连接线索。按用户已说明的机械目标，用connection_intent填写组件名称及rigid/revolute/prismatic；可自动采用唯一几何轴线，仅真实歧义才集中询问。不把局部秩当全机构自由度，不为消除浮动而锁死运动。若仅体检，可直接finish恢复收尾。'})


def resolve(s,intents):
    if not isinstance(intents,list) or not 1<=len(intents)<=8:raise core.StopBatch('CONNECTION_INTENT_INVALID','每次1至8项连接目标。')
    cs=s.connection_survey['components'];out=[]
    for raw in intents:
        if hasattr(raw,'model_dump'):raw=raw.model_dump()
        if not isinstance(raw,dict) or set(raw)-{'component_a','component_b','kind','axis_hint','candidate_id'}:
            raise core.StopBatch('CONNECTION_INTENT_INVALID','连接目标含未知字段。')
        row=dict(raw)
        for key in ('component_a','component_b'):
            text=row.get(key)
            if not isinstance(text,str) or not text.strip():raise core.StopBatch('CONNECTION_INTENT_INVALID','组件名称不能为空。')
            matches=matching_components(cs,text,None)
            if len(matches)!=1:
                return None,{'needs_mechanical_clarification':True,'field':key,'name_hint':text,
                    'choices':mechanical_choices(cs,text,None),'question':'请澄清组件名称或实例后缀；AI使用当前副本候选，不需要用户抄实体ID。','write_dispatched':False}
            row[key]=matches[0]['component_id']
        if row.get('kind') not in joints.KINDS:raise core.StopBatch('CONNECTION_INTENT_INVALID','仅支持rigid/revolute/prismatic。')
        if row.get('axis_hint') is not None:
            try:joints.ac.unit(row['axis_hint'])
            except (ValueError,TypeError) as error:raise core.StopBatch('CONNECTION_INTENT_INVALID','方向须为三个有限数，且不能为零向量。') from error
        for key in ('candidate_id','axis_hint'):
            if not row.get(key):row.pop(key,None)
        out.append(row)
    return out,None


def propose(engine,t,intents):
    engine._require_session(t['task_id'])
    if t['phase'] not in {'constraint_review_ready','awaiting_confirmation'}:raise core.StopBatch('TASK_NOT_READY_FOR_PLAN')
    s=engine.sessions[t['task_id']]
    if intents is None:return {'task_id':t['task_id'],'needs_connection_intent':True,
        'connection_draft':getattr(s,'connection_draft',None) or recommendations.draft(s.connection_survey),
        'connection_review':t['connection_review'],'write_dispatched':False,
        'instruction':'AI读取connection_draft，用候选connection_intent及推荐依据形成整组方案；已有机械目标可直接选择，真正歧义集中询问。草案不是原生预演或执行授权，实际plan仍须传具体connection_intent。现有方案不因只读草案查询自动撤销。'}
    if t['phase']=='awaiting_confirmation':
        t['previous_plan_id']=(t.get('proposal') or {}).get('plan_id')
        t.pop('plan_token',None);t.pop('proposal',None)
        t.update(phase='constraint_review_ready',plan_token_revoked=True);engine.save(t)
    goals,question=resolve(s,intents)
    if question:return {'task_id':t['task_id'],**question}
    try:proposal=joints.plan(s.connection_survey,goals)
    except (ValueError,TypeError) as error:
        reason=str(error)
        code='CONNECTION_GOAL_CONFLICT' if reason in {'existing_constraints_conflict_with_declared_motion','both_components_fixed_no_floating_target_for_native_trial','native_fully_constrained_mobile_goal_requires_review','native_full_constraint_conflicts_with_supported_missing_rank'} else 'CONNECTION_SCOPE_UNSUPPORTED' if reason=='native_inventory_or_health_requires_review' else 'CONNECTION_INTENT_INVALID'
        explanation={'native_fully_constrained_mobile_goal_requires_review':'局部运动线索与原生全约束观察冲突；先核对装配模型作用域及整条约束链，未解固定或补配合。',
            'native_full_constraint_conflicts_with_supported_missing_rank':'原生报告已全约束，但受支持局部模型仍有缺口；未知约束不能当作不存在，未继续补配合。',
            'existing_constraints_conflict_with_declared_motion':'原配合与目标运动冲突；未自动删除、压缩或解除固定。',
            'both_components_fixed_no_floating_target_for_native_trial':'目标两件均固定；先澄清机械目标，未自动解除固定。'}.get(reason,'连接目标或当前受支持范围未通过校验；AI核对诊断，不重试写入。')
        raise core.StopBatch(code,explanation,{'reason':reason,'cad_dispatched':False,'write_dispatched':False,
            'native_state_review_path':str(s.folder/'通用配合体检.json'),
            'original_mates_or_fixed_flags_automatically_changed':False}) from error
    core.write(s.folder/'通用连接补齐规划.json',proposal)
    if proposal['status']!='plan_ready':return {'task_id':t['task_id'],**proposal,
        'instruction':'仅当前已支持几何范围；AI解释缺失参考或轴线歧义，未部分提交配合。'}
    def operation():
        native=s.call('_preview_assembly_connections',model_id=s.model,proposal_json=json.dumps(
            {**proposal,'reference_state_signature':s.connection_survey['reference_state_signature']},ensure_ascii=False))
        t.update(phase='awaiting_confirmation',plan_token=uuid.uuid4().hex,plan_token_revoked=False,proposal={**native,
            'actions':proposal['actions'],'omitted_native_feature_ids':proposal['omitted_native_feature_ids'],
            'scope':'declared_basic_joints_small_trials_only_not_global_DOF_or_full_travel',
            'finish_policy':'restore_import_checkpoint_by_default'},
            next_action={'tool':'execute_mechanism_task','arguments':{'task_id':t['task_id']},
                'instruction':'解释连接目标、自动采用轴线、逐项新增配合、保留的旧约束及未知项、仅副本初态准备和有界试验范围。允许方向可使用临时距离或角度约束驱动，逐次恢复成果检查点移除，未修改原配合；禁止方向用装配移动求解。取得当前具体方案授权后一次执行。未证明全行程、受力或接触；默认恢复原导入状态。'})
    return engine._submit(t,'planning',operation)


def execute(engine,t,token,confirmed,scope_confirmed,alignment_confirmed):
    engine._require_session(t['task_id'])
    if confirmed is not True or scope_confirmed is not True:raise core.StopBatch('CONFIRMATION_REQUIRED','须确认补齐和有限位移验证的具体范围。')
    if alignment_confirmed is not False:raise core.StopBatch('CONNECTION_INTENT_INVALID','本流程保留初始装配姿态，不含重新对齐授权。')
    task_execution.require_plan_token(t,token)
    t['execution_consumed']=True;t['confirmation']={'confirmed':True,'scope_confirmed':True};engine.save(t)
    def operation():
        s=engine.sessions[t['task_id']];s.import_restored=False
        applied=s.call('_apply_assembly_connections',plan_id=t['proposal']['plan_id'],confirmed=True)
        core.write(s.folder/'通用连接补齐成果.json',applied);s.committed=True;s.capture_applied_result()
        poses={c['component_id']:c['transform'] for c in s.result_inspection['components']}
        try:bounds=[trials.bind(goal,poses) for goal in t['proposal']['goals']]
        except (ValueError,KeyError,TypeError) as error:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','初态材料参考绑定未通过。',{'reason':str(error)}) from error
        declared_count=len(bounds);declared_pairs={frozenset((g['component_a'],g['component_b'])) for g in t['proposal']['goals']}
        observed=joints.review({'components':s.result_inspection['components'],'mates':s.result_inspection['mates'],'inventory_complete':True})
        for row in observed['connections']:
            if row['recommended_joint_type'] not in joints.KINDS or frozenset((row['component_a'],row['component_b'])) in declared_pairs:continue
            old_goal={**row,'kind':row['recommended_joint_type'],'reference_point_global_m':row.get('axis_point_global_m')}
            bounds.append(trials.bind(old_goal,poses))
        core.write(s.folder/'已有连接运动保留绑定.json',bounds[declared_count:])
        audits=[];passed=True
        for i,goal in enumerate(t['proposal']['goals']):
            for trial in trials.trials(goal,poses):
                if not passed:break
                probe_id=uuid.uuid4().hex;s.state('bounded_joint_trial','正在验证允许运动与禁止方向，并逐次核对全部组件恢复…',goal_index=i,trial=trial['label'])
                target_json=json.dumps(trial['target'])
                receipt=s.call('_probe_assembly_connection_pose',model_id=s.model,component_id=goal['component_a'],
                    target_json=target_json,checkpoint_id=s.result_checkpoint,probe_id=probe_id,
                    goal_index=i,allowed_trial=trial['allowed'])
                path=core.no_links(core.Path(receipt['artifact_path']));path.relative_to(s.runtime.resolve())
                if path.name!=probe_id+'.json' or receipt.get('sha256')!=core.digest(path):raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','试验工件身份或哈希不符。')
                evidence=core.read(path)
                if evidence.get('model_id')!=s.model or evidence.get('probe_id')!=probe_id or evidence.get('component_id')!=goal['component_a']:
                    raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','试验证据与当前请求不符。')
                try:
                    binding=trials.require_target_binding(evidence,trial['target'],target_json)
                    audit=trials.audit(evidence,bounds,i,trial,poses)
                except (ValueError,KeyError,TypeError) as error:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','试验变换或证据范围无效。',{'reason':str(error),'artifact':receipt}) from error
                audits.append({**audit,'request_target_binding':binding,'artifact':receipt})
                core.write(s.folder/'基础运动副有界验证.json',audits);passed=audit['passed']
        proof={'declared_scope_passed':passed,'method':'native_assembly_solver_small_pose_trials',
            'connection_count':declared_count,'existing_supported_connection_checks':len(bounds)-declared_count,
            'existing_connection_scope':'supported_native_pair_relations_only_not_unknown_constraints_or_global_DOF',
            'omitted_native_feature_ids':observed['omitted_native_feature_ids'],
            'completed_trials':len(audits),'trials':audits,'native_motion_study_solved':False,
            'global_DOF_certified':False,'whole_travel_certified':False,'contact_or_force_validated':False,
            'position_tolerance_m':trials.POSITION_TOLERANCE_M,'angle_tolerance_rad':trials.ANGLE_TOLERANCE_RAD}
        t['verification']=proof;core.write(s.folder/'通用配合验证结论.json',proof)
        if not passed:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','补齐或有界运动验证未通过，停止后续试验；默认收尾恢复导入检查点。',proof)
        t.update(phase='verified',next_action={'tool':'finish_mechanism_task','arguments':{'task_id':t['task_id']},
            'instruction':'报告本次声明连接的小位移验证、旧约束和固定状态保持及每次恢复；不声称全机构自由度或全行程通过。默认恢复导入检查点并正常退出；只有用户明确要求才保留已验证成果副本。'})
    return engine._submit(t,'executing',operation)
