"""Generic basic joints in the existing conversation task lifecycle."""
import json
import uuid
from . import core,source_integrity,task_execution
from .task_engine import matching_components,mechanical_choices
from ..bridge import CadError
from .. import assembly_connections as joints,connection_trials as trials,connection_recommendations as recommendations,connection_groups,assembly_overview,connection_batches,assembly_hierarchy


def discover(s):
    s.state('reviewing_constraints','正在只读核对配合健康、固定状态及局部运动线索…')
    from . import constraint_inventory
    preflight=getattr(s,'import_preflight',None) or {}
    if constraint_inventory.blockers(preflight):
        return constraint_inventory.discover(s,preflight)
    try:
        survey=s.call('_survey_assembly_connections',model_id=s.model)
    except (core.StopBatch,CadError) as error:
        diagnostic=error.diagnostics if isinstance(error.diagnostics,dict) else {}
        details=diagnostic.get('details') or {}
        if (error.code!='CONNECTION_REFERENCE_INVALID' or getattr(s,'unknown',True)
                or not isinstance(details,dict) or details.get('reason')!='native_mate_reference_identity_unavailable'
                or details.get('write_dispatched') is not False or details.get('signature_complete') is not False):
            raise
        # The native signature reader stopped before candidate traversal or writes.
        # Do not replace missing identity with a constant or certify it unchanged.
        core.write(s.folder/'现有配合参考身份未认证.json',details)
        s.state('reviewing_constraints','现有配合参考身份未认证，正在只读报告结构及原生健康；未跳过写入签名门禁。')
        return constraint_inventory.discover(s,preflight,reference_issue=details)
    s.connection_survey=survey;s.initial_inspection=survey if survey.get('inventory_complete') else s.call('inspect_model',model_id=s.model,detail_level='full')
    core.write(s.folder/'通用配合原生调查.json',survey)
    review=joints.review(survey);core.write(s.folder/'通用配合体检.json',review)
    core.write(s.folder/'整装配约束图.json',review.get('assembly_constraint_graph'))
    binding=str(s.folder.parent.absolute())
    context=recommendations.prepare_context(survey,review,binding) if review.get('complete') and not review.get('mate_health_issues') else None
    draft=recommendations.draft(survey,review,binding=binding,context=context);s.connection_draft=draft
    core.write(s.folder/'装配连接自动草案.json',draft)
    overview=assembly_overview.recommend(survey,review);core.write(s.folder/'整装配组件推荐与遗漏检查.json',overview)
    from .. import assembly_assessment
    assessment=assembly_assessment.build(survey,review,overview,draft,binding=binding,draft_context=context)
    s.connection_candidates=(context or {}).get('captured_candidates',draft.get('candidates',[]))
    s.assembly_assessment=assessment;core.write(s.folder/'首轮装配处理结论.json',assessment)
    from ..connection_layers import catalog
    layers=catalog(s.call('_survey_connection_layers',model_id=s.model))
    s.assembly_layers=layers;core.write(s.folder/'分层装配检查清单.json',layers)
    return {'connection_review':review,'connection_draft':draft,'assembly_overview':overview,'assembly_layers':layers,'assembly_assessment':assessment}


def publish_review(engine,t,value):
    s=engine.sessions[t['task_id']];source_integrity.bind(t,s)
    t['assembly_layers']=value.get('assembly_layers')
    assessment=value.get('assembly_assessment')
    if assessment is None:
        from .. import assembly_assessment
        assessment=assembly_assessment.readonly(getattr(s,'connection_survey',{}),value['connection_review'])
    t['assembly_assessment']=assessment
    t.update(model_id=s.model,phase='constraint_review_ready',connection_review=value['connection_review'],connection_draft=value['connection_draft'],assembly_overview=value.get('assembly_overview'),
        next_action={'tool':'plan_mechanism_task','arguments':{'task_id':t['task_id']},
            'instruction':'AI先解释原生配合故障、压缩项及局部连接线索。按用户已说明的机械目标，用connection_intent填写组件名称及rigid/revolute/prismatic；可自动采用唯一几何轴线，仅真实歧义才集中询问。不把局部秩当全机构自由度，不为消除浮动而锁死运动。若仅体检，可直接finish恢复收尾。'})
    if assessment.get('automatic_plan_available'):
        t['next_action'].update(arguments={'task_id':t['task_id'],'auto_plan':True},instruction='AI解释首轮完整分类，自动读取建议目标的原生预演。建议机械用途仍待具体方案确认，不直接execute。')
    elif assessment.get('group_seed_suggestions'):
        t['next_action']['instruction']+='组件较多时，AI先复用已明确用途和group_seed_suggestions，自选各运动组代表件调用group_seeds只读推荐附件；只集中澄清仍冲突的归属，不把选代表件或逐件填清单交给用户。'
    t['next_action']['instruction']+='阵列件优先按已观察的完整种子链组成同用途局部组，仅为种子补必要约束，保留派生关系并逐次验证全部组成员；不要求用户逐个指定派生件。'

    if value.get('constraint_structure'):
        from .constraint_inventory import publish
        publish(engine,t,value)
    from . import assembly_snapshot
    assembly_snapshot.publish_prepare(t,s)


