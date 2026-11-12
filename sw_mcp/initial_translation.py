"""Explicit, bounded translation-only initialization for zero-mate models.

The result is a mathematical prediction, not a native pose or executable mate
plan. It cannot expand a coaxial tolerance, move a fixed body, rotate parts,
or substitute for native readback and a separately confirmed initialization.
"""
import copy
import math
from . import assembly_connections as joints, assembly_hierarchy
from .connection_trials import validate


class InitialTranslationError(ValueError):
    def __init__(self, reason, **diagnostics):
        self.diagnostics = diagnostics
        super().__init__(reason)


def _dot(a, b):return sum(x*y for x, y in zip(a, b))
def _norm(a):return math.sqrt(_dot(a, a))


def _lines(a, b, hint, budget):
    found = []
    for fa in a.get('cylinders', []):
        for fb in b.get('cylinders', []):
            aa, ab = joints.ac.unit(fa['axis_global']), joints.ac.unit(fb['axis_global'])
            if _norm(joints.ac.cross(aa, ab)) > 1e-10:continue
            if hint is not None and abs(_dot(aa, joints.ac.unit(hint))) < 1-1e-8:continue
            pa, pb = fa['reference_point_global_m'], fb['reference_point_global_m']
            gap = _norm(joints.ac.cross([pa[i]-pb[i] for i in range(3)], aa))
            if gap > 2*budget:continue  # Both floating bodies may share a correction.
            if any(joints._line_matches(fa, v['geometry_a']) and joints._line_matches(fb, v['geometry_b']) for v in found):continue
            found.append({'axis_global': aa, 'point_a': list(pa), 'point_b': list(pb),
                          'component_a': a['component_id'], 'component_b': b['component_id'],
                          'geometry_a': fa, 'geometry_b': fb, 'radial_gap_m': gap,
                          'source': 'observed_parallel_cylinder_lines_not_yet_coaxial_proof'})
    return [{'candidate_id': 'translation-axis-'+str(i+1), **v} for i, v in enumerate(found)]


def _solve(ids, fixed, rigid, lines, budget):
    indices = {cid: i for i, cid in enumerate(ids)}; width = 3*len(ids); equations = []
    def add(a, b, normal, rhs):
        values = [0.]*width
        for k, x in enumerate(normal):
            values[3*indices[a]+k] += x
            if b is not None:values[3*indices[b]+k] -= x
        equations.append((values, rhs))
    for cid in fixed:
        for k in range(3):add(cid, None, [float(i == k) for i in range(3)], 0.)
    for a, b in rigid:
        for k in range(3):add(a, b, [float(i == k) for i in range(3)], 0.)
    for line in lines:
        axis = joints.ac.unit(line['axis_global'])
        delta = [line['point_a'][i]-line['point_b'][i] for i in range(3)]
        for normal in joints.ac.perpendiculars(axis):
            add(line['component_a'], line['component_b'], normal, -_dot(normal, delta))
    basis = []
    for source, rhs in equations:
        values = list(source); beta = rhs
        for _ in range(2):
            for q, known in basis:
                factor = _dot(values, q)
                values = [x-factor*y for x, y in zip(values, q)]; beta -= factor*known
        norm = _norm(values)
        if norm < 1e-10:
            if abs(beta) > 1e-10:raise InitialTranslationError('initial_translation_equations_inconsistent')
        else:basis.append(([x/norm for x in values], beta/norm))
    solution = [sum(beta*q[i] for q, beta in basis) for i in range(width)]
    deltas = {cid: solution[3*i:3*i+3] for cid, i in indices.items()}
    for cid in fixed:
        if _norm(deltas[cid]) > 1e-11:raise InitialTranslationError('initial_translation_fixed_body_would_move')
        deltas[cid] = [0., 0., 0.]
    for cid, delta in deltas.items():
        if _norm(delta) < 1e-12:deltas[cid] = [0., 0., 0.]
    solution = [x for cid in ids for x in deltas[cid]]
    residual = max([abs(_dot(row, solution)-rhs) for row, rhs in equations] or [0.])
    maximum = max([_norm(d) for d in deltas.values()] or [0.])
    if residual > 1e-10:raise InitialTranslationError('initial_translation_equation_residual_unverified')
    if maximum > budget:raise InitialTranslationError('initial_translation_budget_exceeded', maximum_translation_m=maximum, budget_m=budget)
    return deltas, residual


