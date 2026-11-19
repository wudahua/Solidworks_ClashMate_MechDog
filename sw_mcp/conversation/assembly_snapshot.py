"""Task-bound compact observations and plan review. No Bridge or CAD calls."""
import copy,hashlib,json,re,threading
from collections import OrderedDict
from pathlib import Path
from . import core

PAGE_BYTES=8000
PAGE_ROWS=16
EXPANDED_PAGE_BYTES=14000
RECOMMENDED_PAGE_ROWS=50
KINDS=('components','candidates','goals','questions','geometry','actions','groups','fixed_changes','mechanical_groups','mate_changes','mates','mirror_dependencies','redundancy_candidates')
_READ_CACHE=OrderedDict()
_READ_LOCK=threading.RLock()


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(value):return hashlib.sha256(encoded(value)).hexdigest()
def page_bytes(value):return len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))


def record_native_inventory(task,session,captured):
    """Keep actual result rows distinct from old prepare and expected additions."""
    inspection=getattr(session,'result_inspection',None) or (captured or {}).get('inspection') or {}
    if 'mates' not in inspection:return
    import time
    task['current_assembly_observation']={'mate_count':len(inspection['mates']),
        'component_count':len(inspection.get('components',[])),'observed_at':time.time(),
        'observation_stage':'after_apply_before_motion_trials','source':'native_result_checkpoint_inspection',
        'mate_count_scope':'returned_native_full_inspection_rows','model_id':session.model,
        'checkpoint_id':(captured or {}).get('checkpoint_id'),
        'historical_after_finish':False,'live_query_performed_by_get':False}


def _page_offsets(sizes,row_limit,byte_limit):
    offsets=[0]
    used=2
    for index,size in enumerate(sizes):
        if size+2>byte_limit:raise ValueError('snapshot_row_exceeds_page_budget')
        if index>offsets[-1] and (index-offsets[-1]>=row_limit or used+size+2>byte_limit):
            offsets.append(index)
            used=2
        used+=size+(2 if index>offsets[-1] else 0)
    if sizes:offsets.append(len(sizes))
    return offsets


def _read_snapshot(path,entry,task,folder):
    # Verify file bytes on *every* read. Only JSON parsing, canonical binding
    # validation and byte-budget boundaries are cached, never a live CAD state.
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=entry['file_sha256']:raise ValueError('snapshot_bytes_changed')
    key=(str(path),entry['file_sha256'],task['task_id'],str(folder))
    with _READ_LOCK:
        cached=_READ_CACHE.get(key)
        if cached is not None:_READ_CACHE.move_to_end(key)
    if cached is None:
        snap=json.loads(data.decode('utf-8-sig'))
        if snap['task_id']!=task['task_id'] or digest({'binding':str(folder),'snapshot':snap})!=entry['snapshot_id']:
            raise ValueError('snapshot_binding_changed')
        sizes={kind:[page_bytes(row) for row in rows] for kind,rows in snap['collections'].items()}
        legacy_limit=PAGE_BYTES-2000
        cached=(snap,sizes,{kind:_page_offsets(values,PAGE_ROWS,legacy_limit)
                            for kind,values in sizes.items() if max(values,default=0)+2<=legacy_limit})
        with _READ_LOCK:
            _READ_CACHE[key]=cached
            while len(_READ_CACHE)>2:_READ_CACHE.popitem(last=False)
    snap,sizes,default_boundaries=cached
    for bound in [{'path':snap['source_file'],'sha256':snap['source_sha256']},*snap.get('additional_sources',[])]:
        p=core.no_links(folder/bound['path']);p.relative_to(folder)
        if core.digest(p)!=bound['sha256']:raise ValueError('snapshot_source_changed')
    return snap,sizes,default_boundaries


def reference(row):
    out={k:row[k] for k in ('entity_id','reference_kind','kind','axis_global','reference_point_global_m',
         'cylinder_radius_m','area_m2','reference_owner_instance') if k in row}
    if row.get('native_reference'):out['native_reference_sha256']=digest(row['native_reference'])
    return out


