"""Late write outcomes, model binding and async opt-in semantics; no CAD."""
import asyncio, json, shutil, subprocess, sys, time, unittest, uuid
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge,CadError
from sw_mcp.jobs import Jobs
from transport_cleanup import drain_bridge, remove_test_root


class ClockTransportTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'runs/clock-tests'/uuid.uuid4().hex[:8];self.root.mkdir(parents=True)
        self.bridge=Bridge(self.root,timeout=5,motion_scan_timeout=.5)
        self.gate=self.root/"release"
        self.addCleanup(self.cleanup)
        (self.root/'executor/bin').mkdir(parents=True);(self.root/'executor/bin/SwExecutor.exe').touch()
        helper=self.root/'helper.py'
        helper.write_text('''import json,sys,time
from pathlib import Path
gate=Path(__file__).with_name('release')
print(json.dumps({'ready':True,'protocol_version':1,'process_id':22}),flush=True)
for line in sys.stdin:
 r=json.loads(line);p=r['params']
 if r['op']=='preview_mate': answer={'id':r['id'],'ok':True,'result':{'plan_id':'b'*32,'model_id':p['model_id']}}
 elif r['op']=='apply_mate':
  end=time.monotonic()+20
  while not gate.exists():
   if time.monotonic()>end: raise RuntimeError("test gate expired")
   time.sleep(.01)
  if p.get('outcome')=='unknown': answer={'id':r['id'],'ok':False,'error':{'code':'MATE_ROLLBACK_FAILED','restoration_status':'unknown'}}
  elif p.get('outcome')=='rolledback': answer={'id':r['id'],'ok':False,'error':{'code':'MATE_APPLY_ROLLED_BACK','restoration_status':'restored'}}
  else: answer={'id':r['id'],'ok':True,'result':{'model_id':p['model_id'],'plan_id':p['plan_id'],'checkpoint_id':'c'*32,'native_parameters':{'verified':True},'restoration_status':'restored'}}
 else: answer={'id':r['id'],'ok':True,'result':{'restoration_status':'restored'}}
 print(json.dumps(answer),flush=True)
''',encoding='utf-8')
        real=subprocess.Popen
        self.patcher=patch('sw_mcp.bridge.subprocess.Popen',side_effect=lambda command,**kw:real([sys.executable,str(helper)],**kw))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
    def cleanup(self):
        self.gate.touch()
        drain_bridge(self.bridge)
        remove_test_root(self.root,ROOT/'runs/clock-tests')
    def plan(self):return self.bridge.request('preview_mate',model_id='user_'+'a'*32)['plan_id']
    def await_reply(self):
        self.gate.touch()
        end=time.monotonic()+10
        while self.bridge.cad_operation_state=='unknown_after_timeout' and time.monotonic()<end:time.sleep(.01)
        self.assertEqual(self.bridge.cad_operation_state,'available')
    def test_derived_journal_fields_are_written_consistently(self):
        self.bridge._journal({'status':'idle','recovery_required':True,'cad_request_policy':'recovery_only'})
        raw=json.loads(self.bridge._journal_path.read_text())
        self.assertFalse(raw['recovery_required']);self.assertNotIn('cad_request_policy',raw)
        self.bridge._journal_path.write_text(json.dumps({'status':'idle','recovery_required':True}))
        before=self.bridge._journal_path.read_bytes();state=self.bridge.recovery_state()
        self.assertFalse(state['journal_derived_fields_consistent']);self.assertEqual(self.bridge._journal_path.read_bytes(),before)
    def test_legacy_dispatch_state_is_diagnosed_without_rewriting(self):
        self.bridge._journal_path.parent.mkdir(parents=True,exist_ok=True)
        self.bridge._journal_path.write_text(json.dumps({'status':'idle','dispatch_state':'dispatching','recovery_required':False}))
        before=self.bridge._journal_path.read_bytes();state=self.bridge.recovery_state()
        self.assertFalse(state['dispatch_field_consistent']);self.assertFalse(state['journal_derived_fields_consistent'])
        self.assertEqual(state['observed_dispatch_state'],'dispatching');self.assertEqual(state['current_request_state'],'completed')
        self.assertEqual(self.bridge._journal_path.read_bytes(),before)
        self.bridge._journal({'status':'unknown','dispatch_state':'dispatching'})
        self.assertTrue(self.bridge.recovery_state()['recovery_required'])
        self.assertEqual(self.bridge.recovery_state()['dispatch_state'],'unconfirmed')
    def test_late_success_keeps_timeout_but_exposes_terminal_result_after_restart(self):
        plan=self.plan();jobs=Jobs(self.bridge,self.root)
        submitted=jobs.submit('apply_mate',{'plan_id':plan,'confirmed':True});jobs._pool.shutdown(wait=True)
        initial=jobs.get(submitted['job_id']);self.assertEqual(initial['status'],'timed_out')
        self.assertEqual(initial['error']['diagnostics']['model_id'],'user_'+'a'*32)
        with self.assertRaises(CadError) as e:self.bridge.request('next')
        self.assertEqual(e.exception.code,'CAD_BUSY_AFTER_TIMEOUT');self.await_reply()
        restarted=Jobs(Bridge(self.root),self.root)
        try:
            final=restarted.get(submitted['job_id']);self.assertEqual(final['status'],'timed_out')
            self.assertTrue(final['late_response']['response']['result']['native_parameters']['verified'])
            self.assertTrue(final['historical_job_read_only']);self.assertFalse(final['automatically_resumed'])
            self.assertEqual(final['late_execution_status'],'completed')
        finally:restarted._pool.shutdown()
        self.assertFalse(json.loads(self.bridge._journal_path.read_text())['recovery_required'])
    def test_late_rollback_records_failure_and_lifts_quarantine(self):
        plan=self.plan()
        with self.assertRaises(CadError) as e:self.bridge.request('apply_mate',plan_id=plan,confirmed=True,outcome='rolledback')
        rid=e.exception.diagnostics['request_id'];self.await_reply()
        self.assertEqual(self.bridge.get_request_result(rid)['response']['error']['code'],'MATE_APPLY_ROLLED_BACK')
        self.assertFalse(self.bridge.recovery_state()['recovery_required'])
    def test_late_unknown_still_blocks_cad_and_wrong_model_restore(self):
        plan=self.plan()
        with self.assertRaises(CadError) as e:self.bridge.request('apply_mate',plan_id=plan,confirmed=True,outcome='unknown')
        rid=e.exception.diagnostics['request_id'];self.await_reply()
        self.assertEqual(self.bridge.get_request_result(rid)['response']['error']['restoration_status'],'unknown')
        with self.assertRaises(CadError) as e:self.bridge.request('next')
        self.assertEqual(e.exception.code,'RECOVERY_REQUIRED')
        with self.assertRaises(CadError) as e:self.bridge.request('restore_model_checkpoint',model_id='user_'+'d'*32)
        self.assertEqual(e.exception.code,'RECOVERY_MODEL_MISMATCH')
    def test_unbound_or_wrong_model_plan_never_dispatches(self):
        self.bridge._start();before=self.bridge.recovery_state()
        with self.assertRaises(CadError):self.bridge.request('apply_mate',plan_id='b'*32,confirmed=True)
        self.assertEqual(before,self.bridge.recovery_state());self.assertFalse(self.bridge._pending)
        plan=self.plan()
        with self.assertRaises(CadError):self.bridge.request('apply_mate',plan_id=plan,model_id='user_'+'c'*32,confirmed=True)
    def test_terminal_response_corruption_is_rejected(self):
        self.bridge.request('next');rid=self.bridge.recovery_state()['request_id']
        path=self.root/'runs/requests'/(rid+'.json');record=json.loads(path.read_text());record['response']['ok']=False
        path.write_text(json.dumps(record))
        with self.assertRaises(CadError) as e:self.bridge.get_request_result(rid)
        self.assertEqual(e.exception.code,'REQUEST_RESULT_INVALID')
    def test_write_operations_use_extended_budget(self):
        for name in ['apply_mate','create_motion_study','convert_motion_study','reset_study_time','create_model_checkpoint']:
            self.assertIn(name,Bridge.LONG_OPERATIONS)


class ClockPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_history_summary_never_calls_cad(self):
        import motion_server as server
        with patch.object(server.artifacts,'summary',return_value={'historical_data':True,'current_model_validity':'not_checked_offline'}) as read, patch.object(server,'call',side_effect=AssertionError('CAD must not be called')):
            await server.get_motion_summary('a'*32,allow_unverified_history=True)
            read.assert_called_once_with('a'*32)
    async def test_default_async_reset_does_not_authorize_calculation(self):
        import motion_server as server
        with patch.object(server.jobs,'submit',return_value={'job_id':'a'*32}) as submit:
            await server.reset_study_time('user_'+'a'*32,'study')
            self.assertIs(submit.call_args.args[1]['allow_recalculate'],False)
            await server.reset_study_time('user_'+'a'*32,'study',allow_recalculate=True)
            self.assertIs(submit.call_args.args[1]['allow_recalculate'],True)
    async def test_apply_requires_confirmation_before_job_submission(self):
        import motion_server as server
        with patch.object(server.jobs,'submit') as submit:
            with self.assertRaises(Exception):await server.apply_mate('a'*32,False)
            submit.assert_not_called()
    async def test_creation_budget_validation_precedes_enqueue(self):
        import motion_server as server
        with patch.object(server.jobs,'submit') as submit:
            with self.assertRaises(Exception):await server.create_motion_study('model','study','component','entity','rotary',10,duration_s=31)
            submit.assert_not_called()


if __name__=='__main__':unittest.main()
