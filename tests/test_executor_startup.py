"""Cache integrity and pre-import lifecycle tests; fixtures are not CAD acceptance."""
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import time
import unittest
from unittest.mock import Mock, patch
import uuid

from sw_mcp.conversation import core, executor_build, mate_worker, startup_process
from sw_mcp.conversation.task_engine import TaskEngine
from sw_mcp.task_errors import task_failure

ROOT = Path(__file__).resolve().parents[1]


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.base = ROOT/'runs/startup-unit'/uuid.uuid4().hex[:10]
        self.runtime = self.base/'runtime';(self.runtime/'executor').mkdir(parents=True)
        (self.runtime/'executor/Program.cs').write_text('source one',encoding='utf-8')
        self.install = self.base/'install';redist = self.install/'api/redist';redist.mkdir(parents=True)
        for name in executor_build.INTEROP:(redist/name).write_bytes(name.encode())
        self.helper=self.base/'helper.cs';self.helper.write_bytes(b'helper one')
        compiler=self.base/'win/Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        compiler.parent.mkdir(parents=True);compiler.write_bytes(b'compiler one')
        self.compiler=compiler
        self.folder=self.base/'evidence';self.folder.mkdir()
        self.env=patch.dict(os.environ,{'WINDIR':str(self.base/'win')});self.env.start()
        self.run=patch.object(executor_build.subprocess,'run',side_effect=self.compile);self.mock_run=self.run.start()
    def tearDown(self):self.run.stop();self.env.stop()
    def compile(self,arguments,**kwargs):
        target=next(a[5:] for a in arguments if a.startswith('/out:'))
        Path(target).write_bytes(('compiled:'+target).encode())
        return SimpleNamespace(returncode=0,stdout=b'ok',stderr=b'')
    def build(self):
        return executor_build.compile_cached(self.runtime,self.install,self.folder,self.helper,self.base/'cache')
    def test_second_task_uses_exact_validated_cache_without_compiler(self):
        first=self.build();second=self.build()
        self.assertFalse(first['cache_hit']);self.assertTrue(second['cache_hit'])
        self.assertEqual(self.mock_run.call_count,2)
        self.assertEqual(first['artifact_sha256'],second['artifact_sha256'])
        self.assertFalse(second['native_session_shared'])
    def test_source_compiler_helper_and_interop_each_invalidate_key(self):
        old=self.build()['key']
        for path in (self.runtime/'executor/Program.cs',self.compiler,self.helper,
                     self.install/'api/redist'/executor_build.INTEROP[0]):
            path.write_bytes(path.read_bytes()+b'changed')
            result=self.build();self.assertFalse(result['cache_hit']);self.assertNotEqual(result['key'],old)
            old=result['key']
        self.assertEqual(self.mock_run.call_count,10)
    def test_corrupt_cached_executable_is_retained_and_rebuilt(self):
        first=self.build();(Path(first['entry'])/'SwExecutor.exe').write_bytes(b'tampered')
        second=self.build()
        self.assertFalse(second['cache_hit']);self.assertEqual(self.mock_run.call_count,4)
        self.assertEqual(len(list((self.base/'cache').glob('*-rejected-*'))),1)
        self.assertNotEqual(core.digest(self.runtime/'executor/bin/SwExecutor.exe'),core.digest(next((self.base/'cache').glob('*-rejected-*'))/'SwExecutor.exe'))
    def test_compile_error_never_publishes_or_copies_runnable_binary(self):
        self.mock_run.side_effect=None;self.mock_run.return_value=SimpleNamespace(returncode=1,stdout=b'bad',stderr=b'compiler rejected')
        with self.assertRaises(core.StopBatch) as error:self.build()
        self.assertEqual(error.exception.code,'COMPILATION_FAILED')
        self.assertFalse((self.runtime/'executor/bin/SwExecutor.exe').exists())
        self.assertFalse(list((self.base/'cache').glob('*/build.json')))
    def test_input_change_during_compile_is_not_cached(self):
        def changed(*args,**kw):
            result=self.compile(*args,**kw)
            self.helper.write_bytes(b'new source')
            (self.runtime/'test_host/AcceptanceControl.cs').write_bytes(b'changed compiled input')
            return result
        self.mock_run.side_effect=changed
        with self.assertRaises(core.StopBatch) as error:self.build()
        self.assertEqual(error.exception.code,'CANDIDATE_SOURCE_MISMATCH')
        self.assertFalse(list((self.base/'cache').glob('*/build.json')))
    def test_corrupt_runtime_copy_is_replaced_from_validated_cache(self):
        first=self.build();(self.runtime/'executor/bin/AcceptanceControl.exe').write_bytes(b'corrupt runtime')
        self.assertTrue(self.build()['cache_hit'])
        self.assertEqual(core.digest(self.runtime/'executor/bin/AcceptanceControl.exe'),first['artifact_sha256']['AcceptanceControl.exe'])
    def test_compiler_response_configuration_invalidation(self):
        first=self.build();self.compiler.with_suffix('.rsp').write_bytes(b'/reference:updated-framework.dll')
        second=self.build();self.assertFalse(second['cache_hit']);self.assertNotEqual(first['key'],second['key'])
    def test_default_cache_stays_beside_budget_checked_runtime(self):
        result=executor_build.compile_cached(self.runtime,self.install,self.folder,self.helper)
        self.assertEqual(Path(result['entry']).parent,self.runtime.parent/'executor-cache-v1')