def _persist(task,session,stage,collections,source,additional_sources=None):
    folder=core.no_links(Path(task['directory']))
    source=core.no_links(source);source.relative_to(folder)
    snapshot={'schema_version':1,'task_id':task['task_id'],'model_id':session.model,'stage':stage,
              'source_file':str(source.relative_to(folder)),'source_sha256':core.digest(source),
              'additional_sources':[{'path':str(p.relative_to(folder)),'sha256':core.digest(p)} for p in (additional_sources or [])],
              'collections':collections,'scope':'frozen_observation_not_current_CAD_or_execution_authority'}
    sid=digest({'binding':str(folder),'snapshot':snapshot})
    path=folder/'session'/('装配'+('调查' if stage=='prepare' else '方案复核')+'快照-'+sid[:16]+'.json')
    core.write(path,snapshot)
    entry={'snapshot_id':sid,'path':str(path.relative_to(folder)),'file_sha256':core.digest(path),
           'counts':{k:len(v) for k,v in collections.items()},'stage':stage,
           'queries':[{'tool':'get_mechanism_task','arguments':{'task_id':task['task_id'],'snapshot_cursor':sid+':'+k+':0',
                       **({'snapshot_page_size':RECOMMENDED_PAGE_ROWS} if len(v)>PAGE_ROWS or page_bytes(v)>PAGE_BYTES-2000 else {})}}
                      for k,v in collections.items() if v],
           'plan_token':task.get('plan_token') if stage=='plan' else None}
    task['assembly_'+stage+'_snapshot']=entry
    return entry