def resolve(s,intents,maximum=8):
    if not isinstance(intents,list) or not 1<=len(intents)<=maximum:raise core.StopBatch('CONNECTION_INTENT_INVALID','本次连接目标上限为'+str(maximum)+'项。')
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


def select_scope(engine,t,row):
    s=engine.sessions[t['task_id']]
    s.root_connection_survey=s.connection_survey
    core.write(s.folder/'根装配原始调查.json',s.connection_survey)
    selected=s.call('_select_connection_layer',model_id=s.model,instance=row['instance'])
    core.write(s.folder/'内部装配范围绑定.json',selected)
    checkpoint=s.call('create_model_checkpoint',model_id=s.model)
    # Commit checkpoint and comparison frame together, before geometry
    # discovery can fail. Root and inner snapshots are never mixed.
    selected_inspection=s.call('inspect_model',model_id=s.model,detail_level='full')
    s.checkpoint=checkpoint['checkpoint_id'];s.initial_inspection=selected_inspection;s.import_restored=False
    selected={**selected,'scope_import_checkpoint_id':s.checkpoint,'scope_checkpoint_includes_all_import_files':True}
    s.selected_assembly_layer=selected;core.write(s.folder/'内部装配范围绑定.json',selected)
    core.write(s.folder/'内部装配导入检查点.json',checkpoint)
    t['selected_assembly_layer']=selected;engine.save(t)
    publish_review(engine,t,discover(s))
    t['next_action']['instruction']='当前检查范围为'+selected['selected_instance']+'的内部文档；AI使用本轮内部组件名称规划，此文档以外的层尚未补齐认证。'+t['next_action']['instruction']
    engine.save(t)