def propose(survey, intents, maximum_translation_mm=.001):
    if type(maximum_translation_mm) not in (int, float) or not math.isfinite(maximum_translation_mm) or not 0 < maximum_translation_mm <= .01:
        raise InitialTranslationError('initial_translation_budget_invalid')
    cs = survey.get('components') or []; ids = [c.get('component_id') for c in cs]
    if not survey.get('inventory_complete') or not 1 <= len(cs) <= 128 or len(set(ids)) != len(ids) or any(not isinstance(cid, str) or not cid for cid in ids):
        raise InitialTranslationError('initial_translation_inventory_incomplete')
    if survey.get('mates'):
        raise InitialTranslationError('initial_translation_requires_zero_existing_mates')
    if any(c.get('is_pattern_instance') is True for c in (survey.get('structural_relations') or {}).get('components',[])):
        raise InitialTranslationError('initial_translation_pattern_relations_unsupported')
    hierarchy = assembly_hierarchy.analyze(cs)
    if any(hierarchy['parents'][cid] is not None or c.get('subassembly') is True or c.get('document_type') == 'assembly' for cid, c in zip(ids, cs)):
        raise InitialTranslationError('initial_translation_requires_flat_rigid_parts')
    by = {c['component_id']: c for c in cs}
    for c in cs:
        try:validate(c['transform'])
        except (KeyError,ValueError,TypeError) as error:raise InitialTranslationError('initial_translation_pose_invalid') from error
        if type(c.get('fixed_component')) is not bool:raise InitialTranslationError('initial_translation_fixed_state_unobserved')
    fixed = [c['component_id'] for c in cs if c['fixed_component']]
    if not fixed:raise InitialTranslationError('initial_translation_requires_fixed_reference')
    if not isinstance(intents, list) or not 1 <= len(intents) <= 128:raise InitialTranslationError('initial_translation_goal_budget')
    lines = []; rigid = []; budget = maximum_translation_mm/1000
    for index, goal in enumerate(intents):
        if not isinstance(goal,dict) or set(goal)-{'component_a','component_b','kind','axis_hint','candidate_id'}:
            raise InitialTranslationError('initial_translation_goal_invalid')
        a, b, kind = goal.get('component_a'), goal.get('component_b'), goal.get('kind')
        if a not in by or b not in by or a == b or kind not in joints.KINDS:raise InitialTranslationError('initial_translation_goal_invalid')
        if kind == 'rigid':rigid.append((a, b));continue
        choices = _lines(by[a], by[b], goal.get('axis_hint'), budget)
        selected = goal.get('candidate_id')
        if selected:choices = [v for v in choices if v['candidate_id'] == selected]
        if not choices and kind == 'prismatic' and goal.get('axis_hint') is not None and not selected:
            lines.append({'component_a': a, 'component_b': b, 'axis_global': joints.ac.unit(goal['axis_hint']),
                          'point_a': [0., 0., 0.], 'point_b': [0., 0., 0.],
                          'source': 'preserve_current_declared_slide_offset_not_rotation_axis'});continue
        if len(choices) != 1:
            raise InitialTranslationError('initial_translation_material_axis_selection_required', goal_index=index,
                                           component_a=a, component_b=b,
                                           choices=[{k: v for k, v in item.items() if not k.startswith('geometry_')} for item in choices])
        lines.append(choices[0])
    deltas, residual = _solve(ids, fixed, rigid, lines, budget)
    virtual = copy.deepcopy(survey); entries = []
    for c in virtual['components']:
        delta = deltas[c['component_id']]; before = list(c['transform']); seen = set()
        for i in range(3):
            c['transform'][9+i] += delta[i]
            if c.get('box') is not None:c['box'][i] += delta[i]; c['box'][i+3] += delta[i]
        for shape in c.get('cylinders', [])+c.get('planes', [])+c.get('completion_planes', []):
            if id(shape) in seen:continue
            seen.add(id(shape))
            shape['reference_point_global_m'] = [shape['reference_point_global_m'][i]+delta[i] for i in range(3)]
        entries.append({'component_id': c['component_id'], 'instance': c['instance'], 'delta_m': delta,
                        'before': before, 'after': list(c['transform']), 'fixed': c['fixed_component']})
    proof = {'schema_version': 1, 'mode': 'explicit_zero_mate_translation_only',
             'maximum_translation_m': max(_norm(v) for v in deltas.values()),
             'translation_budget_m': budget, 'maximum_rotation_rad': 0., 'equation_residual_m': residual,
             'moved_components': sum(_norm(v) > 0 for v in deltas.values()), 'entries': entries,
             'requires_alignment_confirmation': any(_norm(v) > 0 for v in deltas.values()),
             'native_pose_verified': False, 'coaxial_tolerance_relaxed': False, 'source_files_written': False,
             'scope': 'mathematical_prediction_requires_original_state_binding_and_complete_native_pose_readback'}
    return virtual, proof