def publish_prepare(task,session):
    survey=session.connection_survey;review=task.get('connection_review') or {};assessment=task.get('assembly_assessment') or {}
    readonly=review.get('write_scope_allowed') is False
    source=session.folder/'只读结构完整原生检查.json' if readonly else getattr(session,'connection_survey_path',session.folder/'通用配合原生调查.json')
    statuses={c['component_id']:c for c in assessment.get('components',[])}
    components=[];geometry=[]
    for c in survey.get('components',[]):
        components.append({**{k:c.get(k) for k in ('component_id','instance','fixed_component','parent_component_id','constraint_state','geometry_complete',
             'parent_document_fixed_component','fixed_flag_observation_scope','document_type','subassembly','subassembly_solving','configuration')},
             'classification':statuses.get(c['component_id'],{}).get('status'),
             'origin_world_m':c.get('transform',[])[9:12],
             'captured_cylinders':len(c.get('cylinders',[])),'captured_planes':len(c.get('planes',[]))})
        for kind in ('cylinders','planes','completion_planes'):
            for i,row in enumerate(c.get(kind,[])):
                geometry.append({'instance':c['instance'],'component_id':c['component_id'],'collection':kind,
                                 'reference_index':i,**reference(row)})
    analytic=None;additional=[]
    metadata=survey.get('geometry_snapshot')
    if metadata is not None and not readonly:
        try:
            artifact=core.no_links(metadata['path']);artifact.relative_to(core.no_links(session.runtime))
            if core.digest(artifact)!=metadata['sha256']:raise ValueError('native_geometry_artifact_hash_changed')
            analytic=core.read(artifact)
            if (analytic.get('model_id')!=session.model or analytic.get('reference_state_signature')!=survey.get('reference_state_signature')
                    or len(analytic.get('rows',[]))!=metadata.get('row_count')
                    or len(analytic['rows'])>20000):raise ValueError('native_geometry_binding_changed')
            number=len(task.get('connection_batch_history',[]))+1
            saved=session.folder/('原生批量几何观察.json' if number==1 else '原生批量几何观察-第'+str(number)+'批.json')
            core.write(saved,analytic);additional.append(saved)
            # Raw persistent references remain only in the original native survey.
            geometry=[{**r,'collection':'analytic_faces'} for r in analytic['rows']]
            geometry += [{'instance':c['instance'],'component_id':c['component_id'],'collection':'completion_planes',
                          'reference_index':i,**reference(row)} for c in survey['components'] for i,row in enumerate(c.get('completion_planes',[]))]
        except (OSError,ValueError,KeyError,TypeError) as error:
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','原生批量几何工件不属于本任务或哈希/签名不一致，未访问CAD或重建。',{'reason':str(error)}) from error
    candidates=[]
    for row in getattr(session,'connection_candidates',task.get('connection_draft',{}).get('candidates',[])):
        candidates.append({**{k:row.get(k) for k in ('candidate_id','instance_a','instance_b','status','blocker','preferred_option_index','options_complete')},
            'options':[{**{k:o.get(k) for k in ('kind','axis_global','axis_point_global_m','source','supported_whole_inventory_missing_coordinates_if_goal_chosen')},
                        'axis_candidate_id':o.get('connection_intent',{}).get('candidate_id')} for o in row.get('options',[])]})
    questions=[]
    for q in assessment.get('mechanical_question_groups',[]):
        for name in q.get('instances',[]):questions.append({'reason':q['reason'],'instance':name,'design_intent_proven':False})
        for pair in q.get('pairs',[]):questions.append({'reason':q['reason'],'pair':pair,'design_intent_proven':False})
    for row in assessment.get('proposal_review_issues',[]):questions.append({'technical_blocker':row})
    goals=assessment.get('proposed_connection_intent',[])
    from ..assembly_intent_guide import build as intent_guide
    guide=intent_guide(survey,analytic) if not readonly else None
    names={c['component_id']:c['instance'] for c in survey['components']}
    mates=[]
    for m in survey.get('mates',[]):
        bindings=[e.get('component_id') for e in m.get('entities',[])]
        mates.append({**{k:m.get(k) for k in ('native_feature_id','name','type','suppressed','error','warning')},
            'component_instances':[names.get(cid) for cid in bindings[:8]],
            'entity_count':len(bindings),'component_bindings_complete':len(bindings)<=8 and all(cid in names for cid in bindings),
            'state_scope':'prepared_snapshot_revalidated_by_native_plan_not_live_observation',
            'automatic_suppression_recommended':False})
    collections={'components':components,'candidates':candidates,'goals':goals,'questions':questions,'geometry':geometry,'mates':mates}
    if guide:collections['mechanical_groups']=guide['groups']
    from .. import mirror_connections
    mirrors=mirror_connections.review(survey)
    if mirrors:collections['mirror_dependencies']=mirrors
    if not readonly:
        from ..mate_redundancy import review as redundancy_review
        redundant=redundancy_review(survey)
        if redundant:collections['redundancy_candidates']=redundant
    entry=_persist(task,session,'prepare',collections,source,additional)
    search=assessment.get('candidate_search') or {}
    task['assembly_brief']={'schema_version':1,'observation_stage':'prepare_snapshot_before_native_preview',
        'component_count':len(components),'mate_count':len(survey.get('mates',[])),
        'observed_fixed_flag_count':sum(c.get('fixed_component') is True for c in components),
        'fixed_flag_scope':'current_assembly_context_not_inferred_ground_for_descendants',
        'selected_scope':{'instance':(task.get('selected_assembly_layer') or {}).get('selected_instance'),
                          'coordinate_frame':'selected_assembly_document' if task.get('selected_assembly_layer') else 'root_assembly_document'},
        'accounting_complete':assessment.get('accounting_complete') is True,
        'geometry_captured':not readonly,'geometry_complete_for_captured_scope':analytic.get('analytic_geometry_complete') is True if analytic is not None else not readonly and bool(components) and all(c.get('geometry_complete') is True for c in components),
        'geometry_observation_scope':analytic.get('scope') if analytic else 'bounded_native_planner_reference_subset_not_all_faces',
        'planner_reference_geometry_complete':not readonly and bool(components) and all(c.get('geometry_complete') is True for c in components),
        'analytic_geometry_row_count':len(analytic['rows']) if analytic else None,
        'analytic_geometry_omitted_faces':analytic.get('omitted_faces') if analytic else None,
        'analytic_geometry_invalid_faces':analytic.get('invalid_faces') if analytic else None,
        'analytic_geometry_maximum_rows':analytic.get('maximum_rows') if analytic else None,
        'native_write_references_expanded':False,
        'candidate_pair_search_complete':search.get('all_pair_ranges_read') is True,
        'remaining_draft_cursor':search.get('remaining_cursor'),'candidate_search':search,
        'proposed_goal_count':len(goals),'question_row_count':len(questions),
        'category_counts':assessment.get('category_counts',{}),'write_scope_allowed':not readonly,
        'write_scope_blockers':review.get('write_scope_blockers',[]),'native_mate_health_issue_count':len(review.get('mate_health_issues',[])),
        'automatic_plan_available':assessment.get('automatic_plan_available') is True,
        'snapshot':entry,'mechanical_intent_proven':False,'motion_verified':False,
        'instruction':'AI先读取goals与questions，复用已明确用途集中澄清；需要时读取候选/组件/几何快照，不逐面访问CAD。快照不证明设计意图、缺项或当前状态。所有未知项及搜索截断仍保留阻断。实际plan须当前原生预演，具体方案确认后一次执行全部内部批次。'}
    if mirrors:
        task['assembly_brief']['mirror_dependency_count']=len(mirrors)
        task['assembly_brief']['mirror_sources_requiring_review']=sum(m['source_binding_status']=='mirror_source_review_required' for m in mirrors)
        query=next(q for q in entry['queries'] if ':mirror_dependencies:' in q['arguments']['snapshot_cursor'])
        task['next_action']={**query,'instruction':'AI先读镜向源件及派生实例。根据机械用途评估源件目标，避免给派生件直接加配合或将镜向等同于刚性。'}
    if guide:
        task['assembly_brief']['intent_guide']={k:v for k,v in guide.items() if k!='groups'}
        if guide['zero_mate_assembly'] and not mirrors:
            group_query=next((q for q in entry['queries'] if ':mechanical_groups:' in q['arguments']['snapshot_cursor']),None)
            if group_query:
                task['next_action']={'tool':group_query['tool'],'arguments':group_query['arguments'],
                    'instruction':'零配合没有既有约束路径；AI先读取几何同轴组，复用用户已说明的运动目标，按组集中澄清，再用whole_assembly一次预演、一次确认、内部自动分批。不让用户逐件填实体，不把同轴误当刚性。'}


