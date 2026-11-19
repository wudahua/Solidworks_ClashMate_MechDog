"""Bounded four-output aperture verification on a saved guided mechanism."""
import csv
import json
import math
import uuid

from . import core, geometry_audit as geometry
from .task_engine import matching_components, short_name
from .. import connection_trials as trials


STROKES_MM = (5., 10., 20.)
GAP_TOLERANCE_MM = .01


def require(condition, reason, details=None):
    if not condition:
        raise core.StopBatch('CONNECTION_EVIDENCE_FAILED', '开口试算证据无法确认。',
                             {'reason': reason, **(details or {})})


def projection(point, center, axis):
    relative = geometry.sub(point, center)
    return geometry.sub(relative, [u * geometry.dot(relative, axis) for u in axis])


def measure(poses, tips, axis, driver, pairs):
    center = poses[driver][9:12]
    vectors = {name: projection(trials.point(poses[name], point), center, axis) for name, point in tips.items()}
    return [1000 * math.dist(vectors[a], vectors[b]) for a, b in pairs], {
        name: 1000 * geometry.norm(v) for name, v in vectors.items()}


def bind(session, candidate, targets, hints, tip_end):
    inspection = session.initial_inspection
    active = [c for c in inspection['components'] if c.get('loaded') and not c.get('suppressed')]
    require(6 <= len(active) <= 128 and len(active) == len(inspection['components']) and
            all(not c.get('subassembly') and not c.get('speedpak') for c in active), 'flat_resolved_components_required')
    driver = candidate['drive']['component_id']
    reference = candidate['reference']['component_id']
    require(candidate['reference']['fixed_component'] is True, 'fixed_reference_required')
    if hints is None:
        groups = {}
        for c in active:
            if c['fixed_component'] is False and c['component_id'] != driver:
                groups.setdefault((c['path'], c['configuration']), []).append(c)
        choices = [group for group in groups.values() if len(group) == 4]
        poses_by_id = {c['component_id']: c['transform'] for c in active}
        axis = candidate['axis_global']
        center = poses_by_id[driver][9:12]
        reach = sorted((min(geometry.norm(projection(c['transform'][9:12], center, axis)) for c in group), index)
                       for index, group in enumerate(choices))
        require(bool(reach) and (len(reach) == 1 or reach[-1][0] > 1.15 * reach[-2][0]), 'jaw_group_ambiguous',
                {'four_instance_groups': [[short_name(c['instance']) for c in group] for group in choices]})
        selected = choices[reach[-1][1]]
        recommendation = 'unique_outermost_four_instance_floating_part_group'
    else:
        selected = []
        for hint in hints:
            matched = matching_components(active, hint, False)
            require(len(matched) == 1, 'jaw_name_not_unique', {'hint': hint, 'candidates': [short_name(c['instance']) for c in matched]})
            selected.append(matched[0])
        recommendation = 'conversation_selected_output_occurrences'
    require(len({c['component_id'] for c in selected}) == 4 and all(c['component_id'] not in {driver, reference} for c in selected),
            'four_distinct_jaws_required')
    names = {c['component_id']: c['instance'] for c in active}
    initial = {c['instance']: c['transform'] for c in active}
    axis = list(candidate['axis_global'])
    require(abs(geometry.norm(axis) - 1) < 1e-6, 'unit_drive_axis_required')
    # Make the measuring end independent of which of the parallel faces is used.
    if next(v for v in axis if abs(v) > 1e-8) < 0:
        axis = [-v for v in axis]
    center = initial[names[driver]][9:12]
    chosen = [c['component_id'] for c in selected]
    native = session.call('_aperture_vertices', model_id=session.model, components_json=json.dumps(chosen))
    require({r['component_id'] for r in native['outputs']} == set(chosen) and len(native['outputs']) == 4, 'native_jaw_vertex_scope_mismatch')
    tips = {}
    for row in native['outputs']:
        name = names[row['component_id']]
        require(row['instance'] == name, 'native_jaw_component_mismatch')
        vertices = [(point, trials.point(initial[name], point)) for point in row['local_points_m']]
        heights = [geometry.dot(point, axis) for _, point in vertices]
        lo, hi = min(heights), max(heights)
        verified_end = [v for v, height in zip(vertices, heights) if
                        (height <= lo + .25 * (hi - lo) if tip_end == 'axis_min' else height >= hi - .25 * (hi - lo))]
        ranked = [(geometry.norm(projection(point, center, axis)), local) for local, point in verified_end]
        nearest = min(radius for radius, _ in ranked)
        tips[name] = max(local for radius, local in ranked if radius - nearest <= 1e-9)
    a, b, c, d = sorted(tips)
    matches = [[(a, b), (c, d)], [(a, c), (b, d)], [(a, d), (b, c)]]
    vectors = {name: projection(trials.point(initial[name], point), center, axis) for name, point in tips.items()}
    require(min(map(geometry.norm, vectors.values())) > .001, 'jaw_tips_not_offset_from_drive_axis')

    def cosine(pair):
        u, v = (vectors[n] for n in pair)
        return geometry.dot(u, v) / (geometry.norm(u) * geometry.norm(v))

    opposite = [pairs for pairs in matches if all(cosine(pair) < -.9 for pair in pairs)]
    require(len(opposite) == 1, 'opposed_tip_pairs_ambiguous')
    pairs = sorted(opposite[0], key=lambda pair: (math.dist(*(vectors[n] for n in pair)), pair))
    opened, _ = measure(initial, tips, axis, names[driver], pairs)
    require(all(target < gap - GAP_TOLERANCE_MM for target, gap in zip(targets, opened)), 'target_must_reduce_both_openings',
            {'initial_openings_mm': opened, 'requested_max_openings_mm': targets})
    return {'target_openings_mm': targets, 'opening_mm': opened, 'pairs': pairs, 'tip_local_points_m': tips, 'tip_end': tip_end,
            'projection_axis_global': axis, 'driver_name': names[driver], 'reference_name': names[reference],
            'selection_basis': recommendation, 'probe_strokes_mm': list(STROKES_MM), 'full_cycle_duration_s': 4., 'full_cycle_fps': 10,
            'gap_tolerance_mm': GAP_TOLERANCE_MM, 'scope': 'four_tip_projected_aperture_on_fixed_reference'}


