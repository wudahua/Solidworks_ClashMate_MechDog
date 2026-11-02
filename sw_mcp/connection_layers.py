"""Document scopes never inherit internal completeness from a rigid parent."""

def catalog(native):
    if native.get('inventory_complete') is not True:raise ValueError('layer_inventory_incomplete')
    rows=native.get('layers')
    if not isinstance(rows,list) or len(rows)>128:raise ValueError('layer_inventory_invalid')
    seen=set();out=[]
    for raw in rows:
        name=raw.get('instance')
        if not isinstance(name,str) or not name or name in seen:raise ValueError('layer_instance_invalid')
        seen.add(name)
        for key in ('internal_direct_components','internal_fixed_components','internal_mates','shared_document_instances'):
            if type(raw.get(key)) is not int or raw[key]<0:raise ValueError('layer_observation_invalid')
        if type(raw.get('scope_selectable')) is not bool:raise ValueError('layer_admission_unobserved')
        if raw['scope_selectable'] and (raw.get('native_rigid') is not True or raw['shared_document_instances']!=1):raise ValueError('layer_shared_or_flexible_not_selectable')
        out.append({**raw,'internal_completeness_certified':False,
                    'recommended_next_step':'inspect_in_own_document_with_declared_mechanical_goals' if raw['scope_selectable'] else 'explain_scope_refusal',
                    'floating_observation_does_not_prove_missing_mates':True})
    selectable=[r for r in out if r['scope_selectable']]
    return {**native,'layers':out,'recommended_scope_instance':selectable[0]['instance'] if len(selectable)==1 else None,
            'mechanical_intent_inferred':False,'all_layers_completed':False,
            'instruction':'AI按用户目标推荐需要检查的装配层；唯一可检查层可直接推荐，不要求用户抄路径。多个层级依用途选择，不能按浮动数直接判定缺项。一次事务只改所选文档，其他层另立明确目标。'}

def resolve(value,hint):
    if not isinstance(hint,str) or not hint.strip() or len(hint)>256:raise ValueError('layer_hint_invalid')
    rows=value['layers'];text=hint.strip().casefold()
    matches=[r for r in rows if r['instance'].casefold()==text]
    if not matches:matches=[r for r in rows if text in r['instance'].casefold()]
    if len(matches)!=1:
        return None,{'needs_mechanical_clarification':True,'field':'assembly_scope_hint',
            'name_hint':hint,'choices':[{'instance':r['instance'],'internal_components':r['internal_direct_components'],
                'scope_selectable':r['scope_selectable']} for r in matches or rows],
            'question':'请按机械用途澄清检查哪个子装配；AI使用完整实例名，不要求用户输入文档路径。','write_dispatched':False}
    row=matches[0]
    if not row['scope_selectable']:raise ValueError('layer_not_selectable:'+str(row.get('refusal_reason')))
    return row,None