def publish_plan(task,session):
    p=task['proposal'];names={c['component_id']:c['instance'] for c in session.connection_survey['components']}
    def name(v):return names.get(v,v)
    goals=[]
    for i,g in enumerate(p.get('goals',[])):
        goals.append({'goal_index':i,**{k:g[k] for k in ('kind','axis_global','axis_point_global_m','reference_point_global_m','source','added_action_count','coupled_verification_only','declared_closed_loop_coupled','independent_actuation_required') if k in g},
                      'component_a':name(g['component_a']),'component_b':name(g['component_b'])})
    actions=[]
    for i,a in enumerate(p.get('actions',[])):
        actions.append({'action_index':i,'exact_action_sha256':digest(a),
            **{k:a[k] for k in ('kind','value','lock_rotation','alignment','flip','flip_dimension','reference_kind_a','reference_kind_b','reason','goal_index') if k in a},
            **{k:name(a[k]) for k in ('component_a','component_b') if k in a},
            **{k:reference(a[k]) for k in ('reference_a','reference_b') if isinstance(a.get(k),dict)},
            **{k+'_sha256':digest(a[k]) for k in ('reference_a','reference_b') if isinstance(a.get(k),str)},
            'value_unit':'m' if a.get('kind')=='distance' else 'native_parameter'})
    groups=[{'name':g.get('name'),'anchor':name(g.get('anchor')),'member':name(member)}
            for g in p.get('rigid_groups',[]) for member in g.get('members',[])]
    groups.extend({'name':g['name'],'kind':'shared_material_axis','axis_component':name(g['axis_component']),
                   'member':name(m['component']),'axial':m['axial'],'rotation':m['rotation'],
                   'axis_global':g['axis_global'],'reference_point_global_m':g['reference_point_global_m']}
                  for g in p.get('coaxial_groups',[]) for m in g['members'])
    # The full native plan remains in the task record and is hashed by this source.
    path=session.folder/('方案复核原文-'+task['plan_token']+'.json');core.write(path,p)
    entry=_persist(task,session,'plan',{'goals':goals,'actions':actions,'groups':groups,
                 'fixed_changes':p.get('fixed_state_changes',[]),'mate_changes':p.get('mate_changes',[])},path)
    task['assembly_plan_review']={'snapshot':entry,'completion_scope':p.get('completion_scope'),
        'verification_mode':p.get('verification_mode','independent_joint_trials'),
        'construction_review':({k:p['construction_review'][k] for k in ('new_actions_before','new_actions_after','removed_new_action_indices','native_existing_mates_deleted','selection_basis','native_compatibility_verified')} if p.get('construction_review') else None),
        'initial_translation':{k:p['initial_translation'][k] for k in ('maximum_translation_m','translation_budget_m','maximum_rotation_rad','moved_components','requires_alignment_confirmation','native_pose_verified')} if p.get('initial_translation') else None,
        'primary_driven_loop':({'input':name(p['driven_loop_review']['primary']['component_a']),
            'reference':name(p['driven_loop_review']['primary']['component_b']),
            'outputs':[name(cid) for cid in p['driven_loop_review']['output_components']],
            'coupled_goal_indices':p['driven_loop_review']['coupled_goal_indices'],
            'native_motion_and_all_joint_output_checks_required':True,'independent_actuation_certified':False} if p.get('driven_loop_review') else None),
        'selected_scope':task.get('assembly_brief',{}).get('selected_scope'),
        'expected_added_mates':p.get('expected_added_mates'),'mate_change_count':len(p.get('mate_changes',[])),'native_batch_count':len(p.get('batches') or [None]),
        'all_or_restore_import_checkpoint':p.get('all_or_restore_import_checkpoint'),
        'omitted_native_feature_ids':p.get('omitted_native_feature_ids'),
        'scope':p.get('scope'),'finish_policy':p.get('finish_policy'),
        'group_binding_count':len(p.get('group_bindings',[])),'coaxial_group_count':len(p.get('coaxial_groups',[])),
        'pattern_scope_review_count':len(p.get('pattern_scope_reviews',[])),
        'mechanical_intent_proven':False,'execution_authorized':False,
        'instruction':'按全部非空方案复核集合解释目标、每项新增与固定变化、完整组成员及试验范围，集中取得具体确认；一次令牌只用于这一方案。页尾只代表当前集合，不代替其他集合。'}


