import asyncio
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_service import temporary_workspace
from scripts.upgrade import upgrade, UpgradeFailure, installation_target
from sw_mcp import job_payload as payload
from sw_mcp.errors import operational_error

ROOT = Path(__file__).resolve().parents[1]


class FeedbackTests(unittest.TestCase):
    def refusal(self, path):
        with self.assertRaises(UpgradeFailure) as caught:
            upgrade('unused.zip', path, sys.executable, dry_run=True)
        return caught.exception.payload()

    def test_real_same_directory_spelling_is_normalized_before_installation_check(self):
        with temporary_workspace() as folder:
            root=Path(folder); (root/'child').mkdir()
            state={}
            canonical=installation_target(root/'child'/'..',state)
            self.assertEqual(canonical,root.resolve())
            self.assertEqual(state['path_resolution']['aliasing_kind'],'same_directory_spelling')
            self.assertTrue(state['path_resolution']['canonical_directory_used'])
            self.assertEqual(self.refusal(root/'child'/'..')['code'],'UPGRADE_TARGET_NOT_INSTALLATION')

    @unittest.skipUnless(os.name == 'nt', 'Windows path semantics')
    def test_real_short_and_long_directory_names_have_same_classification(self):
        with temporary_workspace() as folder:
            target = Path(folder)/'Long installation spelling for short name verification'
            target.mkdir()
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
            buffer = ctypes.create_unicode_buffer(32768)
            self.assertGreater(kernel.GetShortPathNameW(str(target), buffer, len(buffer)), 0)
            if Path(buffer.value) == target:
                target = Path.home()
                self.assertGreater(kernel.GetShortPathNameW(str(target), buffer, len(buffer)), 0)
                if Path(buffer.value) == target:
                    self.skipTest('Neither volume has a distinct 8.3 spelling')
            for name in (target, Path(buffer.value)):
                result = self.refusal(name)
                self.assertEqual(result['code'], 'UPGRADE_TARGET_NOT_INSTALLATION')
                self.assertEqual(Path(result['error']['diagnostics']['resolved_directory']), target.resolve())
                self.assertFalse(result['target_mutation_started'])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction semantics')
    def test_junction_and_ancestor_junction_are_refused_with_resolved_path(self):
        with temporary_workspace() as folder:
            root=Path(folder); real=root/'real'; real.mkdir(); (real/'child').mkdir()
            link=root/'junction'
            subprocess.run(['cmd.exe','/c','mklink','/J',str(link),str(real)], check=True, capture_output=True)
            try:
                for target in (link,link/'child'):
                    result=self.refusal(target); diag=result['error']['diagnostics']
                    self.assertEqual(result['code'],'UPGRADE_TARGET_INVALID')
                    self.assertEqual(diag['aliasing_kind'],'reparse_point')
                    self.assertEqual(Path(diag['resolved_directory']),target.resolve())
                    self.assertFalse(result['target_mutation_started'])
            finally:
                link.rmdir()

    def test_schema_ranges_and_refusal_status_preserve_existing_codes(self):
        import motion_server
        schemas={t.name:t.input_schema for t in asyncio.run(motion_server.mcp.list_tools())}
        with patch('motion_server.call') as call, patch('motion_server.enqueue') as enqueue:
            for name in ('list_mate_references','list_drive_candidates'):
                budget=schemas[name]['properties']['mate_context_budget_s']
                self.assertEqual((budget['minimum'],budget['maximum']),(1,30))
                for number,code in ((31,'INVALID_MATE_CONTEXT_BUDGET'),(0,'INVALID_MATE_CONTEXT_BUDGET'),
                                    ('10','INVALID_ARGUMENT'),(True,'INVALID_ARGUMENT')):
                    result=asyncio.run(motion_server.mcp.call_tool(name,{'model_id':'m','mate_context_budget_s':number}))
                    error=result.structured_content['error']
                    self.assertEqual(error['code'],code)
                    self.assertEqual(error['next_action']['options_status'],'user_parameter_correction_required')
                    self.assertFalse(error['next_action']['automatic_retry'])
                    self.assertFalse(error['diagnostics']['cad_dispatched'])
                for field,number,code in (('limit',0,'LIMIT_OUT_OF_RANGE'),('face_offset',-1,'INVALID_FACE_OFFSET')):
                    result=asyncio.run(motion_server.mcp.call_tool(name,{'model_id':'m',field:number}))
                    self.assertEqual(result.structured_content['error']['code'],code)
                    self.assertEqual(result.structured_content['error']['next_action']['options_status'],'user_parameter_correction_required')
            call.assert_not_called();enqueue.assert_not_called()

    def test_rich_failed_envelope_reserves_review_and_timing_across_outer_variations(self):
        review=['requested_and_native_output_settings_match','selected_native_motor_and_relative_body',
                'constraints_and_allowed_motion_range','explicit_duration_s_and_output_fps_within_new_solve_budget']
        perf={'schema_version':1,'scope':'sequential_native_body','total_elapsed_ms':27702.56,
              'execution_completed':True,'phase_count':27,'slowest_phases_ms':{'restore':9066.96,'preflight':5481.63,'motor':4400.57},
              'projection_scope':'top_three_only_full_saved_artifact_via_get_run_artifacts'}
        drive={'ComponentId':'component_'+'a'*24,'EntityId':'entity_'+'b'*24,'Kind':'rotary','Speed':10,
               'AxisLocal':[0,0,-1],'PointLocal':[.4,0,.02],'Reverse':False,'description':'x'*20000}
        motor={'native_feature_id':100,'native_feature_name':'motor','identity_source':'native_persistent_reference',
               'persistent_reference_resolved':True,'identity_fallback_used':False,'inventory_complete':True,
               'component_id':drive['ComponentId'],'parameters':drive,'padding':'x'*20000}
        base='C:/Installation with a long but valid directory name/'+'segment/'*18
        artifacts={'run_id':'c'*32,'manifest_path':base+'solve.json','time_axis_file':base+'time-axis.json',
                   'solve_performance_file':base+'solve-performance.json','solve_performance_sha256':'d'*64}
        with temporary_workspace() as folder:
            for count in (0,30,64,256,900):
                job={'job_id':'e'*32,'status':'failed','operation':'run_motion_study',
                     'service_observed_at':'x'*count,'progress':{'stage':'sampling','frames':18,'requested':151,'metadata':'x'*count},
                     'error':operational_error('MOTION_RESULTS_INCOMPLETE','时间轴不完整。'*100,'restored',
                             {'details':{'review_items':review},'requested_drive':drive,'native_motor_snapshot':motor,
                              'solve_performance':perf,'artifacts':artifacts,'time_selection_audit':{'status':'checked','rows':['details'*300]*10},
                              'sampling_performance':{'total_ms':20000,'rows':['details'*300]*10},
                              'sampling_api_batch':{'enabled':True,'rows':['details'*300]*10},
                              'drive_validation':{'status':'pass','direction_verified':False,'unit':'rpm'},
                              'component_name_resolution':{'resolved_count':10,'components':['name'*100]*10},
                              'padding':'x'*40000})}
                value=payload.bound(Path(folder),job)
                self.assertEqual(value['evidence']['review_items']['value'],review)
                self.assertEqual(value['evidence']['solve_performance']['value'],perf)
                self.assertEqual(value['evidence']['requested_drive']['value']['PointLocal'],drive['PointLocal'])
                self.assertEqual(value['evidence']['native_motor_snapshot']['conclusion']['identity_fallback_used'],False)
                self.assertEqual(value['response_wire_bytes'],payload.wire_size(value))
                self.assertLessEqual(payload.wire_size(value),16000)
                self.assertEqual(value['summary_omitted_paths_shown'],len(value['summary_omitted_paths']))
                row=value['evidence']['review_items']; args=row['read']['arguments']
                read=payload.read(Path(folder),job['job_id'],args['response_artifact_id'],0,2000,row['path'])
                self.assertEqual(json.loads(read['text']),review)

    def test_compiled_snapshot_is_immutable_bounded_expiring_and_state_bound(self):
        source=r'''using System;using System.Collections.Generic;
class Check {static void Refuse(Action a){try{a();}catch(InvalidOperationException){return;}throw new Exception("not refused");}
static void Main(){var clock=new DateTime(2026,1,1);var c=new GeometryPageSnapshots(()=>clock);var original=new Dictionary<string,object>{{"value","original"}};
string id=c.Put("query","guard",original);original["value"]="mutated";if((string)c.Get(id,"query","guard")["value"]!="original")throw new Exception("not frozen");
var clone=c.Get(id,"query","guard");clone["value"]="mutated";if((string)c.Get(id,"query","guard")["value"]!="original")throw new Exception("not isolated");
Refuse(()=>c.Get(id,"changed query","guard"));Refuse(()=>c.Get(id,"query","changed guard"));
for(int i=0;i<8;i++){clock=clock.AddSeconds(1);c.Put("query","guard",original);}Refuse(()=>c.Get(id,"query","guard"));
id=c.Put("query","guard",original);clock=clock.AddMinutes(10);Refuse(()=>c.Get(id,"query","guard"));
Refuse(()=>c.Put("query","guard",new string('x',8388609)));Console.WriteLine("snapshot policy passed");}}
'''
        with temporary_workspace() as folder:
            root=Path(folder);pure=root/'Cache.cs';check=root/'Check.cs';exe=root/'Check.exe'
            pure.write_text((ROOT/'executor/GeometryPageSnapshots.cs').read_text(encoding='utf-8').split('public partial class Cad {')[0],encoding='utf-8')
            check.write_text(source,encoding='utf-8')
            compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe),str(pure),str(check)],check=True,capture_output=True)
            self.assertIn(b'snapshot policy passed',subprocess.check_output([str(exe)]))

    def test_verified_baseline_candidate_has_exact_read_after_large_summary(self):
        candidate={'status':'eligible_saved_input_verified','run_id':'f'*32,'automatic_rebinding':False}
        job={'job_id':'a'*32,'result':{'assertion':'pass','run_id':'f'*32,
             'baseline_candidate':candidate,'requested_criteria':{'padding':'x'*30000}}}
        with temporary_workspace() as folder:
            root=Path(folder); value=payload.bound(root,job)
            row=value['evidence']['baseline_candidate']
            self.assertEqual(row['value'],candidate)
            data=payload.read(root,job['job_id'],value['full_response_sha256'],0,2000,row['path'])
            self.assertEqual(json.loads(data['text']),candidate)


if __name__ == '__main__':
    unittest.main()
