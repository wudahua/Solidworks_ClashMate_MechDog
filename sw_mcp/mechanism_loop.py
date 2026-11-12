"""Planning guard for an explicitly driven, fully declared basic-joint loop.

A local revolute joint need not be independently actuable in a closed loop.
This module never relaxes its geometric constraints or certifies movement:
complete native Motion sampling and all declared joint/output audits remain
mandatory. Unknown native constraints are never treated as absent.
"""
import copy
from . import assembly_connections as joints, constraint_graph
from .assembly_completion import SparseBasis


class LoopReviewError(ValueError):
    def __init__(self, reason, **diagnostics):
        self.diagnostics = diagnostics
        super().__init__(reason)


def _copy_matrix(matrix):
    result = SparseBasis()
    result.pivots = {key: dict(value) for key, value in matrix.pivots.items()}
    return result


def prune_bundles(base, bundles):
    """Remove only entire *new* redundant bundles, never native baseline rows.

    A bundle with positive gain when first selected can become wholly
    redundant after a later multi-row mate. Local greedy gain is insufficient
    to prove a minimal final native construction. Prefer removing scalar
    angular constraints before a material-axis bundle; preserve row span.
    """
    retained=set(range(len(bundles)));removed=[]
    order=sorted(retained,key=lambda i:(len(bundles[i]),i))
    for index in order:
        trial=_copy_matrix(base)
        for other in sorted(retained-{index}):
            for row in bundles[other]:trial.add(row)
        if trial.trial(bundles[index])==0:
            retained.remove(index);removed.append(index)
    matrix=_copy_matrix(base)
    for index in sorted(retained):
        for row in bundles[index]:matrix.add(row)
    return sorted(retained),removed,matrix


def prune_actions(survey,actions):
    graph=constraint_graph.Graph(survey);by=graph.by_id;bundles=[]
    for action in actions:
        entities=[]
        for side in ('a','b'):
            component=by[action['component_'+side]]
            shapes=component.get('cylinders',[])+component.get('completion_planes',[])+component.get('planes',[])
            shape=next((s for s in shapes if s['native_reference']==action['reference_'+side]),None)
            if shape is None:raise LoopReviewError('driven_loop_action_geometry_unobserved')
            entities.append({'geometry':{**shape,'kind':'cylindrical_axis' if action['kind']=='concentric' else 'planar_normal'}})
        kind={'concentric':1,'parallel':3,'distance':5,'perpendicular':2,'angle':6}.get(action['kind'])
        if kind is None:raise LoopReviewError('driven_loop_action_kind_unsupported')
        rows=joints.ac._rows({'type':kind},entities,graph.origin,graph.scale)
        bundles.append(graph.lift(rows,action['component_a'],action['component_b']))
    kept,removed,matrix=prune_bundles(graph.matrix,bundles)
    return [actions[i] for i in kept],matrix,{
        'new_actions_before':len(actions),'new_actions_after':len(kept),
        'removed_new_action_indices':removed,'native_existing_mates_deleted':[],
        'selection_basis':'whole_final_supported_row_span_not_just_positive_incremental_gain',
        'native_compatibility_verified':False,'finite_motion_verified':False,
        'removed_new_actions':[{'index':i,**{k:actions[i][k] for k in ('kind','component_a','component_b')}} for i in removed]}


def ideal_graph(survey, goals):
    """A private graph: never mutate the cached survey model or its basis."""
    graph = constraint_graph.Graph(survey)
    if graph.patterns:raise LoopReviewError('driven_loop_pattern_relations_unsupported')
    if graph.unknown:
        raise LoopReviewError('driven_loop_unknown_constraints', unknown=graph.unknown)
    if any(graph.hierarchy['parents'][cid] is not None or
           c.get('subassembly') is True or c.get('document_type') == 'assembly'
           for cid, c in graph.by_id.items()):
        raise LoopReviewError('driven_loop_requires_flat_rigid_parts')
    if any(m.get('suppressed') is not True and m.get('type') not in {0, 1, 2, 3, 5, 6}
           for m in survey.get('mates', [])):
        raise LoopReviewError('driven_loop_requires_supported_basic_mates')
    for goal in goals:
        if goal['kind'] not in joints.KINDS:
            raise LoopReviewError('driven_loop_invalid_joint_kind')
        rows = joints.target_rows(goal['kind'], goal.get('axis_global'),
                                 goal.get('reference_point_global_m'), graph.origin, graph.scale)
        for row in graph.lift(rows, goal['component_a'], goal['component_b']):
            graph.matrix.add(row)
        a, b = goal['component_a'], goal['component_b']
        graph.adj[a].add(b); graph.adj[b].add(a)
    graph.pairs.clear()
    return graph


