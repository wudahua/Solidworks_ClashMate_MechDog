"""Idle bridge handoff and request identity regressions; no CAD in these tests."""
import asyncio
import concurrent.futures
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
import uuid

from sw_mcp.bridge import Bridge,CadError
from sw_mcp.jobs import Jobs,JobLookupError
from sw_mcp.conversation import core,motion_tasks
from sw_mcp.conversation.formal_engine import FormalEngine
from sw_mcp.conversation.owner_transport import fingerprint
from sw_mcp.task_errors import task_failure
from sw_mcp.validation import packed,InputRefusal

ROOT=Path(__file__).resolve().parents[1]


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'runs/legacy-handoff-tests'/uuid.uuid4().hex[:8];self.folder.mkdir(parents=True)
        self.source=self.folder/'fixture.SLDASM';self.source.write_bytes(b'no CAD fixture')
        b=self.bridge=Bridge(self.folder)
        self.engine=e=FormalEngine.__new__(FormalEngine)
        e.source_fingerprint=fingerprint();e.managed_upgrade_guard=False
        e.tasks=SimpleNamespace(active=None,prior_unfinished=[],sessions={},tasks={},work=self.folder/'work')
        e.product=SimpleNamespace(ROOT=self.folder,bridge=b,jobs=SimpleNamespace(_jobs={},bridge=b),artifacts=object(),
            mcp=SimpleNamespace(call_tool=AsyncMock(return_value=packed({'ok':True,'result':{'fixture':True}}))))
        self.addCleanup(lambda:e.product.bridge.close())
        self.addCleanup(b.close)

    def child(self):
        b=self.bridge
        process=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.buffer.read()'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        b._process=process;b._startup.set_result({'protocol_version':1,'ready':True,'process_id':999})
        b._ever_dispatched=True;b._acquire_lease()
        b._journal({'status':'idle','owner_id':b._owner_id,'executor_pid':process.pid,'solidworks_pid':999,'operation':'get_environment'})
        def cleanup():
            if not process.stdin.closed:process.stdin.close()
            process.wait(timeout=10);process.stdout.close()
        self.addCleanup(cleanup)
        return process

    def prepare(self):return self.engine.tool('prepare_mechanism_task',{'assembly_path':str(self.source)})

    def test_live_idle_retained_child_exits_by_EOF_and_prepare_reaches_handler(self):
        p=self.child();journal=self.bridge._journal_path.read_bytes()
        value=self.prepare()['structuredContent']
        proof=value['legacy_session_handoff'];self.assertTrue(proof['automatic_idle_handoff']);self.assertEqual(p.poll(),0)
        self.assertFalse(proof['force_kill']);self.assertFalse(proof['CAD_exit_requested'])
        self.assertEqual(self.bridge._journal_path.read_bytes(),journal)
        self.assertIsNot(self.engine.product.bridge,self.bridge)
        self.assertIs(self.engine.product.jobs.bridge,self.engine.product.bridge)
        self.engine.product.mcp.call_tool.assert_awaited_once()

    def test_exited_retained_Popen_does_not_permanently_block_prepare(self):
        p=self.child();p.stdin.close();p.wait(timeout=10)
        self.assertTrue(self.prepare()['structuredContent']['legacy_session_handoff']['confirmed'])

    def test_queued_job_stays_on_original_bridge_with_specific_read_hint(self):
        p=self.child();self.engine.product.jobs._jobs={'a'*32:{'job_id':'a'*32,'status':'queued'}}
        with self.assertRaises(core.StopBatch) as error:self.prepare()
        self.assertEqual(error.exception.code,'LEGACY_SESSION_REQUIRES_FINISH')
        action=task_failure(error.exception.code,str(error.exception),error.exception.diagnostics)['next_action']
        self.assertEqual(action['tool'],'get_job');self.assertEqual(action['arguments'],{'job_id':'a'*32})
        self.assertIsNone(p.poll());self.assertFalse(p.stdin.closed);self.engine.product.mcp.call_tool.assert_not_called()

    def test_unknown_pending_quarantine_inconsistent_and_unowned_never_send_EOF(self):
        p=self.child();base=self.bridge.recovery_state()
        cases=[{'status':'unknown'},{'owner_id':'other'},{'executor_pid':p.pid+1},{'solidworks_pid':998},
               {'dispatch_state':'dispatching'},{'recovery_required':True}]
        for changes in cases:
            # Write a literal contradictory journal for consistency cases.
            core.write(self.bridge._journal_path,{**base,**changes})
            with self.subTest(changes=changes),self.assertRaises(core.StopBatch) as error:self.prepare()
            self.assertEqual(error.exception.code,'NATIVE_STATE_UNKNOWN');self.assertFalse(p.stdin.closed)
        core.write(self.bridge._journal_path,base)
        self.bridge._pending['x']=concurrent.futures.Future()
        with self.assertRaises(core.StopBatch):self.prepare()
        self.bridge._pending.clear();self.bridge._quarantined_request='x'
        with self.assertRaises(core.StopBatch):self.prepare()
        self.assertFalse(p.stdin.closed);self.engine.product.mcp.call_tool.assert_not_called()

    def test_missing_retained_lease_does_not_authorize_EOF(self):
        p=self.child();self.bridge._lease.close();self.bridge._lease=None
        with self.assertRaises(core.StopBatch) as error:self.prepare()
        self.assertEqual(error.exception.code,'NATIVE_STATE_UNKNOWN');self.assertFalse(p.stdin.closed)

    def test_bridge_request_lock_prevents_handoff(self):
        p=self.child();self.bridge._lock.acquire()
        try:
            with self.assertRaises(core.StopBatch):self.prepare()
        finally:self.bridge._lock.release()
        self.assertFalse(p.stdin.closed)

    def test_incomplete_or_exceptional_handshake_never_authorizes_handoff(self):
        p=self.child()
        for completed in (False,True):
            self.bridge._startup=concurrent.futures.Future()
            if completed:self.bridge._startup.set_exception(RuntimeError('bad handshake'))
            with self.assertRaises(core.StopBatch) as error:self.prepare()
            self.assertEqual(error.exception.code,'NATIVE_STATE_UNKNOWN');self.assertFalse(p.stdin.closed)

    def test_unknown_journal_without_retained_child_is_not_erased_or_bypassed(self):
        self.bridge._journal({'status':'unknown','executor_pid':123})
        before=self.bridge._journal_path.read_bytes()
        with self.assertRaises(core.StopBatch) as error:self.prepare()
        self.assertEqual(error.exception.code,'NATIVE_STATE_UNKNOWN');self.assertEqual(before,self.bridge._journal_path.read_bytes())
        self.engine.product.mcp.call_tool.assert_not_called()

    def test_historical_idle_record_alone_is_not_treated_as_owned_process(self):
        self.bridge._journal({'status':'idle','owner_id':'historic','executor_pid':123})
        before=self.bridge._journal_path.read_bytes();value=self.prepare()['structuredContent']
        self.assertNotIn('legacy_session_handoff',value);self.assertEqual(before,self.bridge._journal_path.read_bytes())

    def test_failed_EOF_retains_bridge_and_lease_and_no_task_dispatch(self):
        self.child()
        with patch('sw_mcp.conversation.formal_engine.release_executor',side_effect=core.StopBatch('EXECUTOR_EXIT_UNCONFIRMED')):
            with self.assertRaises(core.StopBatch) as error:self.prepare()
        self.assertEqual(error.exception.code,'EXECUTOR_EXIT_UNCONFIRMED')
        self.assertIs(self.engine.product.bridge,self.bridge);self.assertIsNotNone(self.bridge._lease)
        self.engine.product.mcp.call_tool.assert_not_called();self.assertIsNone(self.engine.tasks.active)

    def test_input_validation_precedes_any_automatic_handoff(self):
        p=self.child()
        with self.assertRaises(core.StopBatch):self.engine.tool('prepare_mechanism_task',{'assembly_path':str(self.source),'duration_s':6})
        self.assertFalse(p.stdin.closed)

    def test_idle_request_does_not_allow_switching_a_used_connection(self):
        self.child()
        with self.assertRaises(CadError) as error:self.bridge.select_startup_session('auto')
        self.assertEqual(error.exception.code,'STARTUP_SELECTION_NOT_ALLOWED')
        self.assertEqual(error.exception.diagnostics['startup_selection_blockers'],['connection_already_used'])
        self.assertFalse(self.bridge.recovery_state()['recovery_required'])