def samples(session, native, card, expected_axis, stroke, step):
    directory = core.no_links(session.runtime / 'runs' / native['run_id'])
    poses_path = core.no_links(native['poses_path'])
    clashes_path = core.no_links(native['interference_path'])
    require(poses_path == directory / 'aperture-poses.csv' and clashes_path == directory / 'aperture-interference.json', 'native_aperture_artifact_binding_invalid')
    require(native.get('initial_restored') is True and native.get('frame_count') == 40 // step + 1 and native.get('stroke_mm') == stroke and
            native.get('driver') == card['driver_name'] and native.get('reference') == card['reference_name'], 'native_aperture_receipt_mismatch')
    initial = {r['instance']: r['transform'] for r in session.initial_inspection['components']}
    poses = {}
    with poses_path.open(encoding='utf-8-sig', newline='') as file:
        for row in csv.DictReader(file):
            index = int(row['frame'])
            frame = poses.setdefault(index, {})
            require(row['instance'] not in frame and abs(float(row['time_s']) - index / 10) < 1e-7, 'aperture_frame_scope_mismatch')
            frame[row['instance']] = [float(row[f'r{i}{j}']) for i in range(3) for j in range(3)] + [float(row[k]) for k in ('x_m', 'y_m', 'z_m')] + [1., 0., 0., 0.]
    scan = core.read(clashes_path)
    indices = list(range(0, 41, step))
    require(sorted(poses) == indices and [s['frame'] for s in scan['rows']] == indices and scan['threshold_mm3'] == .01, 'aperture_frame_grid_mismatch')
    from .motion_tasks import require_same_poses
    for index in (0, 40):
        require_same_poses({k: p[:12] for k, p in initial.items()}, {k: v[:12] for k, v in poses[index].items()}, 'aperture_cycle_saved_start_and_return')
    result = []
    driver = card['driver_name']
    for index, hit in zip(indices, scan['rows']):
        frame = poses[index]
        require(frame.keys() == initial.keys(), 'aperture_component_scope_mismatch')
        for name, pose in frame.items():
            trials.validate(pose)
            previous = initial[name]
            q = geometry.quat(geometry.mm(geometry.transpose(trials.rotation(previous)), trials.rotation(pose)))
            require(math.dist(pose[9:12], previous[9:12]) <= .05 and 2 * math.atan2(geometry.norm(q[1:]), abs(q[0])) <= math.pi / 12, 'aperture_component_motion_envelope_exceeded')
        actual = 1000 * geometry.dot(geometry.sub(frame[driver][9:12], initial[driver][9:12]), expected_axis)
        desired = stroke * (1 - math.cos(math.pi * index / 20)) / 2
        require(abs(actual - desired) <= .005, 'aperture_drive_profile_mismatch', {'frame': index, 'requested_mm': desired, 'observed_mm': actual})
        gaps, radial = measure(frame, card['tip_local_points_m'], card['projection_axis_global'], driver, card['pairs'])
        result.append({'frame': index, 'time_s': index / 10, 'input_mm': actual, 'gaps_mm': gaps, 'tip_radii_mm': radial,
                       'interferences_mm3': hit['new_or_increased']})
    middle = result[len(result) // 2]
    require(all(result[0]['tip_radii_mm'][name] - radial > .01 for name, radial in middle['tip_radii_mm'].items()), 'aperture_four_jaws_did_not_close')
    for a, b in zip(result, result[1:]):
        direction = 1 if a['frame'] < 20 else -1
        require(all(direction * (a['tip_radii_mm'][name] - value) >= -.01 for name, value in b['tip_radii_mm'].items()),
                'aperture_jaw_motion_not_synchronous')
    return result, scan['baseline_mm3']


def reached(row, targets):
    return all(gap <= target + GAP_TOLERANCE_MM for gap, target in zip(row['gaps_mm'], targets))


def clear_prefix(rows):
    safe = []
    for row in rows:
        if row['frame'] > 20:
            break
        if row['interferences_mm3']:
            return safe, row
        safe.append(row)
    return safe, None


def run(session, proposal, drive, reference):
    card = proposal['aperture_validation']
    targets = card['target_openings_mm']
    binding = proposal['direction_binding']
    direction = [binding['expected_sign_about_selected_native_axis'] * v for v in drive['axis_global']]
    trials_report = []
    best = None
    inspection = getattr(session, 'initial_inspection', None) or {}
    discard_checkpoint = None
    if any(mate.get('suppressed') is True for mate in inspection.get('mates', [])):
        checkpoint = session.call('create_model_checkpoint', model_id=session.model)
        discard_checkpoint = checkpoint['checkpoint_id']
        core.write(session.folder / '开口试算恢复检查点.json', checkpoint)

    def native_cycle(stroke, final):
        run_id = uuid.uuid4().hex
        native = session.call('_run_aperture_cycle', model_id=session.model, driver_id=drive['component_id'],
                              reference_id=reference['component_id'], entity_id=drive['entity_id'],
                              reverse=binding['native_reverse_direction'], stroke_mm=stroke, frame_step=1 if final else 5,
                              candidate=final, run_id=run_id, job_id=run_id, discard_checkpoint=discard_checkpoint)
        return native

    for stroke in STROKES_MM:
        session.state('solving', f'正在试算 {stroke:g} mm 行程并扫描新增干涉。')
        native = native_cycle(stroke, False)
        rows, _ = samples(session, native, card, direction, stroke, 5)
        safe, blocked = clear_prefix(rows)
        if safe:
            best = safe[-1]
        trials_report.append({'run_id': native['run_id'], 'stroke_mm': stroke, 'last_clear_closing_sample': best,
                              'first_sample_with_interference': blocked})
        core.write(session.folder / '开口分段试算.json', trials_report)
        selected = next((row for row in safe if row['frame'] and reached(row, targets)), None)
        if selected or blocked:
            break
    if selected is None:
        return {'declared_scope_passed': False, 'scope': card['scope'], 'target_openings_mm': targets,
                'failure_reason': 'new_interference' if blocked else 'target_not_reached_within_20_mm',
                'last_clear_probe_sample': best, 'first_sample_with_interference': blocked, 'probes': trials_report,
                'native_study_saved': False}
    exact = min(stroke, round(selected['input_mm'], 6))
    session.state('solving', f'正在用 {exact:g} mm 行程验证 41 帧完整开合。')
    native = native_cycle(exact, True)
    try:
        rows, inherited = samples(session, native, card, direction, exact, 1)
        blocked = next((row for row in rows if row['interferences_mm3']), None)
        midpoint = rows[20]
        verified = blocked is None and reached(midpoint, targets)
        core.write(session.folder / '开口逐帧验证.json', {'rows': rows, 'inherited_mm3': inherited, 'verified': verified})
    except Exception:
        session.call('_finish_aperture_cycle', model_id=session.model, study=native['Study'], keep=False)
        raise
    saved = session.call('_finish_aperture_cycle', model_id=session.model, study=native['Study'], keep=verified)
    require(saved.get('saved') is verified, 'aperture_save_state_mismatch')
    result = {'declared_scope_passed': verified, 'scope': card['scope'], 'run_id': native['run_id'], 'native_study_saved': verified,
              'target_openings_mm': targets, 'initial_openings_mm': rows[0]['gaps_mm'], 'achieved_openings_mm': midpoint['gaps_mm'],
              'return_openings_mm': rows[-1]['gaps_mm'], 'input_stroke_mm': midpoint['input_mm'], 'frames': len(rows),
              'first_sample_with_interference': blocked, 'probes': trials_report, 'inherited_interferences_mm3': inherited}
    if not verified:
        result['failure_reason'] = 'new_interference' if blocked else 'target_not_reached_on_full_cycle'
        result['last_clear_probe_sample'] = best
        return result
    table = session.folder / '四指开合测量.csv'
    with table.open('w', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['frame', 'time_s', 'input_mm', 'opening_1_mm', 'opening_2_mm', *rows[0]['tip_radii_mm']])
        for row in rows:
            writer.writerow([row['frame'], row['time_s'], row['input_mm'], *row['gaps_mm'], *row['tip_radii_mm'].values()])
    return {**result, 'study': native['Study'], 'saved_assembly_sha256': saved['sha256'],
            'measurement_table': {'path': str(table), 'sha256': core.digest(table)}, 'four_tip_motion_verified': True,
            'design_full_travel_certified': False, 'contact_force_verified': False}
