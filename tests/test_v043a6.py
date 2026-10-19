import ast
import asyncio
import json
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_service import temporary_workspace
import test_v043a5 as previous
from test_v043a5 import failed_job
from sw_mcp import job_payload as payload
from sw_mcp.validation import refuse, packed

ROOT=Path(__file__).resolve().parents[1]


class FeedbackTests(unittest.TestCase):
    def test_every_literal_input_refusal_has_an_explicit_expected_classification(self):
        tree=ast.parse((ROOT/'motion_server.py').read_text(encoding='utf-8'))
        codes={n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call)
               and isinstance(n.func,ast.Name) and n.func.id=='InputRefusal' and n.args and isinstance(n.args[0],ast.Constant)}
        parameters={'INVALID_ARGUMENT','INVALID_ASSEMBLY_PATH','INVALID_ASSEMBLY_TYPE','ASSEMBLY_FILE_UNAVAILABLE',
                    'DURATION_OR_FPS_OUT_OF_RANGE','CHECKPOINT_ID_MISUSED','LIMIT_OUT_OF_RANGE','INVALID_FACE_OFFSET',
                    'INVALID_MATE_CONTEXT_BUDGET','INVALID_GEOMETRY_SCAN_BUDGET','SPEED_OUT_OF_RANGE',
                    'INVALID_MATE_PARAMETERS','INVALID_POSE_BUDGET','MINIMUM_TRAVEL_OUT_OF_RANGE',
                    'INCOMPATIBLE_REPLAY_OPTIONS','INVALID_RESET_OPTIONS'}
        self.assertEqual(codes,parameters|{'CONFIRMATION_REQUIRED'},'New refusal codes require a deliberate classification')
        for code in parameters:
            with self.subTest(code=code):
                action=refuse(code,'Review explicit parameters').structured_content['error']['next_action']
                self.assertEqual(action['options_status'],'user_parameter_correction_required')
                self.assertFalse(action['automatic_retry'])
        self.assertEqual(refuse('UNKNOWN_TOOL','unknown').structured_content['error']['next_action']['options_status'],
                         'no_safe_parameter_change_inferred_from_error_code')

    def test_real_tool_refusals_cover_all_six_previously_missing_codes_without_dispatch(self):
        import motion_server as server
        mate={'model_id':'m','entity_a':'a','entity_b':'b','mate_type':'parallel'}
        cases=[('import_assembly',{'path':'relative.SLDASM'},'INVALID_ASSEMBLY_PATH'),
               ('import_assembly',{'path':str(ROOT/'invalid.SLDPRT')},'INVALID_ASSEMBLY_TYPE'),
               ('preview_mate',{**mate,'distance_mm':1},'INVALID_MATE_PARAMETERS'),
               ('preview_mate',{**mate,'maximum_translation_mm':10001},'INVALID_POSE_BUDGET'),
               ('reset_study_time',{'model_id':'m','study':'s','reset_output_fps':30},'INVALID_RESET_OPTIONS'),
               ('reset_study_time',{'model_id':'m','study':'s','create_new_model':True},'INVALID_RESET_OPTIONS'),
               ('replay_motion_frame',{'run_id':'r','frame':0,'saved_image_only':True,'use_input_snapshot':True},'INCOMPATIBLE_REPLAY_OPTIONS')]
        with patch.object(server,'call') as call,patch.object(server,'enqueue') as enqueue:
            for tool,args,code in cases:
                value=asyncio.run(server.mcp.call_tool(tool,args)).structured_content
                self.assertEqual(value['error']['code'],code)
                self.assertEqual(value['error']['next_action']['options_status'],'user_parameter_correction_required')
            confirm=asyncio.run(server.mcp.call_tool('apply_mate',{'plan_id':'a'*32,'confirmed':False})).structured_content
            self.assertEqual(confirm['error']['next_action']['options_status'],'explicit_human_confirmation_required')
            plan=asyncio.run(server.mcp.call_tool('apply_mate',{'plan_id':'','confirmed':True})).structured_content
            self.assertEqual(plan['error']['next_action']['options_status'],'tool_identified_arguments_require_user_input')
            call.assert_not_called();enqueue.assert_not_called()

    def test_every_summarized_omission_declares_degradation_with_exact_read(self):
        with temporary_workspace() as folder:
            for description in (0,1000,4000,10000):
                for rows in (0,1,4,10):
                    for progress in (0,100,3000):
                        job=failed_job(description,rows);job['progress']['padding']='p'*progress
                        value=payload.bound(Path(folder),job)
                        self.assertLessEqual(payload.wire_size(value),16000)
                        if value.get('response_summarized'):
                            self.assertTrue(value['summary_degraded']);self.assertTrue(value['summary_requires_artifact_read'])
                            self.assertIn('full_response_read',value)

    def test_name_timing_scalars_are_partial_inline_and_full_rows_remain_readable(self):
        original={'schema_version':3,'total_elapsed_ms':18.1,'batch_enter_ms':7.1,'component_loop_ms':6.9,
                  'export_and_assemble_ms':3.3,'phase_elapsed_ms':18.2,'components':['large row'*1000]*10}
        with temporary_workspace() as folder:
            value=payload.bound(Path(folder),{'job_id':'a'*32,'result':{'component_name_resolution':original}})
            row=value['evidence']['component_name_resolution'];self.assertTrue(row['value_is_partial'])
            self.assertEqual(row['value']['export_and_assemble_ms'],3.3);self.assertNotIn('components',row['value'])
            read=payload.read(Path(folder),'a'*32,value['full_response_sha256'],0,2000,'/result/component_name_resolution/phase_elapsed_ms')
            self.assertEqual(json.loads(read['text']),18.2)

    def test_minimal_envelope_still_reserves_short_review_and_conclusions(self):
        job=failed_job();details=job['error']['diagnostics']['details']
        details['drive_validation']={'status':'fail','unit':'rpm','requested':10,'observed_signed':0}
        for i,kind in enumerate(payload.EVIDENCE_KINDS):
            if kind not in ('review_items','drive_validation'):
                details['long_wrapper_'+str(i)+'x'*350]={kind:{'description':'x'*10000}}
        with temporary_workspace() as folder:
            value=payload.bound(Path(folder),job)
            self.assertLessEqual(payload.wire_size(value),16000)
            self.assertIn('selected_native_motor_and_relative_body',value['evidence']['review_items']['value'])
            self.assertEqual(value['evidence']['drive_validation']['conclusion']['status'],'fail')

    def test_geometry_budget_schema_refusal_and_valid_forwarding(self):
        import motion_server as server
        for name in ('list_mate_references','list_drive_candidates'):
            tool=next(t for t in asyncio.run(server.mcp.list_tools()) if t.name==name)
            prop=tool.input_schema['properties']['geometry_scan_budget_s']
            self.assertEqual((prop['minimum'],prop['maximum']),(1,60))
            with patch.object(server,'call',return_value=packed({'accepted':True})) as call,patch.object(server,'enqueue',return_value=packed({'accepted':True})) as enqueue:
                for bad in (True,0,61,'30'):
                    refusal=asyncio.run(server.mcp.call_tool(name,{'model_id':'m','geometry_scan_budget_s':bad})).structured_content
                    self.assertIn(refusal['error']['code'],('INVALID_ARGUMENT','INVALID_GEOMETRY_SCAN_BUDGET'))
                call.assert_not_called();enqueue.assert_not_called()
                for sync in (False,True):
                    value=asyncio.run(server.mcp.call_tool(name,{'model_id':'m','geometry_scan_budget_s':30,'wait_for_completion':sync})).structured_content
                    self.assertTrue(value['accepted'])
                self.assertEqual(enqueue.call_args.args[1]['geometry_scan_budget_s'],30)
                self.assertEqual(call.call_args.kwargs['geometry_scan_budget_s'],30)

    def test_compiled_exclusive_sampling_envelope_does_not_sum_nested_API_totals(self):
        source=r'''using System;using System.Collections.Generic;using System.Web.Script.Serialization;
class Check {static void Main(){var json=new JavaScriptSerializer();var selected=new[]{new Dictionary<string,object>{{"set_time_ms",800.0}}};var poses=new[]{new Dictionary<string,object>{{"names_ms",80.0}}};var exclusive=new Dictionary<string,double>{{"batch_enter_ms",100},{"selection_wrapper_ms",810},{"pose_reader_wrapper_ms",85}};var d=json.Deserialize<Dictionary<string,object>>(json.Serialize(SamplingPerformance.Summary(selected,poses,1000,10,exclusive)));if(Convert.ToDouble(d["unattributed_elapsed_ms"])!=5||Convert.ToDouble(d["exclusive_attributed_elapsed_ms"])!=995)throw new Exception("nested double count");if(GeometryScanBudget.ValidSeconds(double.NaN)||GeometryScanBudget.ValidSeconds(61)||!GeometryScanBudget.ValidSeconds(60))throw new Exception("budget range");Console.WriteLine("exclusive accounting passed");}}
'''
        previous.FeedbackTests.compile_check(self,source,['SamplingPerformance.cs','GeometryScanBudget.cs'],'exclusive accounting passed')

    def test_compiled_parent_phase_boundary_includes_export_work(self):
        source=r'''using System;using System.Collections.Generic;using System.Web.Script.Serialization;
class Check {static void Main(){double clock=0;var p=new SolvePerformance(()=>clock);clock=2;p.Phase("resolve_component_names");clock=17;double childBeforeExport=15;clock=21;double parent=p.Phase("next");if(parent!=19||parent-childBeforeExport!=4)throw new Exception("lost export envelope");Console.WriteLine("parent phase passed");}}
'''
        previous.FeedbackTests.compile_check(self,source,['SolvePerformance.cs'],'parent phase passed')

    def test_real_stdio_isolated_suite_tolerates_other_installation_activity(self):
        import grid_protocol_checks as suite
        with temporary_workspace() as folder:
            root=Path(folder);(root/'runs').mkdir();journal=root/'runs/executor-state.json';journal.write_text('test installation')
            stop=threading.Event()
            def other_installation():
                counter=0
                while not stop.wait(.03):
                    counter+=1;journal.write_text(str(counter))
            worker=threading.Thread(target=other_installation);worker.start()
            try:
                with patch.object(suite,'ROOT',root):_,report=asyncio.run(suite.check(ROOT))
                self.assertTrue(report['all_passed']);self.assertTrue(report['isolated_sentinel_unchanged'])
                self.assertFalse(report['live_primary_journal_checked'])
            finally:stop.set();worker.join(10)


if __name__=='__main__':unittest.main()
