import asyncio
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch, AsyncMock

from scripts.upgrade import upgrade, UpgradeFailure
from sw_mcp import job_payload as payload
from sw_mcp.validation import packed
from test_service import temporary_workspace

ROOT=Path(__file__).resolve().parents[1]


class FeedbackTests(unittest.TestCase):
    def test_ascii_json_covers_wrapper_python_resolution_failure(self):
        with temporary_workspace() as folder:
            def q(value):return "'"+str(value).replace("'","''")+"'"
            command="function Get-Command { throw 'injected discovery failure' }; & "+q(ROOT/'upgrade.ps1')+' -SourcePackage '+q(Path(folder)/'unused.zip')+' -TargetDir '+q(folder)+' -DryRun -AsciiJson; exit $LASTEXITCODE'
            result=subprocess.run([shutil.which('powershell.exe'),'-NoProfile','-ExecutionPolicy','Bypass','-Command',command],capture_output=True,timeout=20)
            self.assertEqual(result.returncode,1);self.assertTrue(result.stdout.isascii())
            value=json.loads(result.stdout)
            self.assertEqual(value['code'],'UPGRADE_WRAPPER_START_FAILED')
            self.assertEqual(value['failure_stage'],'resolve_python')
            self.assertFalse(value['python_started']);self.assertFalse(value['target_mutation_started'])
            self.assertTrue(value['dry_run'])

    def test_review_priority_at_failed_envelope_boundary(self):
        review=['requested_and_native_output_settings_match','selected_native_motor_and_relative_body',
                'constraints_and_allowed_motion_range','explicit_duration_s_and_output_fps_within_new_solve_budget']
        job={'job_id':'e'*32,'status':'failed','error':{'code':'MOTION_RESULTS_INCOMPLETE','message':'failed',
             'review_items':review,'diagnostics':{'padding':'x'*9000}},
             'result':{f'field_{i}_'+'z'*400:'v'*9000 for i in range(30)}}
        projection=payload.evidence_projection
        def reserve_trimmed(*args):
            rows=projection(*args);rows['review_items'].pop('value',None);return rows
        with temporary_workspace() as folder, patch.object(payload,'evidence_projection',reserve_trimmed):
            value=payload.bound(Path(folder),job)
            self.assertEqual(value['evidence']['review_items']['value'],review)
            self.assertGreater(len(value['summary_omitted_paths']),0)
            self.assertTrue(value['summary_omitted_paths_truncated'])
            self.assertEqual(value['summary_omitted_paths_shown'],len(value['summary_omitted_paths']))
            self.assertEqual(value['response_wire_bytes'],payload.wire_size(value))
            self.assertLessEqual(payload.wire_size(value),16000)

    def test_component_name_resolution_has_direct_exact_read(self):
        original={'registered_count':500,'rows':['details'*1000]*500}
        job={'job_id':'a'*32,'result':{'component_name_resolution':original}}
        with temporary_workspace() as folder:
            root=Path(folder);value=payload.bound(root,job);row=value['evidence']['component_name_resolution']
            self.assertNotIn('value',row)
            args=row['read']['arguments']
            read=payload.read(root,args['job_id'],args['response_artifact_id'],0,2000,row['path']+'/registered_count')
            self.assertEqual(json.loads(read['text']),500)

    def test_missing_and_noninstallation_target_codes_are_distinct(self):
        with temporary_workspace() as folder:
            for target,code in ((Path(folder),'UPGRADE_TARGET_NOT_INSTALLATION'),(Path(folder)/'missing','UPGRADE_TARGET_MISSING')):
                with self.assertRaises(UpgradeFailure) as caught:upgrade('unused.zip',target,sys.executable,dry_run=True)
                self.assertEqual(caught.exception.payload()['code'],code)

    def test_aliased_target_is_generic_invalid_before_installation_check(self):
        with temporary_workspace() as folder, patch.object(Path,'resolve',return_value=Path('different-root')):
            with self.assertRaises(UpgradeFailure) as caught:upgrade('unused.zip',folder,sys.executable,dry_run=True)
            self.assertEqual(caught.exception.code,'UPGRADE_TARGET_INVALID')
            self.assertIn('Aliased installation root',str(caught.exception))

    def test_query_budget_rejects_invalid_parameters_without_dispatch(self):
        import motion_server
        with patch('motion_server.call') as call,patch('motion_server.enqueue') as enqueue:
            for name in ('list_mate_references','list_drive_candidates'):
                for value in (True,'20',None,0,31,float('inf')):
                    result=asyncio.run(motion_server.mcp.call_tool(name,{'model_id':'m','mate_context_budget_s':value}))
                    error=result.structured_content['error']
                    self.assertTrue(result.is_error)
                    self.assertEqual(error['diagnostics']['field'],'mate_context_budget_s')
                    self.assertFalse(error['diagnostics']['cad_dispatched'])
            call.assert_not_called();enqueue.assert_not_called()

    def test_query_budget_default_and_explicit_forwarding(self):
        import motion_server
        for name in ('list_mate_references','list_drive_candidates'):
            for seconds in (None,20):
                with patch('motion_server.call',new_callable=AsyncMock,return_value=packed({'ok':True})) as call:
                    args={'model_id':'m','component_id':'c','kind':'planar_normal','cursor':'cursor','face_offset':12,'detail_level':'compact'}
                    if seconds is not None:args['mate_context_budget_s']=seconds
                    asyncio.run(getattr(motion_server,name)(**args))
                    forwarded=call.call_args.kwargs
                    self.assertEqual(forwarded['mate_context_budget_s'],10 if seconds is None else seconds)
                    self.assertEqual(forwarded['cursor'],'cursor');self.assertEqual(forwarded['face_offset'],12)

    def test_query_guidance_survives_async_summary(self):
        guidance={'tool':'list_mate_references','arguments':{'model_id':'m','cursor':'','mate_context_budget_s':20},'automatic_retry':False}
        job={'job_id':'b'*32,'result':{'next_cursor':'real-cursor','mate_context_complete':False,
             'mate_context_warning':'关联不完整','mate_context_next_query':guidance,'padding':'x'*30000}}
        with temporary_workspace() as folder:
            value=payload.bound(Path(folder),job)
            self.assertEqual(value['query_controls']['mate_context_next_query'],guidance)
            self.assertFalse(value['query_controls']['mate_context_complete'])

    def test_compiled_budget_policy_and_explicit_rescan_contract(self):
        source=r'''using System;using System.Collections.Generic;using System.Web.Script.Serialization;
class Check {static void Main(){if(MateContextBudgetPolicy.Valid(double.NaN)||MateContextBudgetPolicy.Valid(31)||MateContextBudgetPolicy.Valid(.5))throw new Exception("invalid accepted");
if(MateContextBudgetPolicy.Milliseconds(10)!=10000||MateContextBudgetPolicy.Milliseconds(20)!=20000||MateContextBudgetPolicy.Next(20)!=30||MateContextBudgetPolicy.Next(30).HasValue)throw new Exception("budget arithmetic");
var args=new Dictionary<string,object>{{"model_id","m"},{"cursor","old"},{"component_id","c"},{"kind","planar_normal"},{"face_offset",12},{"detail_level","compact"}};var result=new Dictionary<string,object>();
MateContextBudgetPolicy.Apply(result,false,true,"list_mate_references",args,10);Console.WriteLine(new JavaScriptSerializer().Serialize(result));
if((string)args["cursor"]!="old")throw new Exception("mutated original query");
MateContextBudgetPolicy.Apply(result,false,true,"list_mate_references",args,30);if(result["mate_context_next_query"]!=null)throw new Exception("unbounded retry");
MateContextBudgetPolicy.Apply(result,true,false,"list_mate_references",args,10);if(result["mate_context_warning"]!=null||result["mate_context_next_query"]!=null)throw new Exception("false warning");}}
'''
        with temporary_workspace() as folder:
            cs=Path(folder)/'Check.cs';exe=Path(folder)/'Check.exe';cs.write_text(source,encoding='utf-8')
            compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe),str(ROOT/'executor/MateContextBudgetPolicy.cs'),str(cs)],check=True,capture_output=True)
            value=json.loads(subprocess.check_output([str(exe)]))
            self.assertFalse(value['mate_context_complete']);self.assertTrue(value['mate_context_warning'])
            query=value['mate_context_next_query'];self.assertFalse(query['automatic_retry'])
            self.assertTrue(query['preserve_geometry_pending_queue'])
            self.assertEqual(query['arguments']['cursor'],'');self.assertEqual(query['arguments']['face_offset'],12)
            self.assertEqual(query['arguments']['mate_context_budget_s'],20)
            self.assertFalse(query['arguments']['wait_for_completion'])


if __name__=='__main__':unittest.main()
