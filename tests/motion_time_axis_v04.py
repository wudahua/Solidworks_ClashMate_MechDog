"""Clamp fixture regression: incompatible Y rotary and compatible Y linear drives.
Requires an explicitly selected registered copy, checkpoint and component suffix.
"""
import argparse,json,os,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge,CadError

def main(args):
    bridge=Bridge(ROOT);output=ROOT/'runs/motion-time-axis-v04.json';report={'cases':[],'all_passed':False}
    def record(name,data):
        report['cases'].append({'name':name,'passed':True,'evidence':data})
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(name,'PASS',flush=True)
    def restore():return bridge.request('restore_model_checkpoint',model_id=args.model_id,checkpoint_id=args.checkpoint_id)
    try:
        selected=os.environ['SW_MCP_PROCESS_ID'];journal=ROOT/'runs/executor-state.json';before=journal.read_bytes() if journal.exists() else None
        os.environ['SW_MCP_PROCESS_ID']='2147483647'
        try:bridge.request('get_environment');raise AssertionError('absent COM session accepted')
        except CadError as exc:assert exc.code=='COM_SESSION_NOT_FOUND',exc.code
        bridge._process.wait(timeout=20)
        assert (journal.read_bytes() if journal.exists() else None)==before
        os.environ['SW_MCP_PROCESS_ID']=selected
        environment=bridge.request('get_environment');assert environment['solidworks_process_id']==int(selected)
        record('same_bridge_startup_retry',environment)
        record('initial_checkpoint',restore())
        components=bridge.request('inspect_model',model_id=args.model_id)['components']
        chosen=next(c for c in components if c['instance'].endswith(args.component_suffix))
        raw=bridge.request('list_drive_candidates',model_id=args.model_id,component_id=chosen['component_id'],kind='cylindrical_axis',limit=50,group_faces=False)
        groups=bridge.request('list_drive_candidates',model_id=args.model_id,component_id=chosen['component_id'],kind='cylindrical_axis',limit=50,group_faces=True)
        assert sum(e['equivalent_face_count'] for e in groups['entities'])==raw['total']
        record('candidate_geometry_groups',{'raw':raw,'grouped':groups})
        try:bridge.request('list_drive_candidates',model_id=args.model_id,cursor='invalid');raise AssertionError('invalid cursor accepted')
        except CadError as exc:
            assert exc.code=='CANDIDATE_CURSOR_STALE' and exc.restoration_status=='not_required'
            assert exc.document_context_restoration_status=='restored'
            record('cursor_error_restoration_semantics',{'code':exc.code,'restoration_status':exc.restoration_status,'document_context_restoration_status':exc.document_context_restoration_status})
        rotary=next(e for e in raw['entities'] if abs(e['axis_global'][1])>.99)
        name='Alpha3_rotary_'+uuid.uuid4().hex[:6]
        created=bridge.request('create_motion_study',model_id=args.model_id,study=name,component_id=chosen['component_id'],entity_id=rotary['entity_id'],motor_type='rotary',speed=30,reverse_direction=False)
        assert created['duration_s']==1 and created['output_fps']==30
        record('created_settings',created)
        run=uuid.uuid4().hex
        try:bridge.request('run_user_study',model_id=args.model_id,study=name,duration_s=1,output_fps=25,run_id=run);raise AssertionError('incompatible rotary drive passed')
        except CadError as exc:
            assert exc.code=='MOTION_RESULTS_INCOMPLETE' and exc.restoration_status=='restored',exc.code
            saved=json.loads((ROOT/'runs'/run/'solve.json').read_text(encoding='utf-8'))
            assert saved['solver_status']=='incomplete' and saved['result_validity']=='inconclusive'
            assert saved['failure_diagnostics']['time_axis']['actual_count']==1
            record('incomplete_results_rejected',saved)
        restore()
        planes=bridge.request('list_drive_candidates',model_id=args.model_id,component_id=chosen['component_id'],kind='planar_normal',limit=50)
        linear=next(e for e in planes['entities'] if abs(e['axis_global'][1])>.99)
        name='Alpha3_linear_'+uuid.uuid4().hex[:6]
        record('linear_created',bridge.request('create_motion_study',model_id=args.model_id,study=name,component_id=chosen['component_id'],entity_id=linear['entity_id'],motor_type='linear',speed=10,reverse_direction=False))
        for fps in (25,30,60):
            run=uuid.uuid4().hex
            result=bridge.request('run_user_study',model_id=args.model_id,study=name,duration_s=1,output_fps=fps,run_id=run)
            assert result['frames']==fps+1 and result['restoration_status']=='restored' and result['source_files_unchanged']
            assert result['drive_validation']['absolute_magnitude_error']<.001
            record('linear_'+str(fps)+'fps',result)
            if fps==25:
                replay=bridge.request('replay_motion_frame',run_id=run,frame=12)
                assert replay['pose_validation']['within_pose_tolerance']
                assert replay['pose_validation']['maximum_translation_difference_m']<=1e-7 and replay['pose_validation']['maximum_rotation_difference_rad']<=1e-6
                record('linear_replay',replay)
        record('final_checkpoint',restore());report['all_passed']=True
    except Exception as exc:
        report['failure']={'type':type(exc).__name__,'code':getattr(exc,'code',''),'message':str(exc)};raise
    finally:
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');bridge.close()
        if bridge._process:bridge._process.wait(timeout=20)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-id',required=True);parser.add_argument('--checkpoint-id',required=True);parser.add_argument('--component-suffix',required=True)
    sys.stdout.reconfigure(encoding='utf-8');main(parser.parse_args())
