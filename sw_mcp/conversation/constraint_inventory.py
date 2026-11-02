"""Frozen structure observations do not authorize unsupported mate writes."""
import hashlib,json,re
from pathlib import Path
from . import core

MAX_COMPONENTS=500
PAGE_SIZE=16
SNAPSHOT='只读装配结构快照.json'


def blockers(preflight):
    count=preflight.get('components')
    rows=[]
    if type(count) is int and count>128:
        rows.append({'code':'CONNECTION_WRITE_NODE_BUDGET','observed_nodes':count,'write_limit':128})
    rows += [{'code':'FLEXIBLE_SUBASSEMBLY_WRITE_UNVALIDATED','native_observation':s}
             for s in preflight.get('blockers',[]) if isinstance(s,str) and s.startswith('FLEXIBLE_SUBASSEMBLY_NOT_VALIDATED ')]
    return rows


def _digest(snapshot,binding):
    return hashlib.sha256(json.dumps({'binding':str(binding),'snapshot':snapshot},sort_keys=True,
                                    ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')).hexdigest()


def _component(c):
    # Context IsFixed and owning-document IsFixed remain separate observations.
    return {k:c.get(k) for k in ('component_id','instance','parent_component_id','document_type','subassembly',
        'subassembly_solving','fixed_component','parent_document_fixed_component','fixed_flag_observation_scope',
        'configuration','loaded','suppressed','speedpak')}


def _page(snapshot,kind,offset,snapshot_id):
    rows=snapshot[kind];end=min(offset+PAGE_SIZE,len(rows))
    return {'collection':kind,'snapshot_id':snapshot_id,'rows':rows[offset:end],
            'range_start':offset,'range_end_exclusive':end,'total_count':len(rows),
            'next_cursor':snapshot_id+':'+kind+':'+str(end) if end<len(rows) else None,
            'collection_suffix_complete':end==len(rows),'all_structure_pages_completed':False,
            'completeness_scope':'this_collection_suffix_only_not_other_collection_or_previous_pages',
            'native_calls':False,'write_dispatched':False,'observation_scope':'frozen_prepare_snapshot_not_live_CAD_state'}


def discover(session,preflight):
    expected=preflight.get('components')
    if type(expected) is not int or not 1<=expected<=MAX_COMPONENTS:
        raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED','只读结构体检限500节点；写入仍限128节点。',
                             {'observed_nodes':expected,'readonly_limit':MAX_COMPONENTS,'write_limit':128,'write_dispatched':False})
    inspection=session.call('inspect_model',model_id=session.model,detail_level='full')
    cs=inspection['components'];ids=[c.get('component_id') for c in cs]
    if len(cs)!=expected or len(set(ids))!=len(cs) or not all(isinstance(i,str) and i for i in ids) or inspection.get('source_files_unchanged') is not True:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','只读组件数量、身份或源文件核对不一致，未登记为完成。')
    # Restore uses this exact full frame, including all native mates. A compact
    # presentation or a components-only reply must never become its baseline.
    session.initial_inspection=inspection;session.connection_survey=inspection
    native=session.call('_survey_connection_layers',model_id=session.model)
    if native.get('inventory_complete') is not True or len(native.get('layers',[]))>MAX_COMPONENTS:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','原生层级清单不完整，未静默截断。')
    layer_rows=native['layers'];layer_ids=[r.get('component_id') for r in layer_rows]
    if len(set(layer_ids))!=len(layer_ids) or set(layer_ids)-set(ids) or native.get('source_files_unchanged') is not True:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','层级身份或源文件与完整组件快照不匹配。')
    session.assembly_layers=native
    snapshot={'components':[_component(c) for c in cs],
              'layers':[{**r,'scope_selectable':False,'internal_completeness_certified':False,
                         'readonly_task_does_not_authorize_layer_selection':True} for r in native['layers']],
              'component_count':len(cs),'mate_count':len(inspection['mates']),
              'native_mate_health':inspection.get('mate_health'),'preflight_mate_health':preflight.get('mate_health'),
              'write_scope_blockers':blockers(preflight),'geometry_survey_performed':False,
              'source_files_unchanged':True,'configuration':inspection.get('configuration')}
    sid=_digest(snapshot,session.folder.parent.absolute());core.write(session.folder/SNAPSHOT,snapshot)
    core.write(session.folder/'只读结构完整原生检查.json',inspection)
    pages={kind:_page(snapshot,kind,0,sid) for kind in ('components','layers')}
    queries=[{'tool':'get_mechanism_task','arguments':{'structure_cursor':p['next_cursor']}}
             for p in pages.values() if p['next_cursor']]
    summary={'mode':'readonly_structure','snapshot_id':sid,'component_count':len(cs),'mate_count':len(inspection['mates']),
             'layer_count':len(snapshot['layers']),'component_inventory_captured':True,'geometry_survey_performed':False,
             'write_scope_allowed':False,'write_scope_blockers':snapshot['write_scope_blockers'],
             'native_mate_health':snapshot['native_mate_health'],'pages':pages,'pending_queries':queries,
             'all_structure_pages_completed':False,'full_snapshot_path':str(session.folder/SNAPSHOT)}
    review={'status':'readonly_structure_review','mode':'readonly_structure','complete':False,
            'component_inventory_complete':True,'component_count':len(cs),'mate_count':len(inspection['mates']),
            'native_mate_health':snapshot['native_mate_health'],'write_scope_allowed':False,
            'write_scope_blockers':snapshot['write_scope_blockers'],'write_dispatched':False,
            'global_DOF':None,'all_mates_sufficient':None,'motion_verified':False,'native_motion_study_solved':False}
    session.readonly_constraint_inventory=True
    session.connection_draft={'status':'not_generated_readonly_structure','candidates':[],
        'candidate_search_performed':False,'no_candidates_does_not_prove_no_missing_mates':True,'next_cursor':None}
    return {'connection_review':review,'connection_draft':session.connection_draft,
        'assembly_overview':{'status':'readonly_structure_not_joint_recommendations','component_count':len(cs),
            'accounting_complete':True,'write_scope_allowed':False,'mechanical_intent_inferred':False},
        'assembly_layers':{**{k:v for k,v in native.items() if k!='layers'},'layers':pages['layers']['rows'],
            'layers_total':len(snapshot['layers']),'layers_truncated':len(snapshot['layers'])>PAGE_SIZE,
            'next_cursor':pages['layers']['next_cursor'],'readonly_structure':True,'write_scope_allowed':False,
            'all_layers_completed':False},'constraint_structure':summary}


def publish(engine,task,value):
    structure=value['constraint_structure'];task['constraint_structure']=structure
    task['confirmation_required']=False
    for query in structure['pending_queries']:query['arguments']['task_id']=task['task_id']
    task['next_action']=structure['pending_queries'][0] if structure['pending_queries'] else {
        'tool':'finish_mechanism_task','arguments':{'task_id':task['task_id']}}
    task['next_action']={**task['next_action'],'automatic_retry':False,
        'instruction':'当前只读体检已记录组件、原生配合健康和刚性/柔性层级；保留components与layers两队分页待办，末页不代表整模型完成。'
        '几何缺项、全局自由度及配合充分性未认证，写入仍受128节点和原刚性边界限制。'
        'AI解释阻断后finish恢复；若另选独立子文档，先结束本任务再准备新副本，不自动改柔性、配置或原文件。'}


def require_write_scope(task):
    review=task.get('connection_review') or {}
    if review.get('write_scope_allowed') is False:
        raise core.StopBatch('CONNECTION_SCOPE_UNSUPPORTED','当前仅通过只读结构体检，不允许在本任务预演、选择内部写入范围或执行配合。',
            {'write_scope_blockers':review.get('write_scope_blockers',[]),'readonly_structure_available':True,
             'write_dispatched':False,'automatic_retry':False,'next_tool':'get_mechanism_task'})


def page(task,cursor):
    if (task.get('constraint_structure') or {}).get('mode')!='readonly_structure':
        raise core.StopBatch('CONNECTION_INTENT_INVALID','本任务没有只读结构分页快照。')
    match=re.fullmatch(r'([a-f0-9]{64}):(components|layers):([0-9]{1,3})',cursor or '')
    if not match:raise core.StopBatch('CONNECTION_INTENT_INVALID','结构游标格式无效，不混用配合草案游标。')
    folder=core.no_links(Path(task['directory']))
    try:snapshot=core.read(folder/'session'/SNAPSHOT)
    except (OSError,ValueError) as error:raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','保存的结构快照不可读，未访问CAD或重建现场。',{'error_type':type(error).__name__}) from error
    sid=_digest(snapshot,folder.absolute())
    if sid!=task['constraint_structure']['snapshot_id']:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED','保存的只读结构快照发生变化，未继续分页或访问CAD。')
    if match[1]!=sid:raise core.StopBatch('CONNECTION_INTENT_INVALID','结构游标与任务快照不匹配。')
    offset=int(match[3]);kind=match[2]
    if offset<1 or offset>=len(snapshot[kind]) or offset%PAGE_SIZE:
        raise core.StopBatch('CONNECTION_INTENT_INVALID','结构游标超出当前集合或不在页边界。')
    return {'task_id':task['task_id'],'constraint_structure_page':_page(snapshot,kind,offset,sid),
            'instruction':'仅本集合的当前后缀页；AI累计前页并保留另一集合待办，不用末页宣告全部结构完成。'}
