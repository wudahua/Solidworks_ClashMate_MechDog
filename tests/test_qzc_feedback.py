"""Offline history has bounded payloads, explicit provenance and no CAD dispatch."""
import csv
import hashlib
import json
import struct
import tempfile
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.artifacts import Artifacts,ArtifactError
from sw_mcp.bridge import Bridge
from sw_mcp.save_observations import SaveObservations
from transport_cleanup import remove_test_root


class QzcHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Keep SHA-named legacy fixtures below Windows MAX_PATH in long release checkouts.
        self.base=Path(tempfile.gettempdir()).resolve()/'cm-qzc';self.root=self.base/uuid.uuid4().hex[:8];self.root.mkdir(parents=True)
        self.addCleanup(remove_test_root,self.root,self.base)
        self.model='user_'+'c'*32;self.operation='d'*32
        self.model_root=self.root/'experiments/user_assemblies'/self.model[5:]
        self.history=self.model_root/'save-observations'/self.operation;self.history.mkdir(parents=True)
        self.run='a'*32;self.run_root=self.root/'runs'/self.run;self.run_root.mkdir(parents=True)
        self.csv=self.run_root/'component-poses.csv'
        with self.csv.open('w',newline='',encoding='utf-8') as stream:
            out=csv.writer(stream);out.writerow(['frame','time_s','component_id','instance','x_m','y_m','z_m','r00','r01','r02','r10','r11','r12','r20','r21','r22'])
            for i in range(3):out.writerow([i,i/5,'component_a','part',i*.002,0,0,1,0,0,0,1,0,0,0,1])
        self.csv_hash=hashlib.sha256(self.csv.read_bytes()).hexdigest()
        (self.run_root/'solve.json').write_text(json.dumps({'run_id':self.run,'model_id':self.model,'poses_sha256':self.csv_hash,'result_validity':'verified','restoration_status':'restored'}),encoding='utf-8')
        self.artifacts=Artifacts(self.root)

    def make_history(self,count=12,files=7):
        for i in range(1,count+1):
            record={'schema_version':1,'model_id':self.model,'operation_id':self.operation,'sequence_number':i,'stage':f'save_{i}','observed_at_utc':'2026-10-14T00:00:00Z','model_revision':2,'observation':{'complete':True,'dirty_documents_observed':False},'file_hashes':{f'E:/样本/{n}/零件.SLDPRT':'b'*64 for n in range(files)}}
            path=self.history/f'{i:010d}.json';raw=json.dumps(record,ensure_ascii=False).encode();path.write_bytes(raw)
            Path(str(path)+'.sha256').write_text(hashlib.sha256(raw).hexdigest(),encoding='utf-8')
        manifest={'schema_version':1,'model_id':self.model,'operation_id':self.operation,'operation_name':'apply_mate','stage_count':count,'stages':[]}
        raw=json.dumps(manifest).encode();(self.history/'operation.json').write_bytes(raw);(self.model_root/'last-save-observation.json').write_bytes(raw)

    def make_image(self,attempt='b'*32,frame=1):
        # A valid 1x1, 24-bit BMP keeps this a real binary artifact test.
        bitmap=b'BM'+struct.pack('<IHHI',58,0,0,54)+struct.pack('<IiiHHIIiiII',40,1,1,1,24,0,4,0,0,0,0)+b'\x00\x80\xff\x00'
        name=f'motion-frame-{frame}-{attempt}.bmp';image=self.run_root/name;image.write_bytes(bitmap)
        folder=self.run_root/'screenshots';folder.mkdir(exist_ok=True)
        meta={'schema_version':1,'run_id':self.run,'model_id':self.model,'attempt_id':attempt,'frame':frame,'time_s':frame/5,'image_file':name,'image_sha256':hashlib.sha256(bitmap).hexdigest(),'poses_sha256':self.csv_hash,'captured_at_utc':'2026-10-14T00:00:00Z','pose_assertion':'pass','restoration_status':'restored','pose_validation':{'frame':frame,'within_pose_tolerance':True,'checked_component_count':1,'maximum_translation_difference_m':0,'maximum_rotation_difference_rad':0,'translation_tolerance_m':1e-7,'rotation_tolerance_rad':1e-6}}
        path=folder/(attempt+'.json');path.write_text(json.dumps(meta),encoding='utf-8');return image,path,meta

    def test_observations_page_all_stages_without_history_duplication(self):
        self.make_history();reader=SaveObservations(self.root);cursor='';sequences=[]
        while True:
            result=reader.read(self.model,self.operation,5,cursor)
            self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),16000)
            for row in result['stages']:
                self.assertNotIn('file_hashes',row);self.assertEqual(row['artifact_integrity'],'verified');sequences.append(row['sequence_number'])
            cursor=result['next_cursor']
            if not cursor:break
        self.assertEqual(sequences,list(range(1,13)))

    def test_full_hashes_explicit_and_large_record_has_honest_disk_reference(self):
        self.make_history(2,300)
        result=SaveObservations(self.root).read(self.model,self.operation,5,include_file_hashes=True)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),16000)
        self.assertTrue(result['stages'][0]['full_record_omitted']);self.assertEqual(result['stages'][0]['omission_reason'],'single_record_byte_budget')
        self.assertEqual(len(json.loads(Path(result['stages'][0]['full_record_path']).read_text(encoding='utf-8'))['file_hashes']),300)

    def test_observation_tamper_is_rejected(self):
        self.make_history(1);path=self.history/'0000000001.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ArtifactError) as error:SaveObservations(self.root).read(self.model,self.operation)
        self.assertEqual(error.exception.code,'OBSERVATION_HASH_MISMATCH')

    def test_cursor_cannot_cross_operation_or_manifest_update(self):
        self.make_history();reader=SaveObservations(self.root);cursor=reader.read(self.model,self.operation,2)['next_cursor']
        path=self.history/'operation.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ArtifactError) as error:reader.read(self.model,self.operation,2,cursor)
        self.assertEqual(error.exception.code,'OBSERVATION_CURSOR_STALE')

    def test_legacy_trace_is_readable_and_not_assigned_an_operation_identity(self):
        legacy={'model_id':self.model,'stages':[{'stage':'old','file_hashes':{'old':'hash'}}]}
        (self.model_root/'last-save-observation.json').write_text(json.dumps(legacy),encoding='utf-8')
        result=SaveObservations(self.root).read(self.model)
        self.assertTrue(result['legacy_without_operation_identity']);self.assertEqual(result['stages'][0]['artifact_integrity'],'not_recorded_legacy')

    def test_archived_legacy_bytes_remain_readable_and_hash_bound(self):
        legacy=json.dumps({'model_id':self.model,'stages':[{'stage':'old'}]}).encode()
        sha=hashlib.sha256(legacy).hexdigest();directory=self.model_root/'save-observations/legacy';directory.mkdir();path=directory/(sha+'.json');path.write_bytes(legacy)
        result=SaveObservations(self.root).read(self.model,'legacy_'+sha)
        self.assertTrue(result['legacy_without_operation_identity']);self.assertEqual(result['stages'][0]['stage'],'old')
        path.write_bytes(legacy+b' ')
        with self.assertRaises(ArtifactError) as error:SaveObservations(self.root).read(self.model,'legacy_'+sha)
        self.assertEqual(error.exception.code,'OBSERVATION_HASH_MISMATCH')

    def test_invalid_legacy_stage_schema_has_explicit_error(self):
        (self.model_root/'last-save-observation.json').write_text(json.dumps({'model_id':self.model,'stages':None}))
        with self.assertRaises(ArtifactError) as error:SaveObservations(self.root).read(self.model)
        self.assertEqual(error.exception.code,'OBSERVATION_INVALID')

    async def test_observation_public_tool_works_in_quarantine_without_com(self):
        import motion_server as server
        self.make_history(2);bridge=Bridge(self.root);bridge._journal({'status':'unknown'});bridge.close()
        with patch.object(server,'artifacts',self.artifacts),patch.object(server.bridge,'request',side_effect=AssertionError('COM forbidden')):
            result=await server.get_run_artifacts(model_id=self.model,operation_id=self.operation)
        self.assertFalse(result.is_error);self.assertEqual(result.structured_content['returned'],2)

    async def test_public_query_rejects_ambiguous_identity(self):
        import motion_server as server
        with self.assertRaises(Exception):await server.get_run_artifacts(self.run,model_id=self.model)

    async def test_saved_frame_after_restart_and_unknown_state_never_dispatches(self):
        import motion_server as server
        image,_,_=self.make_image();bridge=Bridge(self.root);bridge._journal({'status':'unknown'});bridge.close()
        with patch.object(server,'artifacts',Artifacts(self.root)),patch.object(server.bridge,'request',side_effect=AssertionError('COM forbidden')):
            result=await server.replay_motion_frame(self.run,1,saved_image_only=True)
        self.assertFalse(result.is_error);data=result.structured_content['result'];self.assertEqual(Path(data['image_path']).resolve(),image.resolve())
        self.assertTrue(data['historical_image']);self.assertFalse(data['fresh_cad_replay_performed']);self.assertEqual(data['current_model_validity'],'not_checked_offline')

    def test_saved_image_and_csv_tamper_are_rejected(self):
        image,_,_=self.make_image();image.write_bytes(image.read_bytes()+b'x')
        with self.assertRaises(ArtifactError) as error:self.artifacts.saved_frame_image(self.run,1)
        self.assertEqual(error.exception.code,'IMAGE_HASH_MISMATCH')
        self.assertEqual(self.artifacts.summary(self.run)['saved_frame_images']['status'],'unavailable')
        self.assertEqual(self.artifacts.summary(self.run)['artifact_integrity'],'verified')
        self.make_image();self.csv.write_bytes(self.csv.read_bytes()+b' ')
        with self.assertRaises(ArtifactError) as error:self.artifacts.saved_frame_image(self.run,1)
        self.assertEqual(error.exception.code,'IMAGE_HASH_MISMATCH')

    def test_no_image_is_synthesized_from_csv_or_promoted_from_legacy_bmp(self):
        (self.run_root/'motion-frame-1.bmp').write_bytes(b'legacy')
        with self.assertRaises(ArtifactError) as error:self.artifacts.saved_frame_image(self.run,1)
        self.assertEqual(error.exception.code,'SAVED_FRAME_IMAGE_NOT_FOUND')
        self.assertEqual(self.artifacts.summary(self.run)['saved_frame_images']['total'],0)

    def test_failed_or_contradictory_pose_metadata_is_rejected(self):
        _,path,meta=self.make_image();meta['pose_validation']['maximum_translation_difference_m']=.01;path.write_text(json.dumps(meta))
        with self.assertRaises(ArtifactError) as error:self.artifacts.saved_frame_image(self.run,1)
        self.assertEqual(error.exception.code,'IMAGE_MANIFEST_INVALID')

    def test_image_frame_time_must_match_csv(self):
        _,path,meta=self.make_image();meta['time_s']=.3;path.write_text(json.dumps(meta))
        with self.assertRaises(ArtifactError) as error:self.artifacts.saved_frame_image(self.run,1)
        self.assertEqual(error.exception.code,'IMAGE_POSE_IDENTITY_MISMATCH')

    def test_image_path_cannot_escape_run(self):
        _,path,meta=self.make_image();meta['image_file']='../other.bmp';path.write_text(json.dumps(meta))
        with self.assertRaises(ArtifactError):self.artifacts.saved_frame_image(self.run,1)

    def test_summary_lists_bounded_images_but_exact_frame_query_can_read_older_record(self):
        for i in range(7):self.make_image(attempt=f'{i+1:032x}',frame=1)
        result=self.artifacts.summary(self.run)['saved_frame_images'];self.assertEqual(result['total'],7);self.assertEqual(result['returned'],5);self.assertTrue(result['truncated'])
        self.assertEqual(self.artifacts.saved_frame_image(self.run,1)['frame'],1)


if __name__=='__main__':unittest.main()
