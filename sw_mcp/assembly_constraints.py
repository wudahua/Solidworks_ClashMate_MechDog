"""Read-only, name-independent evidence for assembly constraint completion.

This is a local linearized constraint model, not a replacement for the CAD
solver or a design-intent oracle. Unsupported constraints remain visible.
Nothing in this module fixes, suppresses, registers, or writes a CAD entity.
"""
from collections import defaultdict
import hashlib
import json
import math


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def unit(v):
    if not isinstance(v, (tuple, list)) or len(v) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in v):
        raise ValueError('invalid_vector')
    n = math.sqrt(dot(v, v))
    if n < 1e-12:
        raise ValueError('zero_vector')
    return [x/n for x in v]


def basis(rows):
    """Twice reorthogonalized six-column row basis; scaled before entry."""
    found = []
    for row in rows:
        n = math.sqrt(dot(row, row))
        if n < 1e-14:
            continue
        v = [x/n for x in row]
        for _ in range(2):
            for b in found:
                k = dot(v, b)
                v = [x-k*y for x, y in zip(v, b)]
        n = math.sqrt(dot(v, v))
        if n > 1e-8:
            found.append([x/n for x in v])
    return found


def perpendiculars(axis):
    seed = min(([1, 0, 0], [0, 1, 0], [0, 0, 1]), key=lambda v: abs(dot(axis, v)))
    a = unit(cross(axis, seed))
    return a, unit(cross(axis, a))


def _frame(components):
    points = [c['transform'][9:12] for c in components if isinstance(c.get('transform'), list) and len(c['transform']) >= 12]
    if not points:
        return [0, 0, 0], 1.
    origin = [sum(p[i] for p in points)/len(points) for i in range(3)]
    scale = max([math.sqrt(sum((p[i]-origin[i])**2 for i in range(3))) for p in points]+[.001])
    return origin, scale


def _shape(entity):
    g = entity.get('geometry') or entity.get('constraint_geometry') or {}
    axis = unit(g.get('axis_global'))
    p = g.get('reference_point_global_m')
    if not isinstance(p, list) or len(p) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in p):
        raise ValueError('invalid_reference_point')
    return g.get('kind'), axis, p


def _rows(mate, entities, origin, scale):
    """Relative spatial-twist rows [linear_at_origin / scale, angular]."""
    t = mate['type']
    if t == 16:  # Native lock mate, six relative coordinates.
        return [[float(i == j) for i in range(6)] for j in range(6)]
    kind_a, axis_a, point_a = _shape(entities[0])
    kind_b, axis_b, point_b = _shape(entities[1])
    if t in {2,6} and kind_a==kind_b=='planar_normal':
        cosine=dot(axis_a,axis_b)
        if t==2 and abs(cosine)>1e-8:raise ValueError('perpendicular_reference_mismatch')
        normal=cross(axis_a,axis_b)
        if math.sqrt(dot(normal,normal))<1e-8:raise ValueError('singular_angle_constraint')
        return [[0.,0.,0.]+unit(normal)]
    if abs(dot(axis_a, axis_b)) < 1-1e-8:
        raise ValueError('nonparallel_reference_axes')
    p = [(point_b[i]-origin[i])/scale for i in range(3)]
    def location(normal):
        return list(normal)+cross(p, normal)
    angular = [[0., 0., 0.]+list(v) for v in perpendiculars(axis_a)]
    if t==0 and {kind_a,kind_b}=={'planar_normal','circular_edge'}:
        # Native coincident face/edge references share the edge's plane. This
        # observes the existing mate; it does not register edge->face creation.
        separation=dot(axis_a,[point_a[i]-point_b[i] for i in range(3)])
        if abs(separation)>1e-5:raise ValueError('coincident_circle_plane_gap')
        return angular+[location(axis_a)]
    axial_kinds={'cylindrical_axis','circular_edge','conical_axis','reference_axis'}
    if t == 1 and kind_a in axial_kinds and kind_b in axial_kinds:
        # Concentric observations with visibly different axes are not treated
        # as sound constraints even if the native mate error field is zero.
        d = [point_a[i]-point_b[i] for i in range(3)]
        radial = [d[i]-dot(d, axis_a)*axis_a[i] for i in range(3)]
        if math.sqrt(dot(radial, radial)) > 1e-5:
            raise ValueError('concentric_reference_gap')
        rows = angular+[location(v) for v in perpendiculars(axis_a)]
        lock = mate.get('rotation_lock_observation') or {}
        if lock.get('status') == 'observed' and lock.get('locked') is True:
            rows.append([0., 0., 0.]+axis_a)
        return rows
    if t in {0, 5, 3} and kind_a == kind_b == 'planar_normal':
        # Coincident and distance plane mates align their normals and constrain
        # separation; parallel planes constrain orientation only.
        return angular+([location(axis_a)] if t in {0, 5} else [])
    raise ValueError('unsupported_reference_or_mate_kind')