def denied(number=5):
    error=PermissionError('fixture denied');error.winerror=number;return error


class SpawnTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'runs/startup-unit'/uuid.uuid4().hex[:10];self.folder.mkdir(parents=True)
    def test_failed_createprocess_retries_then_returns_one_started_process(self):
        process=SimpleNamespace(pid=123)
        with patch.object(startup_process.subprocess,'Popen',side_effect=[denied(),denied(32),process]) as spawn,patch.object(startup_process.time,'sleep') as sleep:
            self.assertIs(startup_process.spawn(['x'],self.folder,'connection-check'),process)
        self.assertEqual(spawn.call_count,3);self.assertEqual([c.args for c in sleep.call_args_list],[(1,),(2,)])
        proof=core.read(self.folder/'connection-check-spawn.json')
        self.assertFalse(proof['native_request_replayed']);self.assertEqual(sum(a['process_created'] for a in proof['attempts']),1)
    def test_exhausted_denial_keeps_native_code_and_exact_attempt_count(self):
        with patch.object(startup_process.subprocess,'Popen',side_effect=denied()) as spawn,patch.object(startup_process.time,'sleep') as sleep:
            with self.assertRaises(core.StopBatch) as error:startup_process.spawn(['x'],self.folder,'executor-self-test')
        self.assertEqual(error.exception.code,'EXECUTOR_SPAWN_DENIED');self.assertEqual(spawn.call_count,4)
        self.assertEqual([c.args for c in sleep.call_args_list],[(1,),(2,),(4,)])
        self.assertTrue(all(a['win32_error']==5 and a['process_created'] is False for a in error.exception.diagnostics['attempts']))
    def test_missing_executable_is_not_denial_and_not_retried(self):
        with patch.object(startup_process.subprocess,'Popen',side_effect=FileNotFoundError('missing')) as spawn:
            with self.assertRaises(core.StopBatch) as error:startup_process.spawn(['x'],self.folder,'executor-self-test')
        self.assertEqual(error.exception.code,'EXECUTOR_MISSING');self.assertEqual(spawn.call_count,1)
    def test_solidworks_failure_is_not_mislabelled_executor_failure(self):
        with patch.object(startup_process.subprocess,'Popen',side_effect=denied()),patch.object(startup_process.time,'sleep'):
            with self.assertRaises(core.StopBatch) as error:startup_process.spawn(['x'],self.folder,'solidworks')
        self.assertEqual(error.exception.code,'SOLIDWORKS_SPAWN_DENIED')
    def test_self_test_failure_precedes_any_CAD_launch(self):
        with patch('sw_mcp.conversation.startup_gate.require_idle'),patch.object(startup_process,'self_test',side_effect=core.StopBatch('EXECUTOR_SELF_TEST_FAILED')),patch.object(startup_process,'spawn') as spawn:
            with self.assertRaises(core.StopBatch):core.launch(self.folder,self.folder,self.folder)
        spawn.assert_not_called()
    def test_spawn_success_never_retries_a_started_request(self):
        process=Mock(pid=12)
        with patch.object(startup_process.subprocess,'Popen',return_value=process) as spawn,patch.object(startup_process.time,'sleep') as sleep:
            self.assertIs(startup_process.spawn(['x'],self.folder,'connection-check'),process)
        self.assertEqual(spawn.call_count,1);sleep.assert_not_called();process.wait.assert_not_called()
    def test_retains_started_CAD_before_receipt_write_can_fail(self):
        process=Mock(pid=123);retained=[]
        with patch.object(startup_process.subprocess,'Popen',return_value=process) as spawn,patch.object(core,'write',side_effect=OSError('receipt denied')):
            with self.assertRaises(OSError):startup_process.spawn(['x'],self.folder,'solidworks',on_created=retained.append)
        self.assertEqual(retained,[process]);self.assertEqual(spawn.call_count,1)


