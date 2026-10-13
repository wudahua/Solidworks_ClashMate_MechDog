"""Native history regression using a generated rotary model and optional clamp fixture."""
import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sw_mcp.bridge import Bridge, CadError

def main(model_id, clamp):
    bridge = Bridge(ROOT)
    report = {'all_passed': False, 'cases': []}
    output = ROOT/'runs/motion-history-v04.json'
    def record(name, data):
        report['cases'].append({'name': name, 'passed': True, 'evidence': data})
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(name, 'PASS', flush=True)
    def close():
        bridge.close()
        if bridge._process:
            bridge._process.wait(timeout=20)
    def study(model, name):
        return next(s for s in bridge.request('list_motion_studies', model_id=model)['studies'] if s['name']==name)
    try:
        for invalid, code in [('invalid', 'INVALID_MODEL_ID'), ('user_'+uuid.uuid4().hex, 'MODEL_NOT_REGISTERED')]:
            try:
                bridge.request('inspect_model', model_id=invalid)
                raise AssertionError('Invalid model accepted')
            except CadError as exc:
                assert exc.code==code and '执行器拒绝请求' not in str(exc), str(exc)
                record(code, {'code': exc.code, 'message': str(exc)})
        # Force only an owned history-index write to fail, before any solver state change.
        fault_study = 'History_io_fault_'+uuid.uuid4().hex[:6]
        index = ROOT/'runs/study-history'/model_id/(hashlib.sha256(fault_study.encode()).hexdigest()+'.json')
        index.mkdir(parents=True)
        fault_run = uuid.uuid4().hex
        try:
            bridge.request('run_user_study', model_id=model_id, study=fault_study, duration_s=1, output_fps=30, run_id=fault_run)
            raise AssertionError('Index write conflict accepted')
        except CadError as exc:
            assert exc.code=='FILE_ACCESS_FAILED' and exc.restoration_status=='not_required'
        saved = json.loads((ROOT/'runs'/fault_run/'solve.json').read_text(encoding='utf-8'))
        assert saved['solver_status']=='not_started' and saved['finished_at'] and saved['result_validity']=='inconclusive'
        assert not bridge.recovery_state()['recovery_required']
        record('history_index_failure_does_not_start_solver', saved)
        preflight = bridge.request('preflight_motion', model_id=model_id, study='Public_rotary')
        assert preflight['ready'] and preflight['drive_compatibility_status']=='not_checked'
        assert preflight['ready_scope']=='basic_model_preflight_only_not_solver_compatibility'
        assert not preflight['compatibility_probe']['attempted']
        record('explicit_preflight_scope', preflight)
        solved = bridge.request('run_user_study', model_id=model_id, study='Public_rotary', duration_s=1, output_fps=30, run_id=uuid.uuid4().hex)
        row = study(model_id, 'Public_rotary')
        assert row['last_run']['run_id']==solved['run_id'] and row['last_run']['result_validity']=='verified'
        assert row['last_run']['input_match_status'] in ('matches_recorded_input','unknown'), row
        assert row['last_run']['input_match_diagnostics']['file_hashes_match']
        assert row['last_run']['finished_at'] and row['drive_compatibility_status']=='not_checked'
        record('successful_run_history', row)
        checkpoint = bridge.request('create_model_checkpoint', model_id=model_id)
        bridge.request('restore_model_checkpoint', model_id=model_id, checkpoint_id=checkpoint['checkpoint_id'])
        row = study(model_id, 'Public_rotary')
        assert row['last_run']['run_id']==solved['run_id'] and row['last_run']['input_match_status']=='stale'
        assert row['history_warning'] is None
        record('checkpoint_preserves_history_and_expires_input', row)
        close()
        bridge = Bridge(ROOT)
        row = study(model_id, 'Public_rotary')
        assert row['last_run']['run_id']==solved['run_id'] and row['last_run']['input_match_status']=='stale'
        record('history_survives_executor_restart', row)
        if clamp:
            imported = bridge.request('import_assembly', path=str(Path(clamp).resolve()))
            clamp_id = imported['model_id']
            component = next(c for c in bridge.request('inspect_model', model_id=clamp_id)['components'] if c['instance'].endswith('星形架-1'))
            entities = bridge.request('list_drive_candidates', model_id=clamp_id, component_id=component['component_id'], kind='cylindrical_axis', limit=50)['entities']
            axis = next(e for e in entities if abs(e['axis_global'][1])>.99)
            name = 'History_rotary_'+uuid.uuid4().hex[:6]
            created = bridge.request('create_motion_study', model_id=clamp_id, study=name, component_id=axis['component_id'], entity_id=axis['entity_id'], motor_type='rotary', speed=30, reverse_direction=False)
            assert not created['compatibility_probe']['attempted'] and created['drive_compatibility_status']=='not_checked'
            record('creation_does_not_claim_compatibility', created)
            run_id = uuid.uuid4().hex
            try:
                bridge.request('run_user_study', model_id=clamp_id, study=name, duration_s=1, output_fps=25, run_id=run_id)
                raise AssertionError('Expected the unchanged clamp fixture to return incomplete results')
            except CadError as exc:
                assert exc.code=='MOTION_RESULTS_INCOMPLETE', exc.code
            row = study(clamp_id, name)
            assert row['last_run']['run_id']==run_id and row['last_run']['error_code']=='MOTION_RESULTS_INCOMPLETE'
            assert row['last_run']['input_match_status'] in ('matches_recorded_input','unknown'), row
            assert row['history_warning']==('PREVIOUS_SOLVE_FAILED_SAME_INPUT' if row['last_run']['input_match_status']=='matches_recorded_input' else 'PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED')
            record('incomplete_history_same_input_warning', row)
            preflight = bridge.request('preflight_motion', model_id=clamp_id, study=name)
            assert preflight['ready'] and any(w in preflight['warnings'] for w in ('PREVIOUS_SOLVE_FAILED_SAME_INPUT','PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED'))
            record('preflight_exposes_history_without_blocking', preflight)
            restored = bridge.request('restore_model_checkpoint', model_id=clamp_id, checkpoint_id=imported['checkpoint']['checkpoint_id'])
            assert restored['source_files_unchanged'] and restored['maximum_transform_delta']<1e-7
            record('clamp_source_and_state_restored', restored)
        report['all_passed'] = True
    except Exception as exc:
        report['failure'] = {'type': type(exc).__name__, 'code': getattr(exc, 'code', ''), 'message': str(exc)}
        raise
    finally:
        close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--clamp-fixture', default='')
    args=parser.parse_args()
    main(args.model_id, args.clamp_fixture)
