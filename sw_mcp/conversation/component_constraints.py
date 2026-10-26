"""Read-only constraint evidence; a floating flag never proves a free DOF."""
from . import core


def inventory(components, mates, groups=None):
    groups=groups or {}; moving={cid:side for side,ids in groups.items() for cid in ids}
    links={c['component_id']:[] for c in components}
    for mate in mates:
        if mate.get('suppressed'):continue
        ids=list(dict.fromkeys(e.get('component_id') for e in mate.get('entities',[]) if e.get('component_id') in links))
        for cid in ids:
            links[cid].append({'native_feature_id':mate.get('native_feature_id'),'name':mate.get('name'),
                              'type':mate.get('type'),'peers':[x for x in ids if x!=cid]})
    rows=[]
    for c in components:
        cid=c['component_id'];native=c.get('constraint_state') or {}
        fully=native.get('status')=='observed' and native.get('native_value')==3 and native.get('fully_constrained') is True
        category=('recommended_'+moving[cid]+'_rotor' if cid in moving else 'fixed_by_native_flag' if c['fixed_component']
                  else 'native_fully_constrained_not_fixed' if fully else 'unassigned_constraint_review_required')
        rows.append({'component_id':cid,'instance':c['instance'],'fixed_component':c['fixed_component'],
                     'constraint_state':native or {'status':'not_observed'},'category':category,'mate_links':links[cid],
                     'remaining_DOF':None,'stationary_during_motion_verified':False})
    return {'component_count':len(rows),'fixed_flag_count':sum(r['fixed_component'] for r in rows),
            'native_fully_constrained_not_fixed_count':sum(r['category']=='native_fully_constrained_not_fixed' for r in rows),
            'unassigned_count':sum(r['category']=='unassigned_constraint_review_required' for r in rows),
            'components':rows,'fixed_flag_is_not_DOF':True,'classification_is_design_intent':False,
            'automatic_fix_or_lock_performed':False,'motion_verified':False}


def require_import_health(preflight, evidence_path):
    """All-fixed is intentional preparation input; rebuild errors are never waived."""
    if not isinstance(preflight,dict):
        raise core.StopBatch('MODEL_PREFLIGHT_FAILED','缺少原导入预检，不能继续准备齿轮配合。',
                             {'preflight_status':'missing','evidence_path':str(evidence_path),'write_dispatched':False})
    blockers=[b for b in preflight.get('blockers',[]) if b!='ALL_COMPONENTS_FIXED']
    failed=blockers or preflight.get('native_rebuild_succeeded') is not True or preflight.get('feature_diagnostics')
    if failed:
        raise core.StopBatch('MODEL_PREFLIGHT_FAILED','导入副本存在重建、特征或解析错误；先核对模型健康，不再通过更换零件名称尝试规划。',
            {**preflight,'blocking_gate':'external_gear_import_health','evidence_path':str(evidence_path),
             'blocking_items':blockers,'write_dispatched':False,'name_clarification_can_resolve':False,
             'source_model_defect_proven':False,'recommended_next_step':'review_saved_feature_and_reference_evidence_then_finish_original_task'})
