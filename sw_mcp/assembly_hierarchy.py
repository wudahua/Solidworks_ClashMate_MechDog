"""Validate observed parent frames before treating fixed flags as grounding.

This is private next-stage work. Native hierarchy and real CAD acceptance are
required before enabling subassemblies in the delivered connection workflow.
"""

FIELDS={'parent_component_id','document_type','subassembly_solving','native_hierarchy_observed','parent_document_fixed_component','fixed_flag_observation_scope'}

def analyze(components,require_native=False):
    by={c['component_id']:c for c in components}
    if len(by)!=len(components) or not 1<=len(by)<=128:raise ValueError('hierarchy_component_inventory_invalid')
    observed=any(FIELDS.intersection(c) for c in components)
    if not observed:
        if require_native:raise ValueError('native_hierarchy_observation_required')
        return {'native_observed':False,'parents':{cid:None for cid in by},'parent_document_fixed_components':{cid:None for cid in by},'rigid_child_pairs':[],'subassemblies':[],
                'flexible_subassemblies':[],'supported_for_connection_writes':True,'legacy_flat_scope':True}
    parents={};subassemblies=[];flexible=[]
    for cid,c in by.items():
        if not FIELDS<=set(c) or c['native_hierarchy_observed'] is not True:raise ValueError('hierarchy_observation_incomplete')
        parent=c['parent_component_id'];kind=c['document_type'];mode=c['subassembly_solving']
        owning_fixed=c['parent_document_fixed_component']
        if parent is None:
            if owning_fixed is not None or c['fixed_flag_observation_scope']!='assembly_root':raise ValueError('root_fixed_flag_scope_invalid')
        elif type(owning_fixed) is not bool or c['fixed_flag_observation_scope']!='root_context_only':raise ValueError('owning_document_fixed_flag_not_observed')
        if parent is not None and (not isinstance(parent,str) or parent not in by or parent==cid):raise ValueError('hierarchy_parent_outside_inventory_or_self')
        if type(kind) is not int or kind not in (1,2):raise ValueError('hierarchy_document_type_invalid')
        if kind==1 and mode is not None:raise ValueError('part_cannot_have_subassembly_solving_mode')
        if kind==2:
            if type(mode) is not int or mode not in (0,1):raise ValueError('subassembly_solving_not_observed')
            subassemblies.append(cid)
            if mode==1:flexible.append(cid)
        parents[cid]=parent
    for cid,parent in parents.items():
        if parent is not None and by[parent]['document_type']!=2:raise ValueError('hierarchy_parent_not_an_assembly')
        seen=set();cursor=cid
        while cursor is not None:
            if cursor in seen:raise ValueError('hierarchy_cycle')
            seen.add(cursor)
            if len(seen)>8:raise ValueError('hierarchy_depth_budget')
            cursor=parents[cursor]
    rigid=[{'component_a':cid,'component_b':parent,'kind':'rigid','source':'native_rigid_subassembly_mode_not_new_mate',
            'mechanical_intent_inferred':False,'motion_verified':False} for cid,parent in sorted(parents.items())
           if parent is not None and by[parent]['subassembly_solving']==0]
    return {'native_observed':True,'parents':parents,'parent_document_fixed_components':{cid:c['parent_document_fixed_component'] for cid,c in by.items()},'rigid_child_pairs':rigid,'subassemblies':sorted(subassemblies),
            'flexible_subassemblies':sorted(flexible),'supported_for_connection_writes':not flexible,
            'legacy_flat_scope':False,'maximum_depth':max(sum(1 for _ in ancestors(cid,parents)) for cid in by)}

def ancestors(cid,parents):
    while cid is not None:
        yield cid;cid=parents[cid]

def require_top_level_target(component_id,hierarchy):
    if hierarchy['parents'][component_id] is not None:raise ValueError('nested_component_target_requires_parent_scope')

def inherited_coverage(declared,hierarchy):
    if not hierarchy['supported_for_connection_writes']:raise ValueError('flexible_subassembly_scope_unsupported')
    covered=set(declared);inherited=[]
    for cid in sorted(hierarchy['parents']):
        parent=hierarchy['parents'][cid]
        while parent is not None:
            if parent in declared:
                covered.add(cid);inherited.append({'component_id':cid,'declared_ancestor':parent,'source':'verified_native_rigid_hierarchy_not_unassigned_stationary_default'});break
            parent=hierarchy['parents'][parent]
    return covered,inherited