def propose(engine,t,intents,rigid_groups=None,release_fixed_components=None,completion_scope='declared',assembly_scope_hint='',auto_plan=False,group_seeds=None,
            verification_mode='independent_joint_trials',moving_hint='',reference_hint='',output_hints=None,alignment_mode='strict',initial_translation_limit_mm=.001):
    driven=verification_mode=='driven_loop'
    if verification_mode not in {'independent_joint_trials','driven_loop'}:raise core.StopBatch('CONNECTION_INTENT_INVALID','未知验证方式。')
    if driven:
        if alignment_mode=='strict' and initial_translation_limit_mm!=.001:raise core.StopBatch('CONNECTION_INTENT_INVALID','strict不使用初态平移预算，未静默忽略。')
        if (completion_scope!='whole_assembly' or auto_plan or group_seeds is not None or assembly_scope_hint or release_fixed_components is not None
                or not moving_hint or not reference_hint or not isinstance(output_hints,list) or not 1<=len(output_hints)<=16
                or alignment_mode not in {'strict','small_translation'}):
            raise core.StopBatch('CONNECTION_INTENT_INVALID','整机闭环须明确主直线输入、接地参考及输出，用完整目标规划；不混用层选择、自动草案或解除固定。')
    elif moving_hint or reference_hint or output_hints is not None or alignment_mode!='strict' or initial_translation_limit_mm!=.001:
        raise core.StopBatch('CONNECTION_INTENT_INVALID','主驱动、输出及微量初态调整仅用于显式driven_loop整机验证。')
    if type(auto_plan) is not bool:raise core.StopBatch('CONNECTION_INTENT_INVALID','auto_plan须为布尔值。')
    if completion_scope not in {'declared','whole_assembly'}:raise core.StopBatch('CONNECTION_INTENT_INVALID','completion_scope须为declared或whole_assembly。')
    whole=completion_scope=='whole_assembly'
    engine._require_session(t['task_id'])
    if t['phase'] not in {'constraint_review_ready','awaiting_confirmation'}:raise core.StopBatch('TASK_NOT_READY_FOR_PLAN')
    s=engine.sessions[t['task_id']]
    loop_profile=None
    if driven:
        selected=[]
        for label,hint in [('primary_input',moving_hint),('grounded_reference',reference_hint)]+[('output',h) for h in output_hints]:
            if not isinstance(hint,str) or not hint.strip():raise core.StopBatch('CONNECTION_INTENT_INVALID','主驱动和输出必须使用组件名称。')
            matches=matching_components(s.connection_survey['components'],hint,None)
            if len(matches)!=1:return {'task_id':t['task_id'],'needs_mechanical_clarification':True,'field':label,'name_hint':hint,
                'choices':mechanical_choices(s.connection_survey['components'],hint,None),'write_dispatched':False,'confirmation_token_created':False}
            selected.append(matches[0]['component_id'])
        loop_profile={'primary':{'component_a':selected[0],'component_b':selected[1],'kind':'prismatic'},'outputs':selected[2:]}
    if group_seeds is not None:
        if intents is not None or rigid_groups is not None or release_fixed_components is not None or completion_scope!='declared' or assembly_scope_hint or auto_plan:
            raise core.StopBatch('CONNECTION_INTENT_INVALID','group_seeds仅只读推荐归属，不混用写入目标、范围选择或自动预演。')
        from .constraint_inventory import require_write_scope
        require_write_scope(t)
        from .. import group_review
        if not isinstance(group_seeds,dict):raise core.StopBatch('CONNECTION_INTENT_INVALID','group_seeds须为命名运动组到代表件名称列表。')
        normalized={}
        for label,names in group_seeds.items():
            if not isinstance(names,list):raise core.StopBatch('CONNECTION_INTENT_INVALID','每组代表件须为名称列表。')
            normalized[label]=[]
            for name in names:
                if not isinstance(name,str) or not name.strip():raise core.StopBatch('CONNECTION_INTENT_INVALID','代表件名称不能为空。')
                found=matching_components(s.connection_survey['components'],name,None)
                if len(found)!=1:return {'task_id':t['task_id'],'needs_mechanical_clarification':True,'group':label,'name_hint':name,
                    'choices':mechanical_choices(s.connection_survey['components'],name,None),'write_dispatched':False,'confirmation_token_created':False,
                    'question':'请用用途或实例后缀澄清这个组的代表件；AI不要求实体ID。'}
                normalized[label].append(found[0]['instance'])
        try:result=group_review.recommend(s.connection_survey,normalized)
        except (ValueError,TypeError) as error:raise core.StopBatch('CONNECTION_INTENT_INVALID','运动组推荐输入或范围未通过核对。',{'reason':str(error),'cad_dispatched':False}) from error
        path=s.folder/('装配分组推荐-'+uuid.uuid4().hex+'.json');core.write(path,result)
        t['group_recommendation']={**result,'evidence_path':str(path),'observation_scope':'prepare_snapshot_not_current_native_preflight'};engine.save(t)
        return {'task_id':t['task_id'],'group_recommendation':t['group_recommendation'],'write_dispatched':False,'confirmation_token_created':False,
            'pending_plan_preserved':t['phase']=='awaiting_confirmation','instruction':result['instruction']}
    if auto_plan:
        if (t.get('connection_review') or {}).get('write_scope_allowed') is False:
            from .constraint_inventory import require_write_scope
            require_write_scope(t)
        if rigid_groups is not None or release_fixed_components is not None or completion_scope!='declared' or assembly_scope_hint or t['phase']!='constraint_review_ready':
            raise core.StopBatch('CONNECTION_INTENT_INVALID','自动预演须从新体检开始；可用connection_intent补充局部用途，不混用分组、解除固定、范围或替换待确认方案。')
        assessment=t.get('assembly_assessment') or {}
        if intents is not None:
            from .. import assembly_assessment
            overrides,question=resolve(s,intents,assembly_assessment.MAX_AUTOMATIC_GOALS)
            if question:return {'task_id':t['task_id'],**question}
            try:assessment=assembly_assessment.clarify(s.connection_survey,assessment,overrides)
            except (ValueError,TypeError) as error:
                raise core.StopBatch('CONNECTION_INTENT_INVALID','局部用途与当前装配证据不兼容；未派发原生预演。',{'reason':str(error),'write_dispatched':False}) from error
            t['clarified_assembly_assessment']=assessment;engine.save(t)
            core.write(s.folder/'局部用途与整机目标合并.json',assessment)
        if not assessment.get('automatic_plan_available'):
            return {'task_id':t['task_id'],'needs_mechanical_clarification':bool(assessment.get('mechanical_question_groups')),
                    'needs_scope_review':bool(assessment.get('proposal_review_issues') or assessment.get('write_scope_blockers')),'assembly_assessment':assessment,
                    'write_dispatched':False,'confirmation_token_created':False,'instruction':'AI集中解释未覆盖组件及阻断；有明确用途后填写普通连接目标，不反复调用auto_plan。'}
        selected=assessment['suggested_plan_arguments'];intents=selected['connection_intent'];completion_scope=selected['completion_scope'];whole=completion_scope=='whole_assembly'
        t['automatic_mechanical_goal_proposal']=True
    elif intents is not None or rigid_groups is not None or release_fixed_components is not None:
        t.pop('automatic_mechanical_goal_proposal',None)
    if (t.get('connection_review') or {}).get('write_scope_allowed') is False:
        if intents is None and rigid_groups is None and release_fixed_components is None and completion_scope=='declared' and not assembly_scope_hint:
            return {'task_id':t['task_id'],'readonly_structure':True,'constraint_structure':t['constraint_structure'],
                    'connection_review':t['connection_review'],'write_dispatched':False,'confirmation_token_created':False}
        from .constraint_inventory import require_write_scope
        require_write_scope(t)
    if assembly_scope_hint:
        from ..connection_layers import resolve as resolve_layer
        if getattr(s,'selected_assembly_layer',None):
            if assembly_scope_hint!=s.selected_assembly_layer['selected_instance']:
                raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED','当前内部事务范围已绑定；结束本任务后再检查其他装配层。')
        else:
            if intents is not None or rigid_groups is not None or release_fixed_components is not None or completion_scope!='declared':
                raise core.StopBatch('CONNECTION_INTENT_INVALID','先只传assembly_scope_hint选择范围并读取内部草案，再用内部组件名称形成方案；未静默忽略连接输入。')
            try:row,question=resolve_layer(s.assembly_layers,assembly_scope_hint)
            except ValueError as error:raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED','装配层范围未通过校验。',{'reason':str(error),'write_dispatched':False}) from error
            if question:return {'task_id':t['task_id'],**question}
            if t['phase']=='awaiting_confirmation':
                t.pop('plan_token',None);t.pop('proposal',None);t.update(phase='constraint_review_ready',plan_token_revoked=True);engine.save(t)
            return engine._submit(t,'selecting_assembly_layer',lambda:select_scope(engine,t,row))
    if intents is None and rigid_groups is None and release_fixed_components is None:return {'task_id':t['task_id'],'needs_connection_intent':True,
        'assembly_assessment':t.get('assembly_assessment'),
        'connection_draft':getattr(s,'connection_draft',None) or recommendations.draft(s.connection_survey),
        'connection_review':t['connection_review'],'assembly_overview':t.get('assembly_overview'),'assembly_layers':t.get('assembly_layers'),'selected_assembly_layer':t.get('selected_assembly_layer'),'write_dispatched':False,
        'instruction':'AI读取connection_draft，用候选connection_intent及推荐依据形成整组方案；已有机械目标可直接选择，真正歧义集中询问。草案不是原生预演或执行授权，实际plan仍须传具体connection_intent。现有方案不因只读草案查询自动撤销。'}
    if t['phase']=='awaiting_confirmation':
        t['previous_plan_id']=(t.get('proposal') or {}).get('plan_id')
        t.pop('plan_token',None);t.pop('proposal',None)
        t.update(phase='constraint_review_ready',plan_token_revoked=True);engine.save(t)
    goals,question=resolve(s,intents,128 if whole else 8) if intents is not None else ([],None)
    if question:return {'task_id':t['task_id'],**question}
    expansion=None
    try:
        planning_survey=s.connection_survey
        if rigid_groups is not None or release_fixed_components is not None:
            expansion=connection_groups.expand(planning_survey,goals,rigid_groups,release_fixed_components,whole_assembly=whole)
            core.write(s.folder/'整组目标展开.json',{k:v for k,v in expansion.items() if k!='planning_survey'})
            if expansion['status']!='group_expanded':return {'task_id':t['task_id'],**{k:v for k,v in expansion.items() if k!='planning_survey'},'confirmation_token_created':False}
            goals=expansion['goals'];planning_survey=expansion['planning_survey']
        if whole:
            goals.sort(key=lambda g:g['kind']!='rigid')
            coverage=assembly_overview.coverage(s.connection_survey,goals,(expansion or {}).get('group_bindings',[]))
            core.write(s.folder/'整装配目标覆盖.json',coverage)
            if not coverage['all_components_have_declared_targets']:
                return {'task_id':t['task_id'],'status':'assembly_goal_coverage_required','component_coverage':coverage,
                        'write_dispatched':False,'confirmation_token_created':False,'instruction':'整装配方案仍有未声明组件。AI结合用户目标归组或集中澄清，不把未分配件默认静止，也不部分提交。'}
        initialization=None
        if alignment_mode=='small_translation':
            from .. import initial_translation
            planning_survey,initialization=initial_translation.propose(planning_survey,goals,initial_translation_limit_mm)
            core.write(s.folder/'微量初态平移预测.json',initialization)
        proposal=joints.plan(planning_survey,goals,whole_assembly=whole,driven_loop=loop_profile)
        if initialization is not None:proposal['initial_translation']=initialization
        if any(g.get('coupled_verification_only') for g in proposal.get('goals',[])) and (expansion is not None or whole):
            raise ValueError('coupled_verification_cannot_mix_supplements')
        if expansion:
            proposal.update(group_bindings=expansion['group_bindings'],rigid_groups=expansion['rigid_groups'],
                pattern_scope_reviews=expansion.get('pattern_scope_reviews',[]),
                fixed_state_changes=expansion['fixed_state_changes'],skipped_existing_pairs=expansion['skipped_existing_pairs'],
                unassigned_components=expansion['unassigned_components'],mechanical_ownership_of_unassigned_components_inferred=False)
    except (ValueError,TypeError) as error:
        reason=str(error)
        code='CONNECTION_GOAL_CONFLICT' if reason in {'existing_constraints_conflict_with_declared_motion','existing_indirect_constraints_conflict_with_declared_motion','proposed_group_constraints_conflict_with_declared_motion','mobile_joint_inside_declared_rigid_group','both_components_fixed_no_floating_target_for_native_trial','native_fully_constrained_mobile_goal_requires_review','native_full_constraint_conflicts_with_supported_missing_rank'} else 'CONNECTION_SCOPE_UNSUPPORTED' if reason in {'coupled_verification_cannot_mix_supplements','native_inventory_or_health_requires_review','pattern_group_requires_seed_scope_review','pattern_member_fixed_release_unsupported','fixed_release_requires_an_existing_fixed_reference_to_remain'} else 'CONNECTION_INTENT_INVALID'
        explanation={'native_fully_constrained_mobile_goal_requires_review':'局部运动线索与原生全约束观察冲突；先核对装配模型作用域及整条约束链，未解固定或补配合。',
            'native_full_constraint_conflicts_with_supported_missing_rank':'原生报告已全约束，但受支持局部模型仍有缺口；未知约束不能当作不存在，未继续补配合。',
            'existing_constraints_conflict_with_declared_motion':'原配合与目标运动冲突；未自动删除、压缩或解除固定。',
            'existing_indirect_constraints_conflict_with_declared_motion':'受支持的间接约束链与目标运动冲突；AI核对整装配约束图，不把直接配合较少当成缺项，不自动删除旧约束。',
            'proposed_group_constraints_conflict_with_declared_motion':'整组补充约束会限制已声明的运动；方案未派发，AI核对分组或未解除的固定，不部分提交。',
            'both_components_fixed_no_floating_target_for_native_trial':'目标两件均固定；先澄清机械目标，未自动解除固定。'}.get(reason,'连接目标或当前受支持范围未通过校验；AI核对诊断，不重试写入。')
        if reason=='pattern_group_requires_seed_scope_review':explanation='局部阵列的种子链、原生关系或同组范围未完整认证。AI先核对诊断中的种子归属并补全同用途组；不让用户逐个填写实体，不对派生件重试写入。'
        raise core.StopBatch(code,explanation,{'reason':reason,'cad_dispatched':False,'write_dispatched':False,
            'native_state_review_path':str(s.folder/'通用配合体检.json'),
            'constraint_graph_path':str(s.folder/'整装配约束图.json'),
            'component_state_observations':[{'instance':c['instance'],'fixed_component':c.get('fixed_component'),'constraint_state':c.get('constraint_state')}
                for c in s.connection_survey['components'] if any(c['component_id'] in (g['component_a'],g['component_b']) for g in goals)],
            'nonlinear_constraints_observed':s.connection_survey.get('nonlinear_constraints',[]),
            'group_intent_diagnostics':getattr(error,'diagnostics',None),
            'observation_scope':'whole_inventory_non_equality_constraints_are_not_proven_root_causes',
            'original_mates_or_fixed_flags_automatically_changed':False}) from error
    if whole and proposal['status']=='plan_ready':
        proposal['component_coverage']=coverage
        try:transaction=connection_batches.prepare(proposal)
        except ValueError as error:raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED','整装配事务预算或完整性未通过，未部分提交。',{'reason':str(error),'write_dispatched':False}) from error
        core.write(s.folder/'整装配冻结批次.json',transaction)
    proposal['selected_assembly_layer']=getattr(s,'selected_assembly_layer',None)
    core.write(s.folder/'通用连接补齐规划.json',proposal)
    if proposal['status']!='plan_ready':return {'task_id':t['task_id'],**proposal,
        'instruction':'仅当前已支持几何范围；AI解释缺失参考或轴线歧义，未部分提交配合。'}
    def operation():
        from . import coupled_motion,mate_motion
        loop=proposal.get('driven_loop_review')
        if loop:
            primary=proposal['goals'][loop['primary_goal_index']]
            primary['driven_loop_driver']=coupled_motion.choose(primary,mate_motion.component_geometry(s,primary['component_a'],'planar_normal'))
        for goal in proposal['goals']:
            if goal.get('coupled_verification_only'):
                goal['coupled_motion_driver']=coupled_motion.choose(goal,mate_motion.component_geometry(s,goal['component_a'],'planar_normal'))
        core.write(s.folder/'通用连接补齐规划.json',proposal)
        payload=connection_batches.request(transaction,0,s.connection_survey['reference_state_signature']) if whole else {**proposal,'reference_state_signature':s.connection_survey['reference_state_signature']}
        native=s.call('_preview_assembly_connections',model_id=s.model,proposal_json=json.dumps(payload,ensure_ascii=False))
        from .. import assembly_assessment
        assessment=assembly_assessment.for_plan(s.connection_survey,proposal);assessment['native_preview_completed']=True
        t['assembly_assessment']=assessment;core.write(s.folder/'具体目标逐组件结论.json',assessment)
        if whole:t['connection_transaction']=transaction
        else:t.pop('connection_transaction',None)
        t.update(phase='awaiting_confirmation',plan_token=uuid.uuid4().hex,plan_token_revoked=False,proposal={**native,
            'actions':proposal['actions'],'goals':proposal['goals'],'expected_added_mates':len(proposal['actions']),
            'fixed_state_changes':proposal.get('fixed_state_changes',[]),'completion_scope':completion_scope,
            'verification_mode':verification_mode,'driven_loop_review':proposal.get('driven_loop_review'),'initial_translation':proposal.get('initial_translation'),
            'construction_review':proposal.get('construction_review'),
            'linear_allowed_trial_strategy':'temporary_native_motion_study_0_1mm_per_s_1s_30fps_then_verified_checkpoint_restore' if any(g.get('coupled_verification_only') for g in proposal['goals']) else native.get('linear_allowed_trial_strategy'),
            'batches':transaction['batches'] if whole else None,'component_coverage':proposal.get('component_coverage'),
            'all_or_restore_import_checkpoint':whole,'omitted_native_feature_ids':proposal['omitted_native_feature_ids'],
            'group_bindings':proposal.get('group_bindings',[]),'rigid_groups':proposal.get('rigid_groups',[]),
            'pattern_scope_reviews':proposal.get('pattern_scope_reviews',[]),
            'skipped_existing_pairs':proposal.get('skipped_existing_pairs',[]),'unassigned_components':proposal.get('unassigned_components',[]),
            'scope':'declared_basic_joints_small_trials_only_not_global_DOF_or_full_travel',
            'finish_policy':'restore_import_checkpoint_by_default'},
            next_action={'tool':'execute_mechanism_task','arguments':{'task_id':t['task_id']},
                'instruction':('本方案仅验证已有丝杆联动：新增0项，不解除固定；保留全约束原生观测。正反向各创建临时线性马达，0.1mm/s、1秒、30fps，逐帧核对丝杆关系、限位和接地参考并恢复移除；不添加临时距离配合。' if any(g.get('coupled_verification_only') for g in proposal['goals']) else '允许方向可使用临时距离或角度约束驱动，逐次恢复成果检查点移除。')+'解释连接目标、自动采用轴线、逐项新增配合、保留的旧约束及未知项、仅副本初态准备和有界试验范围。禁止方向用装配移动求解。取得当前具体方案授权后一次执行。未证明全行程、受力或接触；默认恢复原导入状态。'})
        if t.get('automatic_mechanical_goal_proposal'):t['next_action']['instruction']='这些连接用途由AI提出，尚未证明设计意图。先向用户集中确认各运动组应保留的运动及具体改动，再执行。'+t['next_action']['instruction']
        if driven:
            t['proposal']['verification']={'method':'native_primary_driven_motion_both_signs_all_components_all_declared_joints_and_outputs',
                'duration_s_per_direction':1,'output_fps':30,'input_translation_m_per_direction':.0001,
                'independent_joint_actuation_certified':False,'whole_travel_certified':False}
            t['next_action']['instruction']='解释完整连接及主直线驱动、全部输出；闭环局部铰接不承诺能独立转动。执行后须正反各0.1毫米临时Motion，逐帧核对全部组件、全部关节、接地件静止和各输出确实运动，逐次恢复。未证明全行程或接触受力。'
            if (proposal.get('initial_translation') or {}).get('requires_alignment_confirmation'):
                t['next_action']['instruction']+='方案含明确的零配合初态微量平移，无旋转；说明最大预测位移及预算，须另行取得alignment_confirmed授权。默认恢复原导入状态。'
        from . import assembly_snapshot
        assembly_snapshot.publish_plan(t,s)
    return engine._submit(t,'planning',operation)


