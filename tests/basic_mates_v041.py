"""Native mate transactions on project-generated, unmated assemblies only."""
import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sw_mcp.bridge import Bridge, CadError


def main(manifest):
    sources = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    sources = sources.get('assemblies', sources)
    bridge = Bridge(ROOT)
    report = {'all_passed': False, 'cases': [], 'protocol_unmated_source': sources['rotary_unmated']}
    output = ROOT/'runs/basic-mates-v041.json'

    def record(name, data):
        report['cases'].append({'name': name, 'passed': True, 'evidence': data})
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name, 'PASS', flush=True)

    def refs(identifier):
        rows, cursor = [], ''
        while True:
            page = bridge.request('list_mate_references', model_id=identifier, component_id='', kind='', limit=2, cursor=cursor)
            rows += page['entities']
            cursor = page['next_cursor']
            if not cursor:
                return rows

    def pair(rows, kind, axis=None):
        eligible = [r for r in rows if r['kind'] == kind and (axis is None or abs(r['axis_global'][axis]) > .99)]
        fixed = [r for r in eligible if r['fixed_component']]
        moving = [r for r in eligible if not r['fixed_component']]
        return min(((a, b) for a in fixed for b in moving), key=lambda p: sum((a-b)**2 for a, b in zip(p[0]['reference_point_global_m'], p[1]['reference_point_global_m'])))

    def preview(identifier, a, b, kind, baseline='', lock=False, distance=0):
        return bridge.request('preview_mate', model_id=identifier, entity_a=a['entity_id'], entity_b=b['entity_id'], mate_type=kind, alignment='aligned', distance_mm=distance, lock_rotation=lock, baseline_run_id=baseline)

    def reject(name, operation, code, **params):
        try:
            bridge.request(operation, **params)
        except CadError as exc:
            assert exc.code == code, (exc.code, str(exc), exc.diagnostics)
            record(name, {'code': exc.code, 'restoration_status': exc.restoration_status, 'diagnostics': exc.diagnostics})
            return exc
        raise AssertionError(name+' accepted')

    try:
        for kind in ('rotary', 'linear'):
            imported = bridge.request('import_assembly', path=sources[kind+'_unmated'])
            identifier = imported['model_id']
            assert bridge.request('inspect_model', model_id=identifier)['mates'] == []
            rows = refs(identifier)
            assert any(r['fixed_component'] for r in rows)
            record(kind+'_unmated_import_and_pagination', imported)
            a, b = pair(rows, 'cylindrical_axis' if kind == 'rotary' else 'planar_normal', 2 if kind == 'rotary' else 1)
            plan = preview(identifier, a, b, 'concentric' if kind == 'rotary' else 'coincident')
            reject(kind+'_confirmation_required', 'apply_mate', 'MATE_CONFIRMATION_REQUIRED', plan_id=plan['plan_id'], confirmed=False)
            reject(kind+'_same_component_rejected', 'preview_mate', 'MATE_SAME_COMPONENT', model_id=identifier, entity_a=b['entity_id'], entity_b=b['entity_id'], mate_type='concentric' if kind == 'rotary' else 'coincident', alignment='aligned', distance_mm=0, lock_rotation=False, baseline_run_id='')
            applied = bridge.request('apply_mate', plan_id=plan['plan_id'], confirmed=True)
            assert applied['mate_count_after'] == 1 and applied['native_parameters']['verified']
            record(kind+'_first_mate', applied)
            reject(kind+'_duplicate_plan_rejected', 'apply_mate', 'MATE_PLAN_CONSUMED', plan_id=plan['plan_id'], confirmed=True)
            drive = next(r for r in bridge.request('list_drive_candidates', model_id=identifier)['entities'] if r['suggested_motor'] == kind and abs(r['axis_global'][2 if kind == 'rotary' else 0]) > .99)
            study = 'Public_'+kind
            bridge.request('create_motion_study', model_id=identifier, study=study, component_id=drive['component_id'], entity_id=drive['entity_id'], motor_type=kind, speed=12 if kind == 'rotary' else 10, reverse_direction=False)
            baseline = bridge.request('run_user_study', model_id=identifier, study=study, duration_s=1, output_fps=30, run_id=uuid.uuid4().hex)
            rows = refs(identifier)
            a, b = pair(rows, 'planar_normal', 2)
            plan = preview(identifier, a, b, 'coincident', baseline=baseline['run_id'])
            record(kind+'_descriptive_preview', plan)
            applied = bridge.request('apply_mate', plan_id=plan['plan_id'], confirmed=True)
            assert applied['mate_count_after'] == 2
            record(kind+'_second_mate', applied)
            verified = bridge.request('verify_motion_preservation', model_id=identifier, study=study, component_id=drive['component_id'], entity_id=drive['entity_id'], expected_motion=kind, minimum_travel=5, duration_s=1, output_fps=30, run_id=uuid.uuid4().hex, plan_id=plan['plan_id'])
            assert verified['assertion'] == 'pass' and verified['before_after_comparison'] == 'travel_retained', verified
            assert verified['restoration_status'] == 'restored' and verified['source_files_unchanged']
            record(kind+'_before_after_motion', verified)
            original = bridge.request('inspect_model', model_id=identifier)
            plan = preview(identifier, a, b, 'distance', distance=2)
            exc = reject(kind+'_creation_fault_rollback', '_test_mate_rollback', 'MATE_APPLY_ROLLED_BACK', plan_id=plan['plan_id'])
            assert exc.restoration_status == 'restored'
            current = bridge.request('inspect_model', model_id=identifier)
            assert len(current['mates']) == len(original['mates']) and current['source_files_unchanged']
            record(kind+'_rollback_mates_restored', current)
            rows = refs(identifier)
            a, b = pair(rows, 'planar_normal', 2)
            plan = preview(identifier, a, b, 'distance', distance=3)
            cp = bridge.request('create_model_checkpoint', model_id=identifier)
            bridge.request('_test_history_state', model_id=identifier, study=study, mode='unsaved_fps', fps=37)
            reject(kind+'_unsaved_state_stale_rejected', 'apply_mate', 'MATE_PLAN_STALE', plan_id=plan['plan_id'], confirmed=True)
            bridge.request('restore_model_checkpoint', model_id=identifier, checkpoint_id=cp['checkpoint_id'])
            if kind == 'rotary':
                report['protocol_model_id'] = identifier
                report['protocol_drive'] = drive

        fresh = bridge.request('import_assembly', path=sources['linear_unmated'])
        identifier = fresh['model_id']
        a, b = pair(refs(identifier), 'planar_normal', 1)
        plan = preview(identifier, a, b, 'distance', distance=4)
        exc = reject('controlled_post_creation_fault', '_test_mate_rollback', 'MATE_APPLY_ROLLED_BACK', plan_id=plan['plan_id'])
        assert exc.diagnostics['details']['original_error'] == 'CONTROLLED_MATE_FAULT'
        restored = bridge.request('inspect_model', model_id=identifier)
        assert restored['mates'] == [] and restored['source_files_unchanged']
        record('controlled_post_creation_fault_restored_empty_mates', restored)

        for mate_type in ('distance', 'parallel', 'perpendicular'):
            imported = bridge.request('import_assembly', path=sources['linear_unmated'])
            rows = refs(imported['model_id'])
            a, b = pair(rows, 'planar_normal', 1)
            if mate_type == 'perpendicular':
                b = next(r for r in rows if not r['fixed_component'] and r['kind'] == 'planar_normal' and abs(r['axis_global'][2]) > .99)
            plan = preview(imported['model_id'], a, b, mate_type, distance=4 if mate_type == 'distance' else 0)
            applied = bridge.request('apply_mate', plan_id=plan['plan_id'], confirmed=True)
            assert applied['mate_count_after'] == 1 and applied['source_files_unchanged']
            record(mate_type+'_native_creation', applied)

        imported = bridge.request('import_assembly', path=sources['rotary_unmated'])
        identifier = imported['model_id']
        rows = refs(identifier)
        a, b = pair(rows, 'cylindrical_axis', 2)
        plan = preview(identifier, a, b, 'concentric', lock=True)
        assert 'RELATIVE_ROTATION_WILL_BE_LOCKED' in plan['warnings']
        bridge.request('apply_mate', plan_id=plan['plan_id'], confirmed=True)
        rows = refs(identifier)
        a, b = pair(rows, 'planar_normal', 2)
        plan = preview(identifier, a, b, 'coincident')
        bridge.request('apply_mate', plan_id=plan['plan_id'], confirmed=True)
        drive = next(r for r in bridge.request('list_drive_candidates', model_id=identifier)['entities'] if r['kind'] == 'cylindrical_axis')
        bridge.request('create_motion_study', model_id=identifier, study='Locked', component_id=drive['component_id'], entity_id=drive['entity_id'], motor_type='rotary', speed=12, reverse_direction=False)
        result = bridge.request('verify_motion_preservation', model_id=identifier, study='Locked', component_id=drive['component_id'], entity_id=drive['entity_id'], expected_motion='rotary', minimum_travel=5, duration_s=1, output_fps=30, run_id=uuid.uuid4().hex, plan_id='')
        assert result['assertion'] in ('fail', 'inconclusive') and result['restoration_status'] == 'restored', result
        if result.get('native_time_axis_verified'):
            assert result['error_code'] == 'DECLARED_ROTATION_LOCK_CONFLICT' and result['direct_fixed_component_rotation_locks']
        record('locked_rotary_never_passes', result)
        report['all_passed'] = True
    except Exception as exc:
        report['failure'] = {'code': getattr(exc, 'code', ''), 'message': str(exc), 'diagnostics': getattr(exc, 'diagnostics', {})}
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        bridge.close()
        if bridge._process:
            bridge._process.wait(timeout=20)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main(sys.argv[1])
