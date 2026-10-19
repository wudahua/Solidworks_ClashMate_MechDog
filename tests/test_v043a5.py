import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock

from test_service import temporary_workspace
from sw_mcp import job_payload as payload
from sw_mcp.errors import operational_error
from sw_mcp.jobs import Jobs
from sw_mcp.validation import refuse
from sw_mcp.artifacts import Artifacts, PoseCursorMismatch

ROOT=Path(__file__).resolve().parents[1]


def failed_job(description=4000, rows=0, chain=False):
    review=['requested_and_native_output_settings_match','selected_native_motor_and_relative_body',
            'constraints_and_allowed_motion_range','explicit_duration_s_and_output_fps_within_new_solve_budget']
    drive={'ComponentId':'component_'+'a'*24,'EntityId':'entity_'+'b'*24,'Kind':'rotary',
           'Speed':10,'AxisLocal':[0,0,-1],'PointLocal':[.4,0,.02],'description':'x'*description}
    details={'review_items':review,'requested_drive':drive,
             'native_motor_snapshot':{'persistent_reference_resolved':False,'identity_fallback_used':True,
                                      'identity_source':'exact_feature_name_and_native_id','parameters':drive},
             'solve_performance':{'total_elapsed_ms':27702.56,'phase_count':27,
                                  'slowest_phases_ms':{'restore':9066.96,'preflight':5481.63,'motor':4400.57}}}
    if rows:details['sampling_performance']={'rows':['details'*300]*rows}
    if chain:details['original_failure']={'code':'NATIVE_INCOMPLETE','message':'native result incomplete'}
    return {'job_id':'a'*32,'status':'failed','operation':'run_user_study',
            'progress':{'stage':'sampling','frames':18,'requested':151},
            'error':operational_error('MOTION_RESULTS_INCOMPLETE','时间轴不完整。'*100,'restored',{'details':details})}