def execute(engine,t,token,confirmed,scope_confirmed,alignment_confirmed):
    from .constraint_inventory import require_write_scope
    require_write_scope(t)
    engine._require_session(t['task_id'])
    if confirmed is not True or scope_confirmed is not True:raise core.StopBatch('CONFIRMATION_REQUIRED','须确认补齐和有限位移验证的具体范围。')
    task_execution.require_plan_token(t,token)
    init=t['proposal'].get('initial_translation') or {};needs_alignment=init.get('requires_alignment_confirmation') is True
    if needs_alignment and alignment_confirmed is not True:raise core.StopBatch('CONFIRMATION_REQUIRED','须另行确认该冻结方案内有界微量初态平移。',{'separate_alignment_confirmation_required':True,'constraint_write_dispatched':False})
    if not needs_alignment and alignment_confirmed is not False:raise core.StopBatch('CONNECTION_INTENT_INVALID','当前方案未包含待确认的初态调整。')
    t['execution_consumed']=True;t['confirmation']={'confirmed':True,'scope_confirmed':True,'alignment_confirmed':alignment_confirmed};engine.save(t)
    def perform():
        s=engine.sessions[t['task_id']];s.import_restored=False
        if t.get('connection_transaction'):
            from .connection_batch_task import apply
            applied=apply(engine,t,s)
        else:applied=s.call('_apply_assembly_connections',plan_id=t['proposal']['plan_id'],confirmed=True)
        core.write(s.folder/'通用连接补齐成果.json',applied);s.committed=True;s.capture_applied_result()
        expected_fixed={c['component_id']:c['fixed_component'] for c in s.connection_survey['components']}
        for change in t['proposal'].get('fixed_state_changes',[]):
            if expected_fixed.get(change['component_id']) is not True or change['before'] is not True or change['after'] is not False:
                raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','固定状态变更与明确方案不符。')
            expected_fixed[change['component_id']]=False
        actual_fixed={c['component_id']:c['fixed_component'] for c in s.result_inspection['components']}
        fixed_audit={'passed':actual_fixed==expected_fixed,'expected':expected_fixed,'actual':actual_fixed,'changes':t['proposal'].get('fixed_state_changes',[])}
        core.write(s.folder/'固定状态变更核对.json',fixed_audit)
        if not fixed_audit['passed']:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','实际固定标志超出确认的解除固定名单。',fixed_audit)
        poses={c['component_id']:c['transform'] for c in s.result_inspection['components']}
        from .. import coupled_connections
        coupled_bounds={i:coupled_connections.bind(goal['coupling_evidence'],poses) for i,goal in enumerate(t['proposal']['goals']) if goal.get('coupled_verification_only')}
        if coupled_bounds and (t['proposal'].get('actions') or t['proposal'].get('fixed_state_changes')):raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED','既有联动受限验证不允许持久配合或固定状态写入。')
        coupled_signs={}
        if coupled_bounds:core.write(s.folder/'联动有界审计绑定.json',coupled_bounds)
        try:bounds=[trials.bind(goal,poses) for goal in t['proposal']['goals']]
        except (ValueError,KeyError,TypeError) as error:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','初态材料参考绑定未通过。',{'reason':str(error)}) from error
        hierarchy=assembly_hierarchy.analyze(s.result_inspection['components']);expected_parents=hierarchy['parents'] if hierarchy['native_observed'] else None
        declared_count=len(bounds);declared_pairs={frozenset((g['component_a'],g['component_b'])) for g in t['proposal']['goals']}
        for binding in t['proposal'].get('group_bindings',[]):
            pair=frozenset((binding['component_a'],binding['component_b']))
            if pair not in declared_pairs:bounds.append(trials.bind(binding,poses));declared_pairs.add(pair)
        group_extra_count=len(bounds)-declared_count
        for binding in hierarchy['rigid_child_pairs']:
            pair=frozenset((binding['component_a'],binding['component_b']))
            if pair not in declared_pairs:bounds.append(trials.bind(binding,poses));declared_pairs.add(pair)
        hierarchy_extra_count=len(bounds)-declared_count-group_extra_count
        observed=joints.review({'components':s.result_inspection['components'],'mates':s.result_inspection['mates'],'inventory_complete':True})
        for row in observed['connections']:
            if row['recommended_joint_type'] not in joints.KINDS or frozenset((row['component_a'],row['component_b'])) in declared_pairs:continue
            old_goal={**row,'kind':row['recommended_joint_type'],'reference_point_global_m':row.get('axis_point_global_m')}
            bounds.append(trials.bind(old_goal,poses))
        core.write(s.folder/'已有连接运动保留绑定.json',bounds[declared_count:])
        audits=[];passed=True;driven_review=t['proposal'].get('driven_loop_review')
        if driven_review:
            from . import driven_loop_motion
            audits=driven_loop_motion.run(s,t['proposal']['goals'],poses,bounds,driven_review)
            passed=len(audits)==2 and all(a['passed'] for a in audits)
        for i,goal in enumerate(t['proposal']['goals'] if not driven_review else []):
            for trial in trials.trials(goal,poses):
                if not passed:break
                if i in coupled_bounds and trial['allowed']:
                    from . import coupled_motion
                    audit=coupled_motion.run(s,goal,trial,poses,bounds,i,coupled_bounds[i])
                    sign=audit['observed_signed_relation'];previous=coupled_signs.setdefault(i,sign)
                    audit['signed_relation_consistent']=previous==sign;audit['passed']=audit['passed'] and previous==sign
                    audits.append(audit);core.write(s.folder/'基础运动副有界验证.json',audits);passed=audit['passed']
                    continue
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
                    audit=trials.audit(evidence,bounds,i,trial,poses,expected_parents)
                    if i in coupled_bounds:
                        coupled=coupled_connections.audit(coupled_bounds[i],evidence['after']);sign=coupled['observed_signed_relation']
                        if sign is not None:
                            previous=coupled_signs.setdefault(i,sign);coupled['signed_relation_consistent']=previous==sign;coupled['passed']=coupled['passed'] and previous==sign
                        audit['coupled_motion_checks']=coupled;audit['passed']=audit['passed'] and coupled['passed']
                except (ValueError,KeyError,TypeError) as error:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','试验变换或证据范围无效。',{'reason':str(error),'artifact':receipt}) from error
                audits.append({**audit,'request_target_binding':binding,'artifact':receipt})
                if getattr(s,'selected_assembly_layer',None):
                    layer_audit=s.call('_verify_connection_layer',model_id=s.model)
                    core.write(s.folder/('内部试验总装守卫-'+str(len(audits))+'.json'),layer_audit)
                core.write(s.folder/'基础运动副有界验证.json',audits);passed=audit['passed']
        proof={'declared_scope_passed':passed,'method':'native_primary_driven_closed_loop_small_motion' if driven_review else 'native_motion_and_assembly_solver_small_trials' if coupled_bounds else 'native_assembly_solver_small_pose_trials',
            'driven_loop_review':driven_review,'initial_translation':t['proposal'].get('initial_translation'),
            'independent_joint_actuation_certified':False,
            'whole_assembly_declared_targets_passed':passed and t['proposal'].get('completion_scope')=='whole_assembly',
            'component_coverage':t['proposal'].get('component_coverage'),'batch_count':(t.get('connection_transaction') or {}).get('batch_count',1),
            'fixed_state_changes_verified':True,'fixed_state_changes':t['proposal'].get('fixed_state_changes',[]),
            'connection_count':declared_count,'existing_supported_connection_checks':len(bounds)-declared_count-group_extra_count-hierarchy_extra_count,
            'native_rigid_subassembly_binding_checks':hierarchy_extra_count,
            'additional_group_binding_checks':group_extra_count,'declared_group_bindings_checked_per_trial':len(t['proposal'].get('group_bindings',[])),
            'declared_pattern_bindings_checked_per_trial':len(t['proposal'].get('pattern_scope_reviews',[])),
            'existing_connection_scope':'supported_native_pair_relations_only_not_unknown_constraints_or_global_DOF',
            'omitted_native_feature_ids':observed['omitted_native_feature_ids'],
            'coupled_verification_only':bool(coupled_bounds),'persistent_mates_added_for_coupled_review':0 if coupled_bounds else None,
            'completed_trials':len(audits),'trials':audits,'native_motion_study_solved':bool(coupled_bounds or driven_review),
            'global_DOF_certified':False,'whole_travel_certified':False,'contact_or_force_validated':False,
            'position_tolerance_m':trials.POSITION_TOLERANCE_M,'angle_tolerance_rad':trials.ANGLE_TOLERANCE_RAD}
        if passed and getattr(s,'selected_assembly_layer',None):
            guard=s.call('_verify_connection_layer',model_id=s.model,rebuild_root=True)
            proof['assembly_layer_guard']=guard;proof['selected_assembly_layer']=s.selected_assembly_layer
            s.capture_applied_result()
            core.write(s.folder/'内部补齐总装守卫.json',guard)
        t['verification']=proof;core.write(s.folder/'通用配合验证结论.json',proof)
        if not passed:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','补齐或有界运动验证未通过，停止后续试验；默认收尾恢复导入检查点。',proof)
        t.update(phase='verified',next_action={'tool':'finish_mechanism_task','arguments':{'task_id':t['task_id']},
            'instruction':'报告本次声明连接的小位移验证、旧约束和固定状态保持及每次恢复；不声称全机构自由度或全行程通过。默认恢复导入检查点并正常退出；只有用户明确要求才保留已验证成果副本。'})
    def operation():
        try:return perform()
        except Exception as error:
            if t.get('connection_transaction'):
                from .connection_batch_task import restore_failed_transaction
                restore_failed_transaction(engine.sessions[t['task_id']],t,error)
            raise
    return engine._submit(t,'executing',operation)
