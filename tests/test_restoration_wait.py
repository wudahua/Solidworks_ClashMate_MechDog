"""Real subprocess transport with simulated CAD; no SolidWorks is launched."""
import json,subprocess,sys,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge,CadError
from transport_cleanup import drain_bridge,remove_test_root


class RestorationWaitTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'runs/restoration-wait-tests'/uuid.uuid4().hex[:8]
        (self.root/'executor/bin').mkdir(parents=True)
        (self.root/'executor/bin/SwExecutor.exe').touch()
        self.bridge=Bridge(self.root,timeout=.25,motion_scan_timeout=.25)
        self.bridge.RESTORATION_WAIT_S=.7
        self.addCleanup(self.cleanup)
        helper=self.root/'helper.py'
        helper.write_text('''import json,sys,time
from pathlib import Path
root=Path(__file__).parent
print(json.dumps({'ready':True,'protocol_version':1,'process_id':22}),flush=True)
for line in sys.stdin:
 r=json.loads(line);p=r['params'];c=json.loads((root/'config.json').read_text())
 with (root/'dispatches.jsonl').open('a') as stream:stream.write(json.dumps(r)+'\\n')
 progress=root/'runs/progress';progress.mkdir(parents=True,exist_ok=True)
 job=p['job_id'];stamp=time.time()-c.get('age_s',0)
 (progress/(job+'.json')).write_text(json.dumps({'job_id':job,'run_id':c.get('progress_run_id',job),'stage':c.get('stage','restore_solve_scope'),'updated_at':stamp}))
 if c.get('tamper_mapping'):
  (root/'runs/jobs'/(job+'.request.json')).write_text(json.dumps({'job_id':job,'request_id':'0'*32,'operation':r['op']}))
 if c.get('hold'):
  end=time.monotonic()+15
  while not (root/'release').exists():
   if time.monotonic()>end:raise RuntimeError('test gate expired')
   time.sleep(.01)
 else:time.sleep(.4)
 if c.get('native_failure'):answer={'id':r['id'],'ok':False,'error':{'code':'SOLVER_FAILED','message':'native failure retained','restoration_status':'restored'}}
 else:answer={'id':r['id'],'ok':True,'result':{'result_validity':'verified','restoration_status':'restored'}}
 print(json.dumps(answer),flush=True)
''',encoding='utf-8')
        real=subprocess.Popen
        self.patcher=patch('sw_mcp.bridge.subprocess.Popen',side_effect=lambda command,**kw:real([sys.executable,str(helper)],**kw))
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def cleanup(self):
        (self.root/'release').touch()
        drain_bridge(self.bridge)
        remove_test_root(self.root,ROOT/'runs/restoration-wait-tests')

    def call(self,config,operation='run_user_study'):
        (self.root/'config.json').write_text(json.dumps(config),encoding='utf-8')
        return self.bridge.request(operation,model_id='user_'+'b'*32,run_id='a'*32,job_id='a'*32)

    def test_restoration_wait_receives_same_original_response_once(self):
        result=self.call({})
        self.assertEqual(result['result_validity'],'verified')
        wait=result['transport_restoration_wait']
        self.assertEqual(wait['status'],'original_terminal_response_received')
        self.assertEqual(wait['additional_native_dispatches'],0)
        self.assertFalse(wait['automatic_recalculate'])
        self.assertEqual(len((self.root/'dispatches.jsonl').read_text().splitlines()),1)
        original=self.bridge.get_request_result(wait['request_id'])
        self.assertTrue(original['response']['ok'])
        self.assertNotIn('transport_restoration_wait',original['response']['result'])
        self.assertEqual(self.bridge.cad_operation_state,'available')

    def test_expired_restoration_wait_keeps_quarantine_and_one_dispatch(self):
        with self.assertRaises(CadError) as caught:self.call({'hold':True})
        error=caught.exception
        self.assertEqual(error.code,'CAD_TIMEOUT')
        self.assertAlmostEqual(error.diagnostics['wait_budget_s'],.95)
        self.assertEqual(error.diagnostics['last_native_progress']['stage'],'restore_solve_scope')
        self.assertEqual(error.diagnostics['restoration_wait']['status'],'restoration_wait_expired_original_request_still_unconfirmed')
        self.assertEqual(self.bridge.cad_operation_state,'unknown_after_timeout')
        with self.assertRaises(CadError) as blocked:self.bridge.request('next')
        self.assertEqual(blocked.exception.code,'CAD_BUSY_AFTER_TIMEOUT')
        self.assertEqual(len((self.root/'dispatches.jsonl').read_text().splitlines()),1)
        (self.root/'release').touch()
        end=time.monotonic()+5
        while self.bridge.cad_operation_state!='available' and time.monotonic()<end:time.sleep(.01)
        self.assertEqual(self.bridge.cad_operation_state,'available')
        self.assertEqual(error.code,'CAD_TIMEOUT')  # no retroactive success

    def test_native_failure_during_restoration_wait_is_not_success(self):
        with self.assertRaises(CadError) as caught:self.call({'native_failure':True})
        self.assertEqual(caught.exception.code,'SOLVER_FAILED')
        self.assertEqual(caught.exception.restoration_status,'restored')
        audit=json.loads(next((self.root/'runs/request-waits').glob('*.json')).read_text())
        self.assertEqual(audit['status'],'original_terminal_response_received')

    def test_unbound_stale_or_calculating_progress_cannot_extend_wait(self):
        for config in ({'stage':'native_calculate'},{'progress_run_id':'c'*32},{'age_s':10},{'tamper_mapping':True}):
            with self.subTest(config=config):
                with self.assertRaises(CadError) as caught:self.call(config)
                self.assertEqual(caught.exception.code,'CAD_TIMEOUT')
                self.assertIsNone(caught.exception.diagnostics['restoration_wait'])
                self.assertEqual(caught.exception.diagnostics['wait_budget_s'],.25)
                self.assertFalse((self.root/'runs/request-waits').exists())
                end=time.monotonic()+5
                while self.bridge.cad_operation_state!='available' and time.monotonic()<end:time.sleep(.01)
                self.assertEqual(self.bridge.cad_operation_state,'available')

    def test_default_budget_stays_600_plus_at_most_60_for_restoration(self):
        self.assertEqual(Bridge.RESTORATION_WAIT_S,60)
        bridge=Bridge(self.root,timeout=180,motion_scan_timeout=600)
        self.assertEqual(bridge._wait_budget('run_user_study',{}),600)
        self.assertEqual(bridge._wait_budget('inspect_model',{}),180)

    def test_other_operations_do_not_gain_restoration_wait(self):
        with self.assertRaises(CadError) as caught:self.call({},operation='verify_motion_preservation')
        self.assertEqual(caught.exception.code,'CAD_TIMEOUT')
        self.assertIsNone(caught.exception.diagnostics['restoration_wait'])
        self.assertEqual(caught.exception.diagnostics['wait_budget_s'],.25)

    def test_audit_failure_cannot_gain_extra_wait_or_unlock_native_request(self):
        with patch.object(self.bridge,'_record_restoration_wait',side_effect=PermissionError('simulated disk refusal')):
            with self.assertRaises(CadError) as caught:self.call({'hold':True})
        error=caught.exception
        self.assertEqual(error.code,'CAD_TIMEOUT')
        self.assertEqual(error.diagnostics['wait_budget_s'],.25)
        self.assertEqual(error.diagnostics['restoration_wait']['status'],'restoration_wait_not_started_audit_unavailable')
        self.assertEqual(self.bridge.cad_operation_state,'unknown_after_timeout')
        self.assertEqual(len((self.root/'dispatches.jsonl').read_text().splitlines()),1)


if __name__=='__main__':unittest.main()