class FeedbackTests(unittest.TestCase):
    def test_medium_failed_envelopes_never_assert_and_exact_error_remains_readable(self):
        with temporary_workspace() as folder:
            root=Path(folder)
            for description in (0,1000,4000,10000):
                for rows in (0,4,10):
                    for chain in (False,True):
                        with self.subTest(description=description,rows=rows,chain=chain):
                            job=failed_job(description,rows,chain); value=payload.bound(root,job)
                            self.assertLessEqual(payload.wire_size(value),16000)
                            self.assertEqual(value['error']['code'],job['error']['code'])
                            self.assertEqual(value['error']['restoration_status'],'restored')
                            if value.get('response_summarized'):
                                self.assertEqual(value['response_wire_bytes'],payload.wire_size(value))
                                sha=value['full_response_sha256']
                                read=payload.read(root,job['job_id'],sha,0,2000,'/error/code')
                                self.assertEqual(json.loads(read['text']),job['error']['code'])
                                data=(root/'runs/job-responses'/job['job_id']/(sha+'.json')).read_bytes()
                                self.assertEqual(hashlib.sha256(data).hexdigest(),sha)

    def test_extreme_typed_evidence_degrades_to_bounded_exact_root_read(self):
        job=failed_job(); details=job['error']['diagnostics']['details']
        for index,kind in enumerate(payload.EVIDENCE_KINDS):
            details['wrapper_'+str(index)+'x'*350]={kind:{'description':'x'*10000}}
        with temporary_workspace() as folder:
            value=payload.bound(Path(folder),job)
            self.assertLessEqual(payload.wire_size(value),16000)
            self.assertTrue(value['summary_degraded']);self.assertTrue(value['summary_requires_artifact_read'])
            self.assertIn('full_response_read',value)
            self.assertFalse(value['error']['next_action']['automatic_retry'])

    def test_actual_get_job_tool_keeps_failed_job_readable_without_CAD(self):
        import motion_server
        with temporary_workspace() as folder:
            bridge=Mock();bridge.cad_operation_state={'state':'idle'}
            jobs=Jobs(bridge,Path(folder));job=failed_job(4000,0);jobs._persist(job)
            try:
                with patch.object(motion_server,'jobs',jobs):
                    value=asyncio.run(motion_server.mcp.call_tool('get_job',{'job_id':job['job_id']})).structured_content
                self.assertEqual(value['status'],'failed')
                self.assertEqual(value['error']['code'],'MOTION_RESULTS_INCOMPLETE')
                self.assertLessEqual(payload.wire_size(value),16000)
                bridge.request.assert_not_called()
            finally:jobs._pool.shutdown(wait=True)

    def test_confirmation_is_human_decision_and_never_parameter_correction(self):
        import motion_server
        with patch('motion_server.call') as call,patch('motion_server.enqueue') as enqueue:
            value=asyncio.run(motion_server.mcp.call_tool('apply_mate',{'plan_id':'a'*32,'confirmed':False})).structured_content
            self.assertEqual(value['error']['code'],'CONFIRMATION_REQUIRED')
            action=value['error']['next_action']
            self.assertEqual(action['options_status'],'explicit_human_confirmation_required')
            self.assertFalse(action['automatic_retry']);self.assertEqual(action['options'],[])
            call.assert_not_called();enqueue.assert_not_called()
        self.assertEqual(refuse('RECOVERY_REQUIRED','review recovery').structured_content['error']['next_action']['options_status'],
                         'no_safe_parameter_change_inferred_from_error_code')

    def test_geometry_summary_requires_complete_original_page_before_advancing(self):
        entities=[{'entity_id':str(i),'component_id':'c','detail':'x'*2000} for i in range(12)]
        job={'job_id':'b'*32,'result':{'entities':entities,'offset':5,'returned':12,'next_offset':17,
             'next_offset_delta':12,'next_cursor':'unchanged-native-token','total':22,'geometry_complete':False}}
        with temporary_workspace() as folder:
            root=Path(folder);value=payload.bound(root,job); controls=value['query_controls']
            self.assertTrue(controls['page_data_requires_artifact_read'])
            self.assertNotIn('entities',value.get('result',{}))
            self.assertEqual(controls['next_cursor'],'unchanged-native-token')
            read=payload.read(root,job['job_id'],value['full_response_sha256'],0,2000,'/result/returned')
            self.assertEqual(json.loads(read['text']),12)
            self.assertEqual(controls['page_read']['arguments']['response_json_pointer'],'/result')

    def test_pose_cursor_reports_mismatched_field_without_rewriting_filters(self):
        with temporary_workspace() as folder:
            artifact=Artifacts(Path(folder)); digest='d'*64
            token={'run_id':'a'*32,'component_id':'original','frame_start':0,'sha256':digest,'offset':5}
            cursor=base64.b64encode(json.dumps(token).encode()).decode()
            with patch.object(artifact,'_load',return_value=({},None,Path(folder)/'unused.csv')), \
                 patch.object(artifact,'_csv_info',return_value={'observed_poses_sha256':digest}):
                with self.assertRaises(PoseCursorMismatch) as caught:artifact.poses('a'*32,cursor=cursor)
            differences=caught.exception.diagnostics['mismatched_fields']
            self.assertEqual(differences,{'component_id':{'cursor_value':'original','request_value':''}})
            self.assertFalse(caught.exception.diagnostics['automatic_filter_rewrite'])

    def test_compiled_reduced_partial_pages_advance_and_never_self_reference(self):
        source=r'''using System;using System.Linq;using System.Text;using System.Collections.Generic;using System.Web.Script.Serialization;
class Check {static void Main(){var json=new JavaScriptSerializer();Func<int,string> cursor=offset=>Convert.ToBase64String(Encoding.UTF8.GetBytes(json.Serialize(new{snapshot_id="frozen",offset=offset})));
foreach(bool partial in new[]{true,false}){var response=new Dictionary<string,object>{{"padding",new string('x',11000)},{"geometry_complete",!partial},{"scope_geometry_complete",!partial}};
var page=Enumerable.Range(5,17).Select(i=>new Dictionary<string,object>{{"entity_id",i.ToString()},{"detail",new string('x',1000)}}).ToList();
GeometryPageBudget.Apply(response,page,5,22,20,cursor,x=>json.Serialize(x));int count=page.Count;
if(count<=0||count>=17||(int)response["next_offset"]!=5+count||(int)response["next_offset_delta"]!=count||(string)response["next_cursor"]==cursor(5)||(string)response["page_reduction_reason"]!="payload_byte_budget"||(bool)response["scope_geometry_complete"]==partial)throw new Exception("reduced partial page contract");
var end=new Dictionary<string,object>();var final=Enumerable.Range(20,2).Select(i=>new Dictionary<string,object>{{"entity_id",i.ToString()}}).ToList();GeometryPageBudget.Apply(end,final,20,22,20,cursor,x=>json.Serialize(x));if(end["next_cursor"]!=null||!(bool)end["frozen_pages_complete"])throw new Exception("end page");}
try{GeometryPageBudget.Apply(new Dictionary<string,object>(),new List<Dictionary<string,object>>{new Dictionary<string,object>()},5,22,20,i=>"self",x=>json.Serialize(x));throw new Exception("self accepted");}catch(InvalidOperationException){}
Console.WriteLine("reduced page policy passed");}}
'''
        self.compile_check(source,['GeometryPageBudget.cs'],'reduced page policy passed')

    def test_compiled_batch_profiles_enter_restore_and_previous_flag(self):
        source=r'''using System;using System.Threading;using System.Web.Script.Serialization;
class Check {static void Main(){bool flag=false;var batch=new NativeCommandBatch(()=>{Thread.Sleep(2);return flag;},value=>{Thread.Sleep(2);flag=value;});if(!flag)throw new Exception("not enabled");Thread.Sleep(2);batch.Dispose();var json=new JavaScriptSerializer();var d=json.Deserialize<System.Collections.Generic.Dictionary<string,object>>(json.Serialize(batch.Export()));if(flag||!(bool)d["restored"]||Convert.ToDouble(d["enter_elapsed_ms"])<4||Convert.ToDouble(d["restore_elapsed_ms"])<3||d["finished_at_utc"]==null)throw new Exception("missing batch timings");Console.WriteLine("batch profile passed");}}
'''
        self.compile_check(source,['NativeCommandBatch.cs'],'batch profile passed')

    def test_compiled_context_causes_distinguish_unsupported_references_from_budget(self):
        source=r'''using System;using System.Collections.Generic;using System.Web.Script.Serialization;
class Check {static void Main(){var json=new JavaScriptSerializer();foreach(string reason in new[]{"unsupported_reference_kind","budget_exhausted","feature_limit_exhausted","no_candidate_scope"}){
var c=new Dictionary<string,object>{{"unresolved_reference_count",reason=="unsupported_reference_kind"?1:0},{"unresolved_references",new[]{new Dictionary<string,object>{{"cause","unsupported_kind"}}}},{"feature_limit_exhausted",reason=="feature_limit_exhausted"},{"scan_attempted",reason!="no_candidate_scope"}};
var response=new Dictionary<string,object>{{"mate_context_scan",c}};MateContextBudgetPolicy.Apply(response,false,reason=="budget_exhausted","list_mate_references",new Dictionary<string,object>(),10);
if((string)response["mate_context_incomplete_reason"]!=reason)throw new Exception(json.Serialize(response));if((response["mate_context_next_query"]!=null)!=(reason=="budget_exhausted"))throw new Exception("misleading retry");}
Console.WriteLine("context causes passed");}}
'''
        self.compile_check(source,['MateContextBudgetPolicy.cs'],'context causes passed')

    def compile_check(self, source, production, expected):
        with temporary_workspace() as folder:
            root=Path(folder);cs=root/'Check.cs';exe=root/'Check.exe';cs.write_text(source,encoding='utf-8')
            compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            result=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe),
                                   *[str(ROOT/'executor'/name) for name in production],str(cs)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout.decode(errors='replace'))
            self.assertIn(expected,subprocess.check_output([str(exe)],text=True))


if __name__=='__main__':unittest.main()
