"""Explain observed mirror dependencies before any native mate preview."""
def review(survey):
    structure = survey.get('structural_relations') or {}
    occurrences = structure.get('components') or []
    names = {c['component_id']: c['instance'] for c in survey['components']}
    by_feature = {r['native_feature_id']: r for r in occurrences if r.get('native_feature_id') is not None}
    mirrors = {m['native_feature_id']: m for m in structure.get('mirrors', [])}
    structure_complete = (structure.get('feature_inventory_truncated') is False and structure.get('issues') == []
                          and len(by_feature)==len(occurrences) and len(mirrors)==len(structure.get('mirrors', [])))
    result = []
    verified_edges = {}
    for row in occurrences:
        cid = row['component_id']
        parents = row.get('parent_features', [])
        if not row.get('is_pattern_instance') or cid not in names:
            continue
        features = [p for p in parents if p.get('type') == 'MirrorCompFeat']
        if not features:
            continue
        sources = set()
        direct = {by_feature[p['native_feature_id']]['component_id'] for p in parents
                  if p['native_feature_id'] in by_feature and p.get('type') in {'Reference','ReferencePattern'}}
        feature_rows = []
        for p in features:
            feature = mirrors.get(p['native_feature_id'], {})
            observed = set(feature.get('definition_source_component_ids', []))
            sources.update(observed)
            feature_rows.append({'native_feature_id':p['native_feature_id'], 'name':p['name'],
                'definition_available':feature.get('definition_available',False),
                'derived_child_observed':any(c['native_feature_id']==row['native_feature_id'] for c in feature.get('child_features', [])),
                'suppressed':feature.get('suppressed')})
        reported = sources | direct
        candidates = sorted((reported & names.keys()) - {cid})
        evidence_complete = (structure_complete and len(parents)<64 and bool(candidates)
                             and reported==set(candidates) and direct<=sources
                             and all(f['definition_available'] and f['derived_child_observed'] and f['suppressed'] is False for f in feature_rows)
                             and all(mirrors.get(p['native_feature_id'],{}).get('definition_source_component_ids') for p in features))
        unique = evidence_complete and len(features)==1 and len(candidates)==1
        if evidence_complete:
            verified_edges[cid] = set(candidates)
        result.append({'component_id':cid,'instance':names[cid], 'mirror_features':feature_rows,
            'source_candidates':[{'component_id':c,'instance':names[c]} for c in candidates],
            'source_binding_status':'unique_native_source_observed' if unique else 'mirror_source_review_required',
            'planning_route':'review_explicit_source_goal' if unique else 'review_original_mirror_definition',
            'individual_mate_write_allowed':False,'automatic_goal_remap':False,'rigid_motion_proven':False})
    original_occurrences={r['component_id'] for r in occurrences if r.get('is_pattern_instance') is False}
    root_cache={}

    def roots(cid, path):
        if cid in original_occurrences:
            return ({cid},0)
        if cid in path or cid not in verified_edges or len(path)>=16:
            return None
        if cid in root_cache:
            return root_cache[cid]
        origins=set()
        depth=0
        for source in verified_edges[cid]:
            found=roots(source,path|{cid})
            if not found:return None
            origins.update(found[0])
            depth=max(depth,found[1]+1)
        root_cache[cid]=(origins,depth)
        return root_cache[cid]

    for row in result:
        found=roots(row['component_id'],set())
        origins=found[0] if found and found[1]<=16 else set()
        row['root_source_candidates']=[{'component_id':c,'instance':names[c]} for c in sorted(origins or [])]
        unique_root=len(origins)==1
        row['root_source_status']='unique_root_of_observed_dependency_chain' if unique_root else 'mirror_chain_requires_review'
        row['supported_actions']=['review_source_goal','verify_declared_rigid_group'] if unique_root else ['review_original_mirror_definition']
        if unique_root:
            family={row['component_id']};pending=list(family)
            while pending:
                sources=verified_edges.get(pending.pop(),set())-family
                family.update(sources)
                pending.extend(sources)
            row['rigid_group_member_hints']=sorted(names[c] for c in family)
            row['rigid_group_condition']='all_source_and_derived_members_share_a_declared_rigid_motion_and_require_native_verification'
        if unique_root and row['source_binding_status']=='mirror_source_review_required':
            row['planning_route']='review_shared_root_goal_and_intermediate_mirror_mapping'
    return result


def blockers(survey, goals, reviewed):
    names = {c['component_id']:c['instance'] for c in survey['components']}
    by_id = {r['component_id']:r for r in reviewed}
    blocked = []
    for index, goal in enumerate(goals):
        a,b = goal['component_a'],goal['component_b']
        affected = [by_id[c] for c in (a,b) if c in by_id]
        if affected:
            blocked.append({'goal_index':index,'component_a':names[a],'component_b':names[b],
                'kind':goal['kind'],'mirror_dependencies':affected})
    return blocked
