"""Native dirty-flag, repeated-failure and enumeration regressions on owned copies only."""
import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge,CadError

def main(model_id,clamp):
    os.environ['SW_MCP_FAULT_TESTS']='1'
    bridge=Bridge(ROOT);report={'all_passed':False,'cases':[]};output=ROOT/'runs/motion-history-diagnostics-v04.json'
    def record(name,data):
        report['cases'].append({'name':name,'passed':True,'evidence':data})
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(name,'PASS',flush=True)
    def rows(identifier):return bridge.request('list_motion_studies',model_id=identifier)
    def row(identifier,name):
        response=rows(identifier)
        return next(s for s in response['studies'] if s['name']==name),response['input_observation']
    def hashes(identifier):
        m=json.loads((ROOT/'experiments/user_assemblies'/identifier[5:]/'model.json').read_text(encoding='utf-8'))
        return {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in m['Files']}
    def flags_response(response):
        stages=response['input_observation']['stages']
        assert {'before_load_motion','after_load_motion','after_scope_open'}<={s['stage'] for s in stages}
        for s in response['studies']:
            raw=s['native_feature_enumeration_status']
            if raw=='native_null':assert s['feature_enumeration_status']==('native_null_study_active' if s['enumeration_study_active'] else 'native_null_study_inactive')
            assert not s['empty_feature_list_means_no_drive'] and s['enumeration_activation_requirement']=='not_proven'
            if not s['motion_features']:assert s['feature_presence']=='unknown'
    try:
        cp=bridge.request('create_model_checkpoint',model_id=model_id)
        solved=bridge.request('run_user_study',model_id=model_id,study='Public_rotary',duration_s=1,output_fps=30,run_id=uuid.uuid4().hex)
        current,observation=row(model_id,'Public_rotary')
        assert current['last_run']['input_match_status'] in ('matches_recorded_input','unknown'),current
        diagnostics=current['last_run']['input_match_diagnostics']
        assert diagnostics['revision_match'] and diagnostics['configuration_match'] and diagnostics['file_hashes_match'] and diagnostics['study_settings_match']
        record('successful_history_diagnostics',{'row':current,'input_observation':observation})
        stable_hashes=hashes(model_id)
        bridge.request('_test_history_state',model_id=model_id,study='Public_rotary',mode='mark_dirty')
        current,observation=row(model_id,'Public_rotary')
        assert current['last_run']['input_match_status']=='unknown' and current['last_run']['input_match_diagnostics']['file_hashes_match']
        assert current['history_warning'] is None and observation['dirty_documents_observed']
        assert hashes(model_id)==stable_hashes
        record('dirty_flag_without_saved_change_is_unknown',{'row':current,'input_observation':observation})
        candidates=bridge.request('list_drive_candidates',model_id=model_id,kind='planar_normal',limit=50)['entities']
        candidate=candidates[0];name='Enum_linear_'+uuid.uuid4().hex[:6]
        bridge.request('create_motion_study',model_id=model_id,study=name,component_id=candidate['component_id'],entity_id=candidate['entity_id'],motor_type='linear',speed=10,reverse_direction=False)
        before=rows(model_id);flags_response(before)
        assert next(s for s in before['studies'] if s['name']==name)['active']
        bridge.request('_test_history_state',model_id=model_id,study='Public_rotary',mode='activate_study')
        after=rows(model_id);flags_response(after)
        assert next(s for s in after['studies'] if s['name']=='Public_rotary')['active']
        assert not next(s for s in after['studies'] if s['name']==name)['active']
        again=rows(model_id)
        assert [(s['name'],s['active']) for s in after['studies']]==[(s['name'],s['active']) for s in again['studies']]
        assert next(s for s in after['studies'] if s['name']=='Public_rotary')['registered_drive']['Kind']=='rotary'
        record('active_inactive_enumeration_does_not_switch_studies',{'before':before,'after':after})
        restored=bridge.request('restore_model_checkpoint',model_id=model_id,checkpoint_id=cp['checkpoint_id'])
        assert restored['source_files_unchanged']
        record('generated_copy_restored',restored)
        imported=bridge.request('import_assembly',path=str(Path(clamp).resolve()));identifier=imported['model_id']
        star=next(c for c in bridge.request('inspect_model',model_id=identifier)['components'] if c['instance'].endswith('星形架-1'))
        axis=next(e for e in bridge.request('list_drive_candidates',model_id=identifier,component_id=star['component_id'],kind='cylindrical_axis',limit=50)['entities'] if abs(e['axis_global'][1])>.99)
        name='Dirty_rotary_'+uuid.uuid4().hex[:6]
        bridge.request('create_motion_study',model_id=identifier,study=name,component_id=axis['component_id'],entity_id=axis['entity_id'],motor_type='rotary',speed=30,reverse_direction=False)
        for i in range(2):
            run=uuid.uuid4().hex
            try:
                bridge.request('run_user_study',model_id=identifier,study=name,duration_s=1,output_fps=25,run_id=run)
                raise AssertionError('Unchanged clamp fixture expected incomplete output')
            except CadError as exc:assert exc.code=='MOTION_RESULTS_INCOMPLETE',exc.code
            current,observation=row(identifier,name)
            assert current['last_run']['run_id']==run and current['last_run']['input_match_status']!='stale',current
            expected='PREVIOUS_SOLVE_FAILED_SAME_INPUT' if current['last_run']['input_match_status']=='matches_recorded_input' else 'PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED'
            assert current['history_warning']==expected
            manifest=json.loads((ROOT/'runs'/run/'solve.json').read_text(encoding='utf-8'))
            assert {'after_restore_apply_states','after_restore_context'}<={s['stage'] for s in manifest['input_observation']['stages']}
            record('repeated_incomplete_'+str(i+1),{'row':current,'input_observation':observation,'solve_observation':manifest['input_observation']})
        stable_hashes=hashes(identifier)
        bridge.request('_test_history_state',model_id=identifier,study=name,mode='mark_dirty')
        current,observation=row(identifier,name)
        assert current['last_run']['input_match_status']=='unknown' and current['history_warning']=='PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED'
        assert current['last_run']['input_match_diagnostics']['file_hashes_match'] and hashes(identifier)==stable_hashes
        preflight=bridge.request('preflight_motion',model_id=identifier,study=name)
        assert 'PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED' in preflight['warnings']
        record('unverified_failed_input_warns_without_same_input_claim',{'row':current,'preflight':preflight})
        mutation=bridge.request('_test_history_state',model_id=identifier,study=name,mode='unsaved_fps',fps=37)
        assert mutation['fps_after']==37 and not mutation['saved']
        current,observation=row(identifier,name)
        assert current['last_run']['input_match_status']=='stale' and current['last_run']['input_match_diagnostics']['study_settings_match'] is False
        assert current['history_warning'] is None and hashes(identifier)==stable_hashes
        record('real_unsaved_study_setting_change_is_stale',{'mutation':mutation,'row':current,'input_observation':observation})
        restored=bridge.request('restore_model_checkpoint',model_id=identifier,checkpoint_id=imported['checkpoint']['checkpoint_id'])
        assert restored['source_files_unchanged'] and restored['maximum_transform_delta']<1e-7
        final=rows(identifier);flags_response(final)
        record('clamp_restored_and_query_diagnostics_retained',{'restored':restored,'query':final})
        report['all_passed']=True
    except Exception as exc:
        report['failure']={'type':type(exc).__name__,'code':getattr(exc,'code',''),'message':str(exc)};raise
    finally:
        bridge.close()
        if bridge._process:bridge._process.wait(timeout=20)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--model-id',required=True);p.add_argument('--clamp-fixture',required=True);a=p.parse_args();main(a.model_id,a.clamp_fixture)
