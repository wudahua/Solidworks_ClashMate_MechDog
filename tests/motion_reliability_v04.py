"""Real feedback regression: edits only fresh imported copies, source hashes verified."""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge,CadError
from sw_mcp.jobs import Jobs
from sw_mcp.artifacts import Artifacts


def main(source, resume_model=None, resume_checkpoint=None):
    os.environ['SW_MCP_FAULT_TESTS']='1'
    bridge=Bridge(ROOT);jobs=Jobs(bridge,ROOT);artifacts=Artifacts(ROOT)
    report={'all_passed':False,'cases':[]}
    output=ROOT/'runs/motion-reliability-v04-alpha2.json'
    model=None;checkpoint=None
    def record(name,evidence):
        report['cases'].append({'name':name,'passed':True,'evidence':evidence})
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name,'PASS',flush=True)
    def states():
        return [{k:s[k] for k in ('name','type','time_s','duration_s','output_fps','active')} for s in bridge.request('list_motion_studies',model_id=model)['studies']]
    try:
        if resume_model:
            model=resume_model;checkpoint=resume_checkpoint
            assert checkpoint
            record('registered_copy_resumed_after_verified_recovery',bridge.request('inspect_model',model_id=model))
        else:
            submitted=jobs.submit('import_assembly',{'path':str(Path(source).resolve())});stages=set();deadline=time.monotonic()+bridge.motion_scan_timeout+30
            while True:
                job=jobs.get(submitted['job_id'])
                if job.get('progress'):stages.add(job['progress']['stage'])
                if job['status'] not in ('queued','running'):break
                if time.monotonic()>=deadline:raise TimeoutError('Import has not ended; preserve quarantine and await the actual CAD response')
                time.sleep(.1)
            assert job['status']=='succeeded',job
            imported=job['result'];model=imported['model_id'];checkpoint=imported['checkpoint']['checkpoint_id']
            assert imported['preflight']['ready'] and stages
            record('import_progress',{'model_id':model,'file_count':imported['file_count'],'observed_stages':sorted(stages)})
        inventory=bridge.request('list_motion_studies',model_id=model)['studies'];study=next(s['name'] for s in inventory if s['type']==4)
        assert all('time_s' in s and 'study_type_name' in s and 'feature_enumeration_status' in s for s in inventory)
        before=states();record('study_clock_and_inventory',inventory)
        candidates=[];cursor='';page_sizes=[]
        while True:
            page=bridge.request('list_drive_candidates',model_id=model,limit=50,cursor=cursor)
            assert 'components' not in page and len(page['entities'])<=50
            size=len(json.dumps({'content':[{'type':'text','text':json.dumps(page,ensure_ascii=False)}],'structuredContent':page},ensure_ascii=False).encode('utf-8'))
            assert size<50000,size
            page_sizes.append(size);candidates.extend(page['entities']);cursor=page['next_cursor']
            if not cursor:break
        assert len(candidates)==page['total'] and len({c['entity_id'] for c in candidates})==len(candidates)
        chosen=next(c for c in candidates if c['suggested_motor']=='rotary')
        filtered=bridge.request('list_drive_candidates',model_id=model,component_id=chosen['component_id'],kind='cylindrical_axis',limit=50)
        assert all(c['component_id']==chosen['component_id'] and c['kind']=='cylindrical_axis' for c in filtered['entities'])
        first_page=bridge.request('list_drive_candidates',model_id=model,limit=1)
        record('bounded_filtered_candidates',{'candidates':len(candidates),'pages':len(page_sizes),'maximum_wire_bytes':max(page_sizes)})
        initial=bridge.request('inspect_model',model_id=model)
        for duration in (2,1):
            run_id=uuid.uuid4().hex
            solved=bridge.request('run_user_study',model_id=model,study=study,duration_s=duration,output_fps=25,run_id=run_id)
            assert solved['frames']==int(duration*25)+1 and solved['restoration_status']=='restored' and solved['result_validity']=='verified'
            assert solved['motion_detected'] and solved['maximum_translation_from_frame0_m']>.001
            assert states()==before,(states(),before)
            after=bridge.request('inspect_model',model_id=model)
            a={c['component_id']:c['transform'] for c in initial['components']};z={c['component_id']:c['transform'] for c in after['components']}
            assert a.keys()==z.keys() and max(abs(v-w) for k in a for v,w in zip(a[k],z[k]))<1e-7
            assert artifacts.summary(run_id)['poses_available'] and artifacts.poses(run_id,limit=1)['artifact_integrity']=='verified'
            record('existing_study_'+str(duration)+'s_full_state_restore',solved)
        restored=bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=checkpoint)
        assert states()==before
        record('inactive_nonzero_checkpoint_restore',restored)
        if first_page['next_cursor']:
            try:bridge.request('list_drive_candidates',model_id=model,limit=1,cursor=first_page['next_cursor'])
            except CadError as e:assert e.code=='CANDIDATE_CURSOR_STALE'
            else:raise AssertionError('stale cursor accepted')
            record('stale_candidate_cursor_rejected',{})
        candidates=bridge.request('list_drive_candidates',model_id=model,kind='cylindrical_axis',limit=50)['entities'];chosen=candidates[0]
        created=bridge.request('create_motion_study',model_id=model,study='Review_Create_After_Restore',component_id=chosen['component_id'],entity_id=chosen['entity_id'],motor_type='rotary',speed=12,reverse_direction=False)
        record('create_drive_after_checkpoint_restore',created)
        bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=checkpoint)
        setup=bridge.request('_test_set_study_time',model_id=model,study=study,time_s=.54174)
        active_before=states();active_cp=bridge.request('create_model_checkpoint',model_id=model)
        run_id=uuid.uuid4().hex
        try:bridge.request('run_user_study',model_id=model,study=study,duration_s=1,output_fps=25,run_id=run_id)
        except CadError as e:assert e.code=='ACTIVE_TIME_NOT_FRAME_ALIGNED' and e.diagnostics
        else:raise AssertionError('unsupported active clock was accepted')
        assert states()==active_before and not bridge.recovery_state()['recovery_required']
        record('active_non_frame_aligned_clock_rejected_without_mutation',{'setup':setup})
        reset=bridge.request('reset_study_time',model_id=model,study=study)
        assert next(s for s in states() if s['name']==study)['time_s']==0
        record('explicit_time_reset',reset)
        zero_state=states()
        after_reset=bridge.request('run_user_study',model_id=model,study=study,duration_s=1,output_fps=25,run_id=uuid.uuid4().hex)
        assert after_reset['restoration_status']=='restored' and states()==zero_state
        record('run_after_explicit_reset',after_reset)
        bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=active_cp['checkpoint_id'])
        assert states()==active_before
        record('active_nonzero_checkpoint_restore',{})
        bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=checkpoint)
        run_id=uuid.uuid4().hex
        try:bridge.request('_test_run_restoration_failure',model_id=model,study=study,duration_s=1,output_fps=25,run_id=run_id)
        except CadError as e:
            assert e.code=='RESTORATION_FAILED' and e.restoration_status=='unknown' and e.diagnostics
        else:raise AssertionError('controlled fault incorrectly passed')
        assert bridge.recovery_state()['recovery_required']
        offline=artifacts.summary(run_id);rows=artifacts.poses(run_id,limit=20)
        assert offline['sampling_status']=='completed' and offline['result_validity']=='inconclusive' and rows['returned']==20
        record('failed_restore_artifacts_readable_under_quarantine',offline)
        bridge.request('restore_model_checkpoint',model_id=model,checkpoint_id=checkpoint)
        assert not bridge.recovery_state()['recovery_required']
        manifest=json.loads((ROOT/'experiments/user_assemblies'/model[5:]/'model.json').read_text(encoding='utf-8'))
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()==v.replace('-','').upper() for p,v in manifest['SourceHashes'].items())
        record('all_source_hashes_unchanged',{'files':len(manifest['SourceHashes'])})
        report['all_passed']=True
    except Exception as e:
        report['failure']={'code':getattr(e,'code',''),'message':str(e),'diagnostics':getattr(e,'diagnostics',{})}
        raise
    finally:
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        jobs._pool.shutdown(wait=True);bridge.close()
        if bridge._process:
            try:bridge._process.wait(timeout=20)
            except Exception:pass

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--assembly');parser.add_argument('--source-manifest');parser.add_argument('--resume-model-id');parser.add_argument('--checkpoint-id');args=parser.parse_args()
    source=args.assembly
    if args.source_manifest:
        manifest=json.loads(Path(args.source_manifest).read_text(encoding='utf-8-sig'));source=next(p for p in manifest['SourceHashes'] if p.lower().endswith('.sldasm'))
    if not source and not args.resume_model_id:parser.error('--assembly, --source-manifest or --resume-model-id is required')
    main(source,args.resume_model_id,args.checkpoint_id)
