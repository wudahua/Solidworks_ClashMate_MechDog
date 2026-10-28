"""Read-only grouping drafts from observed constraints, with explicit uncertainty.

Membership is a proposal for mechanical review, never a proof of rigidity or
permission to fix a part. Unobserved relations and multi-seed patterns stay open.
"""
from . import assembly_constraints as ac


def recommend(survey, seeds, review=None):
    components = survey['components']
    by_id = {c['component_id']: c for c in components}
    if not survey.get('inventory_complete') or not 1 <= len(components) <= 128 or len(by_id) != len(components):
        return {'status': 'incomplete_inventory', 'complete': False,
                'write_dispatched': False, 'automatic_assignment': False}
    review = review or ac.analyze(components, survey['mates'], seeds,
        structural_relations=survey.get('structural_relations'))
    rows = {r['component_id']: r for r in review['components']}
    labels = {cid: r['suggested_group'] for cid, r in rows.items() if r['suggested_group']}
    evidence = {cid: {'kind': rows[cid]['group_source'],
                     'rigidity_proven': False} for cid in labels}
    # Integral bearing models have no separately movable inner/outer rings.
    # A rank-five connection to a shaft must not imply bearing follow-through.
    bearings = {cid for cid, c in by_id.items()
                if any(word in c['instance'].casefold() for word in ('bearing', '轴承', '軸承'))
                and not any(word in c['instance'].casefold() for word in ('cover', 'housing', 'cap', '盖', '蓋', '座'))
                and not any(cid in members for members in seeds.values())}
    for cid in bearings:
        if rows[cid]['group_source'] != 'native_fixed_flag':
            labels.pop(cid, None)
    # Search through unassigned peers, stopping at each existing group anchor.
    # All reachable anchors must agree; a bolt between two moving groups must
    # not acquire whichever group happened to be processed first.
    anchors = dict(labels)
    for cid, row in rows.items():
        if cid in anchors or cid in bearings or row['status'] == 'group_conflict':
            continue
        todo = [cid]; visited = set(); found = set(); features = set()
        while todo:
            peer = todo.pop()
            if peer in visited or peer in bearings:
                continue
            visited.add(peer)
            if peer in anchors:
                found.add(anchors[peer]); continue
            if rows[peer]['status'] == 'group_conflict':
                found.add('conflict'); continue
            for link in rows[peer]['mate_links']:
                if link['supported_local_rank'] > 0 and not link['issues']:
                    todo.append(link['peer']); features.update(link['native_feature_ids'])
        if len(found) == 1 and 'conflict' not in found:
            labels[cid] = next(iter(found))
            evidence[cid] = {'kind': 'single_group_constraint_path_hypothesis',
                'rigidity_proven': False, 'native_feature_ids': sorted(features)}
    # Propagate a *proposal* only through explicitly observed pattern ancestry.
    # All seeds must have the same proposal. Pattern motion is still unproven.
    patterns = {p['component_id']: p for p in review['pattern_dependencies']}
    changed = True
    while changed:
        changed = False
        for cid, dependency in patterns.items():
            if cid in labels or cid in bearings or rows[cid]['status'] == 'group_conflict':
                continue
            parents = dependency['seed_component_ids']
            groups = {labels.get(parent) for parent in parents}
            if parents and None not in groups and len(groups) == 1:
                labels[cid] = next(iter(groups))
                evidence[cid] = {'kind': 'native_pattern_seed_group_hypothesis',
                    'seed_component_ids': parents, 'pattern_features': dependency['pattern_features'],
                    'rigidity_proven': False, 'pattern_motion_proven': False}
                changed = True
    suggestions = []
    pending = []
    for cid, c in by_id.items():
        row = rows[cid]
        label = labels.get(cid)
        if cid in bearings and row['group_source'] != 'native_fixed_flag':
            # Even an apparently complete local relation does not identify the
            # intended inner/outer race semantics of a single-part bearing.
            label = None
        candidates = sorted(group for group, rank in row['constraint_rank_by_neighbor_group'].items() if rank > 0)
        record = {'component_id': cid, 'instance': c['instance'], 'suggested_group': label,
            'candidate_groups': candidates, 'evidence': evidence.get(cid),
            'requires_mechanical_intent_confirmation': row['group_source'] != 'native_fixed_flag',
            'motion_verified': False}
        if label:
            suggestions.append(record)
        else:
            record.update(reason='integral_bearing_motion_intent' if cid in bearings else
                'conflicting_group_evidence' if row['status'] == 'group_conflict' else 'insufficient_or_multiple_group_evidence',
                pattern_dependency=patterns.get(cid), mate_links=row['mate_links'])
            pending.append(record)
    question_sets = {}
    for r in pending:
        # Bearings are one mechanical decision, even with different neighboring
        # shafts. Other unknown components retain their differing alternatives.
        key = (r['reason'], () if r['reason'] == 'integral_bearing_motion_intent' else tuple(r['candidate_groups']))
        question_sets.setdefault(key, []).append(r)
    questions = [{'reason': key[0], 'components': [{'component_id': r['component_id'], 'instance': r['instance']} for r in values],
        'candidate_groups': sorted({g for r in values for g in r['candidate_groups']}),
        'question': ('这些轴承按整件建模，无法分别模拟内外圈。是否让整件相对机体静止？如需分别运动，应使用可区分内外圈的模型。'
                     if key[0] == 'integral_bearing_motion_intent' else
                     '这些组件应随输入轴、输出轴、机体保持相对静止，还是保留其他独立运动？AI按回答补齐清单。')}
        for key, values in question_sets.items()]
    draft = {group: [r['instance'] for r in sorted(suggestions,
                key=lambda r: (seeds.get(group, []).index(r['component_id'])
                    if r['component_id'] in seeds.get(group, []) else len(components)))
                if r['suggested_group'] == group]
             for group in ('stationary', 'input', 'output')}
    return {'schema_version': 1, 'status': 'mechanical_questions_required' if pending else 'draft_ready_for_plan_review',
        'complete': not pending, 'component_count': len(components), 'draft_component_count': len(suggestions),
        'pending_component_count': len(pending), 'question_count': len(questions),
        'assembly_intent_draft': draft, 'component_recommendations': suggestions,
        'pending_components': pending, 'mechanical_questions': questions,
        'evidence_sha256': review['input_sha256'], 'reference_state_signature': survey.get('reference_state_signature'),
        'requires_plan_confirmation': True, 'automatic_assignment': False,
        'fixed_state_changes': [], 'write_dispatched': False, 'motion_verified': False,
        'instructions': 'AI复用推荐清单，集中澄清pending组件；归属仍是待确认的机械假设。清单完整且互不重叠后使用assembly_intent只读规划，取得当前方案确认后才执行。不得以局部秩、阵列或名称代替原生运动验证。'}