class IdentityAndParameterTests(unittest.TestCase):
    def test_job_format_missing_and_corrupt_are_distinct_and_not_rewritten(self):
        folder=ROOT/'runs/legacy-handoff-tests'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
        b=Bridge(folder);jobs=Jobs(b,folder);self.addCleanup(b.close);self.addCleanup(jobs._pool.shutdown)
        cases=[('job_'+'a'*32,'INVALID_JOB_ID'),('a'*8,'INVALID_JOB_ID'),('a'*32,'JOB_NOT_FOUND')]
        for identifier,code in cases:
            with self.subTest(identifier=identifier),self.assertRaises(JobLookupError) as error:jobs.get(identifier)
            self.assertEqual(error.exception.code,code);self.assertFalse(error.exception.diagnostics['identifier_rewritten'])
        core.write(folder/'runs/jobs'/('b'*32+'.json'),{'job_id':'wrong','status':'failed'})
        with self.assertRaises(JobLookupError) as error:jobs.get('b'*32)
        self.assertEqual(error.exception.code,'JOB_RECORD_INVALID')
        import motion_server
        with patch.object(motion_server,'jobs',jobs):
            with self.assertRaises(InputRefusal) as error:asyncio.run(motion_server.get_job('job_'+'a'*32))
        self.assertEqual(error.exception.code,'INVALID_JOB_ID')

    def test_gear_reports_requested_zero_and_full_signed_waveform_not_unused_95_percent(self):
        folder=ROOT/'runs/legacy-handoff-tests'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
        source=folder/'fixture.SLDASM';source.write_bytes(b'offline')
        for reverse in (True,False):
            _,p=motion_tasks.prepare_inputs(str(source),task_kind='gear_transmission',speed=60,duration_s=2,reverse_direction=reverse)
            self.assertNotIn('minimum_travel',p);self.assertEqual(p['requested_minimum_travel'],0)
            self.assertEqual(p['signed_target_travel_deg'],-720 if reverse else 720)
            self.assertEqual(p['input_waveform_tolerance_deg'],.1);self.assertEqual(p['external_ratio_tolerance_deg'],1e-4)
        self.assertEqual(motion_tasks.parameters('rotary',60,2,30,False,0)['minimum_travel'],684)


if __name__=='__main__':unittest.main(verbosity=2)