def verify_native(proof,before_components,after_components,solver_readback=False):
    """Separate command initialization from later assembly-solver readback.

    The actual initialization remains translation-only with a strict native
    rotation readback. Later mate solves have an independently bounded numeric
    residual: <=2nm displacement of any material point bounded by an observed
    component box, and the unchanged mechanical angular tolerance. A uniform
    coefficient cutoff is not a physical displacement measure for parts of
    different sizes. The matrix-norm bound includes shear/scale roundoff too.
    The original predicted baseline, fixed poses and absolute movement budget
    are never advanced or widened.
    """
    entries={v['component_id']:v for v in proof['entries']}
    before={c['component_id']:c for c in before_components};after={c['component_id']:c for c in after_components}
    if not 1<=len(entries)<=128 or len(entries)!=len(proof['entries']) or set(entries)!=set(before) or set(entries)!=set(after):
        raise InitialTranslationError('initial_translation_native_inventory_mismatch')
    maximum=0.;checks=[];maximum_solver_rotation=0.;maximum_material_residual=0.
    for cid,e in entries.items():
        a,b=before[cid],after[cid];validate(a['transform']);validate(b['transform'])
        if (a['instance']!=e['instance'] or b['instance']!=e['instance'] or type(a['fixed_component']) is not bool or
                a['fixed_component']!=e['fixed'] or b['fixed_component']!=e['fixed']):
            raise InitialTranslationError('initial_translation_native_fixed_or_instance_mismatch')
        if any(abs(x-y)>1e-12 for x,y in zip(e['before'],a['transform'])):
            raise InitialTranslationError('initial_translation_original_pose_mismatch')
        solved=solver_readback and not e['fixed']
        rotation_delta=max(abs(b['transform'][i]-e['after'][i]) for i in range(9))
        shift=math.dist(b['transform'][9:12],e['after'][9:12]);angle=0.;material_residual=shift
        if rotation_delta>0 and solved:
            from .conversation import geometry_audit as g
            from .connection_trials import rotation
            box=a.get('box')
            if not isinstance(box,list) or len(box)!=6 or any(type(x) not in (int,float) or not math.isfinite(x) for x in box) or any(box[i]>box[i+3] for i in range(3)):
                raise InitialTranslationError('initial_translation_solver_box_unobserved',instance=e['instance'])
            radius=max(math.dist([box[0+3*i],box[1+3*j],box[2+3*k]],a['transform'][9:12]) for i in (0,1) for j in (0,1) for k in (0,1))
            if radius<=0:raise InitialTranslationError('initial_translation_solver_box_unobserved',instance=e['instance'])
            q=g.quat(g.mm(g.transpose(rotation(e['after'])),rotation(b['transform'])))
            angle=2*math.atan2(g.norm(q[1:]),abs(q[0]))
            matrix_norm=math.sqrt(sum((b['transform'][i]-e['after'][i])**2 for i in range(9)))
            material_residual=shift+radius*matrix_norm
        from .connection_trials import ANGLE_TOLERANCE_RAD
        invalid_pose=(material_residual>2e-9 or angle>ANGLE_TOLERANCE_RAD if solved else
            rotation_delta>1e-12 or shift>1e-9)
        if invalid_pose or any(abs(b['transform'][i]-e['after'][i])>1e-12 for i in range(12,16)):
            raise InitialTranslationError('initial_translation_native_pose_mismatch',instance=e['instance'],
                rotation_coefficient_delta=rotation_delta,expected_origin_error_m=shift,material_displacement_bound_m=material_residual,
                solver_readback=solver_readback,initialization_rotation_authorized=False)
        delta=[b['transform'][9+i]-a['transform'][9+i] for i in range(3)];distance=_norm(delta)
        if distance>proof['translation_budget_m'] or e['fixed'] and distance>1e-12:
            raise InitialTranslationError('initial_translation_native_budget_or_fixed_mismatch')
        maximum=max(maximum,distance);maximum_solver_rotation=max(maximum_solver_rotation,angle);maximum_material_residual=max(maximum_material_residual,material_residual)
        checks.append({'component_id':cid,'delta_m':delta,'translation_m':distance,'fixed':e['fixed'],
            'solver_rotation_coefficient_delta':rotation_delta,'solver_rotation_rad':angle,'material_residual_bound_m':material_residual})
    return {'passed':True,'all_component_count':len(checks),'maximum_translation_m':maximum,
            'expected_pose_translation_tolerance_m':2e-9 if solver_readback else 1e-9,'rotation_coefficient_tolerance':None if solver_readback else 1e-12,
            'solver_angular_tolerance_rad':ANGLE_TOLERANCE_RAD if solver_readback else None,
            'solver_residual_measure':'origin_error_plus_observed_box_radius_times_Frobenius_norm_of_matrix_difference',
            'solver_readback':solver_readback,'fixed_rotation_coefficient_tolerance':1e-12,
            'material_residual_limit_m':2e-9,'maximum_material_residual_m':maximum_material_residual,
            'maximum_solver_rotation_rad':maximum_solver_rotation,'initialization_rotation_authorized':False,
            'fixed_flags_preserved':True,'checks':checks,'native_readback_verified':True}