def analyze(components, mates, seeds=None, inventory_complete=True, structural_relations=None):
    """Analyze any supported top-level assembly, without model-name rules.

    Seeds are explicit proposed/mechanically declared motion groups. Membership
    inferred from rank remains a recommendation pending native motion testing.
    Native IsFixed and GetConstrainedStatus are observations, not inferred DOF.
    """
    ids = [c.get('component_id') for c in components]
    if len(components) > 128 or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        return {'status': 'unsupported_inventory', 'write_dispatched': False, 'motion_verified': False}
    by_id = {c['component_id']: c for c in components}
    origin, scale = _frame(components)
    pairs = defaultdict(lambda: {'rows': [], 'mates': [], 'issues': []})
    problems, omitted = [], []
    for mate in mates:
        evidence = {k: mate.get(k) for k in ('native_feature_id', 'name', 'type', 'type_name')}
        if mate.get('suppressed') is True:
            omitted.append({**evidence, 'reason': 'suppressed'})
            continue
        if mate.get('suppressed') is not False or type(mate.get('error')) is not int:
            omitted.append({**evidence, 'reason': 'native_activity_or_health_not_observed'})
            continue
        if mate.get('error') not in (0, None) or mate.get('warning'):
            problems.append({**evidence, 'reason': 'native_mate_health', 'error': mate.get('error'), 'warning': mate.get('warning')})
            continue
        entities = mate.get('entities') or []
        cids = [e.get('component_id') for e in entities]
        if len(entities) != 2 or len(set(cids)) != 2 or any(cid not in by_id for cid in cids):
            omitted.append({**evidence, 'reason': 'not_two_observed_top_level_components'})
            continue
        key = tuple(sorted(cids)); pair = pairs[key]
        if cids != list(key):
            entities = list(reversed(entities))
        pair['mates'].append(evidence)
        try:
            pair['rows'].extend(_rows(mate, entities, origin, scale))
        except (ValueError, TypeError, KeyError) as error:
            issue = {**evidence, 'reason': str(error)}
            pair['issues'].append(issue); omitted.append(issue)
    for pair in pairs.values():
        pair['basis'] = basis(pair['rows'])
        pair['rank'] = len(pair['basis'])
    # Exact relative rigidity within this supported local model. No graph edge
    # alone, mate count, name, or fully-constrained flag creates a rigid group.
    clusters = [{cid} for cid in ids]
    changed = True
    while changed:
        changed = False
        for i in range(len(clusters)):
            if changed:
                break
            for j in range(i+1, len(clusters)):
                rows = [r for (a, b), p in pairs.items() if (a in clusters[i] and b in clusters[j]) or (b in clusters[i] and a in clusters[j]) for r in p['basis']]
                if len(basis(rows)) == 6:
                    clusters[i] |= clusters[j]; clusters.pop(j); changed = True; break
    labels = defaultdict(set)
    for c in components:
        if c.get('fixed_component') is True:
            labels[c['component_id']].add('stationary')
    for label, members in (seeds or {}).items():
        for cid in members:
            if cid in by_id:
                labels[cid].add(label)
    cluster_rows = []
    for cluster in clusters:
        effective = set().union(*(labels[cid] for cid in cluster))
        # A task may deliberately release an originally fixed rotor. Distinguish
        # that visible planned release from a second *outside* fixed component.
        moving = effective-{'stationary'}
        fixed_outside = [cid for cid in cluster if by_id[cid].get('fixed_component') and cid not in {m for members in (seeds or {}).values() for m in members}]
        if len(moving) == 1 and not fixed_outside:
            effective = moving
        row = {'components': sorted(cluster), 'instances': [by_id[cid]['instance'] for cid in sorted(cluster)],
               'suggested_groups': sorted(effective), 'status': 'group_conflict' if len(effective) > 1 else 'supported_rigid_relation',
               'motion_verified': False}
        cluster_rows.append(row)
        for cid in cluster:
            labels[cid] = set(effective)
    # Anchoring through independent constraints on several already-rigid peers.
    changed = True
    while changed:
        changed = False
        for cluster in clusters:
            if any(labels[cid] for cid in cluster):
                continue
            candidates = defaultdict(list)
            for (a, b), pair in pairs.items():
                own, peer = (a, b) if a in cluster and b not in cluster else (b, a) if b in cluster and a not in cluster else (None, None)
                if own and len(labels[peer]) == 1:
                    candidates[next(iter(labels[peer]))].extend(pair['basis'])
            proven = [label for label, rows in candidates.items() if len(basis(rows)) == 6]
            if proven:
                for cid in cluster:
                    labels[cid] = set(proven)
                changed = True
    component_rows, questions, suggestions = [], [], []
    for cid in ids:
        c = by_id[cid]; linked = []
        evidence_by_group = defaultdict(list)
        for (a, b), pair in pairs.items():
            if cid not in (a, b):
                continue
            peer = b if cid == a else a
            linked.append({'peer': peer, 'instance': by_id[peer]['instance'], 'supported_local_rank': pair['rank'],
                           'native_feature_ids': [m['native_feature_id'] for m in pair['mates']], 'issues': pair['issues']})
            if len(labels[peer]) == 1:
                evidence_by_group[next(iter(labels[peer]))].extend(pair['basis'])
        group_ranks = {label: len(basis(rows)) for label, rows in evidence_by_group.items()}
        group = next(iter(labels[cid])) if len(labels[cid]) == 1 else None
        state = 'group_conflict' if len(labels[cid]) > 1 else 'supported_group_recommendation' if group else 'mechanical_intent_required'
        preferred = sorted(group_ranks, key=lambda k: (-group_ranks[k], k))
        row = {'component_id': cid, 'instance': c['instance'], 'fixed_component': c.get('fixed_component'),
               'native_constraint_state': c.get('constraint_state', {'status': 'not_observed'}),
               'status': state, 'suggested_group': group, 'constraint_rank_by_neighbor_group': group_ranks,
               'mate_links': linked, 'global_remaining_DOF': None, 'motion_verified': False,
               'group_seed_is_rigidity_proof':False,
               'group_source':'proposed_intent_seed' if any(cid in members for members in (seeds or {}).values()) else 'native_fixed_flag' if c.get('fixed_component') else 'supported_local_constraint_relations' if group else 'not_determined'}
        if group is None:
            question = {'component_id': cid, 'instance': c['instance'], 'candidate_groups': preferred,
                        'reason': 'conflicting_rigid_group_seeds' if state == 'group_conflict' else 'existing_constraints_do_not_determine_design_intent',
                        'supported_rank_by_group': group_ranks,
                        'recommended_question': '这个组件应与哪一侧保持相对静止，还是应保留独立运动？'}
            questions.append(question)
            if len(preferred) == 1 and group_ranks[preferred[0]] > 0:
                rank = group_ranks[preferred[0]]
                suggestions.append({'component_id': cid, 'instance': c['instance'], 'proposed_group': preferred[0],
                    'supported_local_rank': rank, 'missing_relative_constraints_if_rigid_intent_confirmed': 6-rank,
                    'existing_mates_action': 'reuse', 'proposed_action': 'inspect_reference_then_preview_minimum_complement',
                    'requires_mechanical_intent_confirmation': True, 'fix_component_recommended': False,
                    'automatic_write_allowed': False})
        component_rows.append(row)
    structure=structural_relations or {}
    component_features={r['native_feature_id']:r for r in structure.get('components',[])}
    patterns={r['native_feature_id']:r for r in structure.get('patterns',[]) if r.get('suppressed') is False}
    dependencies=[]
    for observed in structure.get('components',[]):
        if not observed.get('is_pattern_instance'):
            continue
        parent_ids={p['native_feature_id'] for p in observed.get('parent_features',[])}
        matched=[p for pid,p in patterns.items() if pid in parent_ids or observed['native_feature_id'] in {f['native_feature_id'] for f in p.get('child_features',[])}]
        seeds_found={cid for p in matched for cid in p.get('seed_component_ids',[]) if cid in by_id}
        seeds_found.update(component_features[pid]['component_id'] for pid in parent_ids if pid in component_features)
        seeds_found.discard(observed['component_id'])
        dependencies.append({'component_id':observed['component_id'],'instance':observed['instance'],
            'seed_component_ids':sorted(seeds_found),'pattern_features':[p['native_feature_id'] for p in matched],
            'status':'native_dependency_observed' if seeds_found else 'pattern_instance_seed_unresolved',
            'missing_mates_proven':False,'rigid_motion_proven':False,'automatic_fix_allowed':False})
    grouped_questions=defaultdict(list)
    for q in questions:
        grouped_questions[(tuple(q['candidate_groups']),q['reason'])].append(q)
    question_groups=[{'candidate_groups':list(key[0]),'reason':key[1],
        'components':[{'component_id':q['component_id'],'instance':q['instance']} for q in rows],
        'question':'请按机械用途确认这一组应随轴运动、相对支承静止，还是保留独立运动；可整体说明，AI生成组件清单。'}
        for key,rows in sorted(grouped_questions.items())]
    fingerprint = hashlib.sha256(json.dumps({'components': components, 'mates': mates, 'seeds': seeds or {},'structural_relations':structure}, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {'schema_version': 1, 'task_name': '通用装配约束检查与配合补齐——减速器首例',
        'status': 'partial_review_required' if not inventory_complete else 'review_required' if questions or problems else 'supported_relations_classified_pending_native_validation',
        'input_sha256': fingerprint, 'inventory_complete': bool(inventory_complete),
        'counts': {'components': len(components), 'mates': len(mates), 'rigid_clusters': len(clusters),
                   'classified_components': sum(r['suggested_group'] is not None for r in component_rows),
                   'mechanical_questions': len(questions), 'minimum_complement_suggestions': len(suggestions),
                   'mate_health_issues': len(problems), 'omitted_constraints': len(omitted),
                   'mechanical_question_groups':len(question_groups),'pattern_instances':len(dependencies)},
        'groups': {label: [r['component_id'] for r in component_rows if r['suggested_group'] == label] for label in sorted(set().union(*labels.values()) if labels else [])},
        'components': component_rows, 'rigid_clusters': cluster_rows,
        'pair_constraints': [{'components': list(key), 'instances': [by_id[cid]['instance'] for cid in key],
            'supported_local_rank': p['rank'], 'relative_DOF_upper_bound_supported_model': 6-p['rank'],
            'native_mates': p['mates'], 'issues': p['issues'], 'redundant_mate_proven': False} for key, p in sorted(pairs.items())],
        'questions': questions, 'question_groups':question_groups,'pattern_dependencies':dependencies,
        'completion_suggestions': suggestions, 'mate_health_issues': problems, 'omitted_constraints': omitted,
        'analysis_scope': 'local_linearized_planar_concentric_and_rigid_constraints_not_global_solver_or_design_intent',
        'numerics': {'origin_m': origin, 'characteristic_length_m': scale, 'rank_tolerance': 1e-8},
        'global_remaining_DOF': None, 'redundancy_or_compatibility_verified': False,
        'classification_is_design_intent': False, 'write_dispatched': False, 'motion_verified': False,
        'classification_complete_means_constraints_complete':False,
        'blanket_fix_recommended': False, 'unsupported_constraints_are_not_absent': True}


def summary(report, limit=8):
    """Small dialogue view; full evidence retained by the owner, never rescan."""
    return {k: report[k] for k in ('schema_version', 'status', 'input_sha256', 'counts', 'analysis_scope',
            'inventory_complete', 'global_remaining_DOF', 'write_dispatched', 'motion_verified', 'blanket_fix_recommended') if k in report} | {
        'mechanical_questions': report.get('questions', [])[:limit],
        'mechanical_question_groups':[{**{k:v for k,v in group.items() if k!='components'},
            'component_count':len(group['components']),'examples':[r['instance'] for r in group['components'][:4]]}
            for group in report.get('question_groups',[])[:limit]],
        'questions_truncated': len(report.get('questions', [])) > limit,
        'minimum_complement_examples': report.get('completion_suggestions', [])[:limit],
        'next_step': 'AI解释已有配合和分组证据，集中澄清运动归属；复用既有约束，确认后只补必要约束，不能把全部附件固定作为补配合。'}
