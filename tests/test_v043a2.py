import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.upgrade import upgrade, UpgradeFailure
from sw_mcp import job_payload as payload
from test_service import temporary_workspace

ROOT = Path(__file__).resolve().parents[1]


class FeedbackTests(unittest.TestCase):
    def test_early_failure_keeps_target_and_dry_run(self):
        with temporary_workspace() as folder:
            for dry in (False, True):
                target = Path(folder)/'missing'
                with self.assertRaises(UpgradeFailure) as caught:
                    upgrade('missing.zip', target, sys.executable, dry_run=dry)
                value = caught.exception.payload()
                self.assertEqual(value['code'], 'UPGRADE_TARGET_MISSING')
                self.assertEqual(value['dry_run'], dry)
                self.assertEqual(value['target_directory'], str(target.absolute()))
                self.assertFalse(value['target_mutation_started'])

    def test_ascii_json_cli_preserves_chinese_and_exit_status(self):
        with temporary_workspace() as folder:
            target=Path(folder);(target/'executor').mkdir();(target/'motion_server.py').write_text('x')
            command=[sys.executable,str(ROOT/'scripts/upgrade.py'),'--package',str(target/'missing.zip'),'--target',str(target),'--python',sys.executable,'--ascii-json','--dry-run']
            result=subprocess.run(command,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,1)
            self.assertTrue(result.stdout.isascii())
            value=json.loads(result.stdout)
            self.assertIn('缺少',value['error']['message'])
            self.assertTrue(value['dry_run'])

    def test_conditional_parameter_refusal_has_actionable_field_without_dispatch(self):
        import motion_server
        with patch.object(motion_server.jobs,'get') as get:
            result=asyncio.run(motion_server.mcp.call_tool('get_job',{'job_id':'a'*32,'response_json_pointer':'/error'}))
            value=result.structured_content
            self.assertEqual(value['error']['diagnostics']['field'],'response_artifact_id')
            self.assertEqual(value['error']['diagnostics']['required_when'],{'field':'response_json_pointer','present':True})
            self.assertFalse(value['error']['diagnostics']['cad_dispatched'])
            get.assert_not_called()

    def test_budget_boundary_keeps_real_readable_omission_paths(self):
        with temporary_workspace() as folder:
            root=Path(folder)
            # Vary the actual wire envelope around fitting boundaries. Each
            # returned pointer must read exact saved data, never a sentinel.
            for n in range(2,32):
                job={'job_id':'a'*32,'status':'failed','error':{'code':'FAILED','message':'x'*900,'diagnostics':{f'field_{i}':'v'*9000 for i in range(n)}}}
                value=payload.bound(root,job)
                self.assertTrue(value['summary_omitted_paths'])
                self.assertNotIn('/',value['summary_omitted_paths'])
                self.assertEqual(value['response_wire_bytes'],payload.wire_size(value))
                self.assertLessEqual(payload.wire_size(value),payload.BUDGET)
                self.assertEqual(value['summary_omitted_prefix_counts_limit'],8)
                for pointer in value['summary_omitted_paths']:
                    read=payload.read(root,job['job_id'],value['full_response_sha256'],0,2000,pointer)
                    self.assertTrue(read['text'])

    def test_long_pointer_never_becomes_fake_root_or_partial_token(self):
        with temporary_workspace() as folder:
            key='z'*18000
            job={'job_id':'b'*32,'result':{key:'x'*18000,'short':'x'*18000}}
            value=payload.bound(Path(folder),job)
            self.assertIn('/result/short',value['summary_omitted_paths'])
            self.assertNotIn('/',value['summary_omitted_paths'])
            self.assertTrue(value['summary_omitted_paths_truncated'])

    def test_review_refill_does_not_break_wire_limit_or_identity(self):
        job={'job_id':'c'*32,'result':{'requested_drive':{'ComponentId':'c','Axis':[0,0,1],'padding':'x'*30000},
             'review_items':['需要复核原生马达引用']*4,
             **{kind:{'padding':'x'*30000} for kind in payload.EVIDENCE_KINDS if kind not in ('requested_drive','review_items')}}}
        with temporary_workspace() as folder:
            value=payload.bound(Path(folder),job)
            self.assertEqual(value['evidence']['review_items']['value'],job['result']['review_items'])
            self.assertEqual(value['evidence']['requested_drive']['value']['ComponentId'],'c')
            data=Path(folder)/'runs/job-responses'/job['job_id']/(value['full_response_sha256']+'.json')
            self.assertEqual(hashlib.sha256(data.read_bytes()).hexdigest(),value['full_response_sha256'])
            self.assertLessEqual(payload.wire_size(value),payload.BUDGET)

    def test_admission_timer_freezes_sequential_accounting(self):
        with temporary_workspace() as folder:
            source=Path(folder)/'Check.cs';exe=Path(folder)/'Check.exe'
            source.write_text('using System;using System.Web.Script.Serialization; class Check {static void Main(){var t=new OperationTiming("admission");t.Start("a");t.Start("b");t.Finish();Console.WriteLine(new JavaScriptSerializer().Serialize(t.Export()));}}',encoding='utf-8')
            compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe),str(ROOT/'executor/OperationTiming.cs'),str(source)],check=True,capture_output=True)
            value=json.loads(subprocess.check_output([str(exe)]))
            self.assertEqual(value['scope'],'admission')
            self.assertEqual([row['stage'] for row in value['phases']],['a','b'])
            self.assertEqual(value['current_stage'],None)
            self.assertEqual(sum(row['elapsed_ms'] for row in value['phases'])+value['unattributed_elapsed_ms'],value['total_elapsed_ms'])


if __name__=='__main__':unittest.main()