def review(survey, goals, proposed_matrix, primary, outputs):
    """Require complete target/action equivalence and a free linear input.

`primary` is an exact current component pair, resolved by the caller from the
prepared task. Outputs must remain connected to that input after removing
stationary bodies. This is planning evidence, never finite-motion evidence.
"""
    if not isinstance(primary, dict) or set(primary) != {'component_a', 'component_b', 'kind'} or primary['kind'] != 'prismatic':
        raise LoopReviewError('driven_loop_requires_explicit_linear_input')
    graph = ideal_graph(survey, goals)
    a, b = primary['component_a'], primary['component_b']
    if a not in graph.by_id or b not in graph.by_id or a == b:
        raise LoopReviewError('driven_loop_invalid_primary_components')
    if graph.by_id[a].get('fixed_component') is not False or graph.rank(b, None) != 6:
        raise LoopReviewError('driven_loop_requires_floating_input_and_grounded_reference')
    matches = [(i, g) for i, g in enumerate(goals) if g['component_a'] == a and g['component_b'] == b and g['kind'] == primary['kind']]
    if len(matches) != 1:
        raise LoopReviewError('driven_loop_primary_goal_not_unique')
    primary_index, input_goal = matches[0]
    input_projection = graph.relative(a, b)
    motion = joints.mobility(input_projection['rows'], graph.origin, graph.scale)
    if motion.get('recommended_joint_type') != 'prismatic' or input_projection['supported_effective_rank'] != 5:
        raise LoopReviewError('driven_loop_primary_input_locked_or_incompatible',
                              input_rank=input_projection['supported_effective_rank'])
    if abs(joints.ac.dot(joints.ac.unit(motion['axis_global']), joints.ac.unit(input_goal['axis_global']))) < 1-1e-8:
        raise LoopReviewError('driven_loop_primary_direction_conflict')
    # Checking both inclusions prevents missing a constraint or accidentally
    # adding constraints beyond the complete declared mechanism.
    if _copy_matrix(proposed_matrix).trial(list(graph.matrix.pivots.values())):
        raise LoopReviewError('driven_loop_declared_targets_not_fulfilled')
    if _copy_matrix(graph.matrix).trial(list(proposed_matrix.pivots.values())):
        raise LoopReviewError('driven_loop_actions_exceed_declared_targets')
    actual = constraint_graph.Graph(survey)
    actual.matrix = _copy_matrix(proposed_matrix)
    if actual.rank(a, b) != 5:
        raise LoopReviewError('driven_loop_actions_lock_primary_input')
    coupled = []
    for i, goal in enumerate(goals):
        rank = actual.rank(goal['component_a'], goal['component_b'])
        expected = 6 if goal['kind'] == 'rigid' else 5
        if rank == 6 and expected == 5 and i != primary_index:
            coupled.append(i)
        elif rank != expected:
            raise LoopReviewError('driven_loop_joint_projection_incompatible', goal_index=i, rank=rank)
    if not isinstance(outputs, list) or not 1 <= len(outputs) <= 16 or any(not isinstance(cid,str) for cid in outputs) or len(set(outputs)) != len(outputs):
        raise LoopReviewError('driven_loop_requires_one_to_16_distinct_outputs')
    grounded = {cid for cid in graph.ids if graph.rank(cid, None) == 6}
    reachable = set(); pending = [a]
    while pending:
        cid = pending.pop()
        if cid in reachable or cid in grounded:continue
        reachable.add(cid); pending.extend(graph.adj[cid]-reachable-grounded)
    bad = [cid for cid in outputs if cid not in graph.by_id or cid not in reachable or cid in {a, b}]
    if bad:
        raise LoopReviewError('driven_loop_output_not_connected_to_moving_input', outputs=bad)
    return {'schema_version': 1, 'mode': 'explicit_primary_driven_basic_joint_loop',
            'primary_goal_index': primary_index, 'primary': copy.deepcopy(primary),
            'axis_global': list(input_goal['axis_global']), 'output_components': list(outputs),
            'grounded_components': sorted(grounded), 'coupled_goal_indices': coupled,
            'coupled_goal_meaning': 'local_joint_not_independently_actuable_in_declared_closed_loop',
            'target_action_spans_equal': True, 'native_full_status_overridden': False,
            'native_motion_required': True, 'all_declared_joint_residuals_required': True,
            'all_output_motion_required': True, 'both_directions_required': True,
            'global_DOF_certified': False, 'finite_motion_verified': False,
            'independent_joint_actuation_certified': False, 'write_dispatched': False}
