"""Focused native reset/checkpoint/failure-artifact regression on a registered copy."""
import argparse,json,os,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge,CadError
from sw_mcp.artifacts import Artifacts

def main(model,checkpoint):
    os.environ['SW_MCP_FAULT_TESTS']='1';bridge=Bridge(ROOT);artifacts=Artifacts(ROOT)
    report={'all_passed':False,'cases':[]};output=ROOT/'runs/motion-reset-recovery-v04-alpha3.json'
    def record(name,value):
        report['cases'].append({'name':name,'passed':True,'evidence':value});output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(name,'PASS',flush=True)
    def states():
        return [{k:s[k] for k in ('name','type','time_s','duration_s','output_fps','active')} for s in bridge.request('list_motion_studies',model_id=model)['studies']]
    try:
        study=next(s['name'] for s in bridge.request('list_motion_studies',model_id=model)['studies'] if s['type']==4)
        record('native_environment',bridge.request('get_environment'))
        record('active_clock_setup',bridge.request('_test_set_study_time',model_id=model,study=study,time_s=.54174))
        before=states();active_cp=bridge.request('create_model_checkpoint',model_id=model);record('nonzero_active_checkpoint',active_cp)
        try:bridge.request('run_user_study',model_id=model,study=study,duration_s=1,output_fps=25,run_id=uuid.uuid4().hex)
        except CadError as e:assert e.code=='ACTIVE_TIME_NOT_FRAME_ALIGNED'
        else:raise AssertionError('non-frame-aligned active state accepted')
        assert states()==before and not bridge.recovery_state()['recovery_required'];record('nonaligned_state_rejected_without_changes',{})
        record('explicit_time_reset',bridge.request('reset_study_time',model_id=model,study=study))
        zero=states();assert next(s for s in zero if s['name']==study)['time_s']==0
        run_id=uuid.uuid4().hex;result=bridge.request('run_user_study',model_id=model,study=study,duration_s=1,output_fps=25,run_id=run_id,job_id=run_id)
        assert result['restoration_status']=='restored' and states()==zero;record('solve_after_reset',result)
        restored=bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=active_cp['checkpoint_id']);assert states()==before;record('active_nonzero_checkpoint_restored',restored)
        bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=checkpoint)
        run_id=uuid.uuid4().hex
        try:bridge.request('_test_run_restoration_failure',model_id=model,study=study,duration_s=1,output_fps=25,run_id=run_id,job_id=run_id)
        except CadError as e:assert e.code=='RESTORATION_FAILED' and e.restoration_status=='unknown'
        else:raise AssertionError('controlled failure returned pass')
        assert bridge.recovery_state()['recovery_required'];summary=artifacts.summary(run_id);assert summary['sampling_status']=='completed' and summary['result_validity']=='inconclusive';assert artifacts.poses(run_id,limit=20)['returned']==20
        record('failure_artifacts_readable_while_quarantined',summary)
        restored=bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=checkpoint);assert not bridge.recovery_state()['recovery_required'];record('restore_after_controlled_fault',restored)
        report['all_passed']=True
    except Exception as e:
        report['failure']={'code':getattr(e,'code',''),'message':str(e),'diagnostics':getattr(e,'diagnostics',{})};raise
    finally:
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');bridge.close()
        if bridge._process:
            try:bridge._process.wait(timeout=20)
            except Exception:pass

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('--model-id',required=True);p.add_argument('--checkpoint-id',required=True);a=p.parse_args();main(a.model_id,a.checkpoint_id)