def page(task,cursor,owner_available=False,page_size=None):
    match=re.fullmatch(r'([a-f0-9]{64}):('+('|'.join(KINDS))+r'):([0-9]{1,5})(?::([1-9][0-9]{0,2}))?',cursor or '')
    if not match:raise core.StopBatch('CONNECTION_INTENT_INVALID','装配快照游标格式错误；未查询CAD。')
    sid,kind,offset=match[1],match[2],int(match[3]);folder=core.no_links(Path(task['directory']))
    cursor_size=int(match[4]) if match[4] else None
    if ((page_size is not None and (type(page_size) is not int or not 1<=page_size<=100))
            or (cursor_size is not None and (cursor_size>100 or page_size not in (None,cursor_size)))
            or (cursor_size is None and offset and page_size is not None)):
        raise core.StopBatch('CONNECTION_INTENT_INVALID','页大小在集合首页选择（1至100），后续使用原样返回的游标。')
    page_size=cursor_size if cursor_size is not None else page_size
    byte_limit=EXPANDED_PAGE_BYTES if page_size is not None else PAGE_BYTES
    entries=[task.get('assembly_'+stage+'_snapshot') or {} for stage in ('prepare','plan')]
    for batch in task.get('connection_batch_history',[]):entries.extend(batch['snapshots'])
    entry=next((e for e in entries if e.get('snapshot_id')==sid),None)
    if not entry:raise core.StopBatch('CONNECTION_INTENT_INVALID','游标不属于本任务当前登记的装配快照。')
    try:
        path=core.no_links(folder/entry['path']);path.relative_to(folder)
        snap,sizes,default_boundaries=_read_snapshot(path,entry,task,folder)
        rows=snap['collections'][kind]
        if offset<0 or offset>=len(rows):raise ValueError('snapshot_offset_out_of_range')
        # Reproduce variable byte-budget page boundaries, rejecting offsets that
        # could skip rows or turn a shortened page into a self-referencing cursor.
        boundaries=default_boundaries.get(kind) if page_size is None else _page_offsets(sizes[kind],page_size,byte_limit-700)
        if boundaries is None:
            raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','该集合有单行超出旧分页预算，用较大页重新从集合首行读取。',
                {'snapshot_cursor':sid+':'+kind+':0','snapshot_page_size':RECOMMENDED_PAGE_ROWS,'native_calls':False})
        if offset not in boundaries[:-1]:raise ValueError('snapshot_offset_not_page_boundary')
        end=boundaries[boundaries.index(offset)+1]
        next_cursor=sid+':'+kind+':'+str(end) if end<len(rows) else None
        current=owner_available and snap['stage']=='plan' and task.get('phase')=='awaiting_confirmation' and task.get('plan_token')==entry.get('plan_token') and not task.get('execution_consumed') and not task.get('plan_token_revoked')
        if page_size is not None:
            result={'task_id':task['task_id'],'snapshot_page':{'snapshot_id':sid,'stage':snap['stage'],'collection':kind,
                'rows':copy.deepcopy(rows[offset:end]),'range_start':offset,'range_end_exclusive':end,'total_count':len(rows),
                'next_cursor':next_cursor+':'+str(page_size) if next_cursor else None,'requested_page_size':page_size,
                'collection_suffix_complete':end==len(rows),'all_collections_read':False,'native_calls':False,'write_dispatched':False,'plan_current':current,
                'observation_scope':snap['scope']}}
            if page_bytes(result)>byte_limit:raise ValueError('snapshot_page_envelope_over_budget')
            return result
        result={'task_id':task['task_id'],'snapshot_page':{'snapshot_id':sid,'model_id':snap['model_id'],'stage':snap['stage'],'collection':kind,
            'rows':rows[offset:end],'range_start':offset,'range_end_exclusive':end,'total_count':len(rows),
            'next_cursor':next_cursor,
            'collection_suffix_complete':end==len(rows),'all_collections_read':False,
            'read_tracking':'not_tracked_stateless_page','all_collections_read_is_completion_claim':False,
            'other_collection_counts':entry['counts'],'native_calls':False,'write_dispatched':False,
            'observation_scope':snap['scope'],'plan_current':current},
            'instruction':'只读已保存快照；累计前页并保留其他集合待办。末页不表示所有集合读完、原生状态当前有效或已获得执行授权。'}
        if page_bytes(result)>PAGE_BYTES:raise ValueError('snapshot_page_envelope_over_budget')
        return copy.deepcopy(result)
    except (OSError,ValueError,KeyError,TypeError) as error:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','装配快照、源证据或分页边界未通过核对；未访问CAD或重新生成。',{'reason':str(error)}) from error