@unittest.skipUnless(os.name=='nt','Windows .NET compiler required')
class NativeEmptyExitGuardTests(unittest.TestCase):
    def test_actual_CSharp_guard_refuses_documents_and_wrong_PID(self):
        folder=ROOT/'runs/startup-unit'/uuid.uuid4().hex[:10];folder.mkdir(parents=True)
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        target=folder/'guard.exe'
        run=subprocess.run([str(compiler),'/nologo','/main:StartupEmptyControlTests',
            '/reference:System.Web.Extensions.dll','/out:'+str(target),str(ROOT/'tests/StartupEmptyControlTests.cs'),
            str(ROOT/'sw_mcp/conversation/session_control.cs')],capture_output=True)
        self.assertEqual(run.returncode,0,(run.stdout+run.stderr).decode(errors='replace'))
        actual=subprocess.run([str(target)],capture_output=True)
        self.assertEqual(actual.returncode,0,(actual.stdout+actual.stderr).decode(errors='replace'))
        self.assertIn(b'3 native empty-exit guard cases passed',actual.stdout)


class StartupCloseTests(unittest.TestCase):
    def setUp(self):
        self.base=ROOT/'runs/startup-unit'/uuid.uuid4().hex[:10];self.base.mkdir(parents=True)
        self.source=self.base/'case.SLDASM';self.source.write_bytes(b'not a CAD acceptance fixture')
    def session(self):return mate_worker.Session(self.base,self.base/uuid.uuid4().hex[:6],self.base/'rt')
    def induce_failure(self,session,process=None):
        def launch(*a,**kw):
            if process:kw['on_started'](process)
            raise core.StopBatch('EXECUTOR_SPAWN_DENIED','fixture',{'process_created':False,'purpose':'connection-check' if process else 'executor-self-test'})
        with patch.object(mate_worker,'stage'),patch.object(mate_worker,'compile_runtime'),patch.object(mate_worker.sw_install,'resolve',return_value={'resolved_directory':str(self.base)}),patch.object(core,'launch',side_effect=launch),patch.object(core,'runtime_path_budget'),patch('sw_mcp.conversation.startup_gate.require_idle'):
            with self.assertRaises(core.StopBatch) as error:mate_worker.Session.discover(session,self.source)
        return error.exception
    def test_no_CAD_failure_closes_without_COM_or_checkpoint(self):
        session=self.session();error=self.induce_failure(session)
        self.assertFalse(session.unknown);self.assertTrue(session.can_finish_startup())
        self.assertEqual(core.read(session.folder/'CAD会话状态.json')['status'],'startup_failed')
        failure=task_failure(error.code,str(error),error.diagnostics,task_id='a'*32,asynchronous=True)
        self.assertIs(failure['diagnostics']['cad_dispatched'],False)
        self.assertEqual(failure['restoration_status'],'not_required')
        self.assertEqual(failure['next_action']['tool'],'finish_mechanism_task')
        with patch.object(core,'close_owned') as close:receipt=session.finish_startup()
        close.assert_not_called();self.assertTrue(receipt['ended']);self.assertFalse(receipt['native_motion_passed'])
    def test_created_CAD_requires_empty_only_control_and_retained_handle(self):
        session=self.session();process=Mock(pid=876);self.induce_failure(session,process)
        self.assertTrue(session.unknown)
        with patch.object(core,'close_owned') as close:session.finish_startup()
        close.assert_called_once_with(None,process,session.runtime,session.folder,empty_only=True)
    def test_refused_or_pending_cleanup_cannot_be_retried(self):
        session=self.session();self.induce_failure(session,Mock(pid=876))
        with patch.object(core,'close_owned',side_effect=core.StopBatch('CONTROL_FAILED')) as close:
            with self.assertRaises(core.StopBatch):session.finish_startup()
            with self.assertRaises(core.StopBatch):session.finish_startup()
        self.assertEqual(close.call_count,1);self.assertTrue(session.unknown);self.assertFalse(session.ended)
    def test_null_model_or_dispatch_fields_without_phase_proof_never_grant_close(self):
        session=self.session();session.unknown=True;session.proc=Mock(pid=876)
        self.assertFalse(session.can_finish_startup())
        with self.assertRaises(core.StopBatch):session.finish_startup()
        failure=task_failure('EXECUTOR_SPAWN_DENIED','fixture',{'cad_dispatched':None},asynchronous=True)
        self.assertIsNone(failure['diagnostics']['cad_dispatched']);self.assertEqual(failure['restoration_status'],'unknown')
    def test_pending_offline_probe_is_not_mistaken_for_no_process_started(self):
        session=self.session()
        with patch.object(mate_worker,'stage'),patch.object(mate_worker,'compile_runtime'),patch.object(core,'runtime_path_budget'),patch.object(mate_worker.sw_install,'resolve',return_value={'resolved_directory':str(self.base)}),patch('sw_mcp.conversation.startup_gate.require_idle'),patch.object(core,'launch',side_effect=core.StopBatch('EXECUTOR_SELF_TEST_PENDING')):
            with self.assertRaises(core.StopBatch):session.discover(self.source)
        self.assertTrue(session.unknown);self.assertFalse(session.can_finish_startup())
        with self.assertRaises(core.StopBatch):session.close()
    def test_import_dispatched_even_without_model_id_blocks_startup_close(self):
        session=self.session();self.induce_failure(session);session.import_dispatched=True
        self.assertFalse(session.can_finish_startup())
        with self.assertRaises(core.StopBatch):session.finish_startup()
    def test_same_engine_failed_task_finishes_and_accepts_next_task(self):
        outer=self
        class FailureSession(mate_worker.Session):
            def __init__(self,project,folder,runtime_base,**kw):super().__init__(project,folder,runtime_base)
            def discover(self,path):raise outer.induce_failure(self)
        engine=TaskEngine(self.base,self.base/'work',self.base/'rt',FailureSession)
        def wait(tid):
            for _ in range(1000):
                state=engine.get(tid)
                if not state['busy']:return state
                time.sleep(.005)
            self.fail('task did not settle')
        try:
            with patch('sw_mcp.conversation.startup_gate.require_idle'):
                first=engine.prepare(str(self.source))['task_id'];state=wait(first)
                self.assertEqual(state['phase'],'failed');self.assertEqual(state['error']['code'],'EXECUTOR_SPAWN_DENIED')
                owner=engine.server_instance_id;engine.finish(first);closed=wait(first)
                self.assertTrue(closed['closed']);self.assertEqual(closed['task_outcome'],'failed_before_import')
                self.assertEqual(closed['previous_failure']['code'],'EXECUTOR_SPAWN_DENIED')
                self.assertEqual(closed['finish']['restoration']['restoration_status'],'not_required')
                self.assertTrue(closed['finish']['next_round_allowed'])
                second=engine.prepare(str(self.source))['task_id'];wait(second)
                self.assertNotEqual(first,second);self.assertEqual(engine.server_instance_id,owner)
                engine.finish(second);self.assertTrue(wait(second)['closed'])
        finally:engine.shutdown()


if __name__=='__main__':unittest.main()