def summary(task):
    from .task_views import conclusions
    keys=('task_id','phase','busy','closed','task_kind','server_instance_id','model_id','error','previous_failure',
          'next_action','progress','native_stage','plan_token','plan_token_revoked','assembly_brief','assembly_plan_review',
          'connection_status','task_owner_available','current_assembly_observation','validation_conclusions','orphan_review')
    result={k:task[k] for k in keys if k in task}
    result['validation_conclusions']=conclusions(task)
    proposal=task.get('proposal') or {}
    if proposal.get('task_operation') in {'change_existing_mates','independentize_mirrors'}:
        result['assembly_repair_plan']={k:proposal[k] for k in ('task_operation','affected_component_pairs','mirror_features',
            'independent_occurrences','expected_added_mates','motion_verified')}
    if task.get('assembly_repair_review'):
        result['assembly_repair_review']=task['assembly_repair_review']
    if task.get('connection_batch_history'):
        result['previously_verified_batch_count']=len(task['connection_batch_history'])
    if (task.get('proposal') or {}).get('task_operation')=='assign_part_materials':
        result['material_assignment_review']={'count':len(task['proposal']['assignments']),
            'requires_explicit_confirmation':True,
            'query':{'tool':'get_mechanism_task','arguments':{'task_id':task['task_id'],'full_record':True}}}
    if task.get('material_input_review'):
        result['material_input_review']={k:task['material_input_review'][k] for k in ('code','message')}
    for key in ('error','previous_failure'):
        if isinstance(result.get(key),dict):
            result[key]={k:result[key][k] for k in ('code','message','assertion','restoration_status','native_unknown','retry_write_allowed') if k in result[key]}
            result[key]['details_in_full_task']=True
    if isinstance(task.get('verification'),dict):
        result['verification']={k:v for k,v in task['verification'].items() if v is None or type(v) in (str,int,float,bool)}
        for key in ('initial_openings_mm','achieved_openings_mm','final_openings_mm','target_openings_mm'):
            if key in task['verification']:result['verification'][key]=task['verification'][key]
        result['verification']['full_task_retains_detailed_evidence']=True
    if task.get('finish'):
        f=task['finish'];result['finish']={k:f.get(k) for k in ('cleanup_status','next_round_allowed','source_files_unchanged','result_assembly_path','result_assembly_sha256','native_exit','executor_exit')}
        restored=f.get('restoration') or {}
        result['finish']['restoration']={k:restored.get(k) for k in ('restoration_status','source_files_unchanged','maximum_transform_delta')}
    result.update(summary_only=True,native_calls=False,
        observation_scope='saved_task_state_and_frozen_evidence_not_live_native_admission',
        full_record_query={'tool':'get_mechanism_task','arguments':{'task_id':task['task_id'],'full_record':True}})
    if task.get('assembly_brief'):
        result['assembly_brief_context']='historical_prepare_observation_not_current_mate_count'
    if task.get('closed') and result.get('current_assembly_observation'):
        result['current_assembly_observation']={**result['current_assembly_observation'],'historical_after_finish':True}
    if task.get('assembly_plan_review') and task.get('phase')=='awaiting_confirmation':
        result['assembly_brief_context']='historical_prepare_observation; current_concrete_goals_are_in_assembly_plan_review'
        result['next_action']={'tool':'get_mechanism_task','arguments':task['assembly_plan_review']['snapshot']['queries'][0]['arguments'],
              'instruction':'先累计方案复核的所有非空集合、解释完整改动并取得具体授权，再使用本任务令牌执行；摘要不代替方案复核或确认。'}
    if (task.get('error') or task.get('busy')) and task.get('connection_status')!='owner_lost_read_only':
        result['next_action']={'tool':'get_mechanism_task','arguments':{'task_id':task['task_id'],'full_record':True},
            'instruction':'运行或失败摘要仅来自保存记录；读取完整任务核对原请求、进度和恢复结论，不据摘要重复执行或关闭。'}
    return result
