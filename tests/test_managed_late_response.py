"""Real subprocess transport, simulated CAD handles; no SolidWorks activation."""
import json,subprocess,sys,time,threading,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from sw_mcp.bridge import Bridge,CadError
from sw_mcp.conversation import core,managed_wait
from sw_mcp.conversation.task_engine import ConversationSession
from transport_cleanup import drain_bridge,remove_test_root

ROOT=Path(__file__).resolve().parents[1]


class ManagedLateTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'runs/managed-wait-tests'/uuid.uuid4().hex[:8];self.folder.mkdir(parents=True)
        self.addCleanup(remove_test_root,self.folder,ROOT/'runs/managed-wait-tests')
        self.cad=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read()'],stdin=subprocess.PIPE)
        self.addCleanup(self.close_cad)
        (self.folder/'executor/bin').mkdir(parents=True);(self.folder/'executor/bin/SwExecutor.exe').touch()
        helper=self.folder/'helper.py'
        helper.write_text('''import json,os,sys,time
from pathlib import Path
root=Path(__file__).parent
print(json.dumps({'ready':True,'protocol_version':1,'process_id':int(sys.argv[1])}),flush=True)
for line in sys.stdin:
 r=json.loads(line);config=json.loads((root/'config.json').read_text())
 with (root/'dispatches.jsonl').open('a') as f:f.write(json.dumps(r)+'\\n')
 while not (root/'release').exists():time.sleep(.01)
 if config.get('failure'):v={'id':r['id'],'ok':False,'error':{'code':'SOLVER_FAILED','message':'native failure','restoration_status':'restored'}}
 else:v={'id':r['id'],'ok':True,'result':{'run_id':r['params'].get('run_id'),'restoration_status':'restored','result_validity':'verified'}}
 print(json.dumps(v),flush=True)
''',encoding='utf8')
        real=subprocess.Popen
        self.patcher=patch('sw_mcp.bridge.subprocess.Popen',side_effect=lambda args,**kw:real([sys.executable,str(helper),str(self.cad.pid)],**kw))
        self.patcher.start();self.addCleanup(self.patcher.stop)
        self.bridge=Bridge(self.folder,timeout=.08,motion_scan_timeout=.08)
        self.addCleanup(self.cleanup_bridge)
        self.s=ConversationSession.__new__(ConversationSession)
        self.s.folder=self.folder/'session';self.s.folder.mkdir();self.s.runtime=self.folder
        self.s.bridge=self.bridge;self.s.proc=self.cad;self.s.unknown=False;self.s.serial=0
        self.s.model='user_'+'b'*32;self.s.checkpoint='c'*32
        self.s.persist_ownership=lambda *args:None
        self.observations=[];self.s.on_progress=self.observations.append
        (self.folder/'config.json').write_text('{}')
        self.limits=patch.multiple(managed_wait,MAX_CALL_WAIT_S=2,POLL_S=.01);self.limits.start();self.addCleanup(self.limits.stop)

    def close_cad(self):
        if self.cad.stdin and not self.cad.stdin.closed:self.cad.stdin.close()
        self.cad.wait(timeout=10)

    def cleanup_bridge(self):
        (self.folder/'release').touch();drain_bridge(self.bridge)

    def call(self):return self.s.call('run_user_study',model_id=self.s.model,run_id='a'*32,duration_s=1,output_fps=30)

    def start(self):
        result={}
        def run():
            try:result['value']=self.call()
            except Exception as e:result['error']=e
        thread=threading.Thread(target=run);thread.start();return thread,result

    def pending(self):
        end=time.monotonic()+5
        while not getattr(self.s,'pending_native_response',None) and time.monotonic()<end:time.sleep(.01)
        self.assertIsNotNone(getattr(self.s,'pending_native_response',None))

    def test_wait_keeps_same_stack_and_consumes_only_original_response(self):
        thread,result=self.start();self.pending();self.assertTrue(thread.is_alive())
        self.assertTrue(self.s.unknown)
        (self.folder/'release').touch();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertNotIn('error',result)
        self.assertEqual(result['value']['result_validity'],'verified')
        self.assertFalse(self.s.unknown);self.assertIsNone(self.s.pending_native_response)
        self.assertEqual(len((self.folder/'dispatches.jsonl').read_text().splitlines()),1)
        self.assertFalse(self.s.late_response_reconciled['whole_task_verified'])
        self.assertTrue(list(self.s.folder.glob('等待超时-*.json')))

    def test_native_failure_is_retained_and_known_restoration_allows_finish(self):
        (self.folder/'config.json').write_text('{"failure":true}')
        thread,result=self.start();self.pending();(self.folder/'release').touch();thread.join(5)
        self.assertEqual(result['error'].code,'SOLVER_FAILED');self.assertFalse(self.s.unknown)
        self.assertFalse(self.s.late_response_reconciled['response_ok'])

    def test_hard_wait_expiry_late_arrival_can_be_read_without_dispatch(self):
        with patch.object(managed_wait,'MAX_CALL_WAIT_S',.15):
            with self.assertRaises(CadError) as error:self.call()
        self.assertEqual(error.exception.code,'CAD_TIMEOUT');self.assertTrue(self.s.unknown)
        self.assertIsNotNone(self.s.pending_native_response)
        with self.assertRaises(core.StopBatch):self.s.require_live_idle()
        (self.folder/'release').touch();end=time.monotonic()+5
        while self.bridge.cad_operation_state!='available' and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(self.s.require_live_idle()['journal_idle'])
        self.assertFalse(self.s.unknown);self.assertEqual(len((self.folder/'dispatches.jsonl').read_text().splitlines()),1)

    def test_response_owner_tamper_never_clears_unknown(self):
        with patch.object(managed_wait,'MAX_CALL_WAIT_S',.15):
            with self.assertRaises(CadError):self.call()
        (self.folder/'release').touch();end=time.monotonic()+5
        while self.bridge.cad_operation_state!='available' and time.monotonic()<end:time.sleep(.01)
        pending=self.s.pending_native_response;path=self.folder/'runs/requests'/(pending['request_id']+'.json')
        data=core.read(path);data['owner_id']='different_owner';core.write(path,data)
        with self.assertRaises(core.StopBatch) as error:self.s.require_live_idle()
        self.assertEqual(error.exception.code,'REQUEST_RESULT_INVALID');self.assertTrue(self.s.unknown)

    def test_pending_heartbeat_remains_observable_without_inventing_progress(self):
        from sw_mcp.conversation.task_progress import watch_call
        self.s.pending_native_response={'request_id':'d'*32,'operation':'run_user_study','call_wait_budget_s':3600,'same_original_request':True,'additional_native_dispatches':0}
        with watch_call(self.s,'run_user_study',{'run_id':'a'*32,'job_id':'a'*32},interval=.02):time.sleep(.08)
        self.assertGreaterEqual(len(self.observations),3)
        self.assertGreater(self.observations[-1]['operation_elapsed_s'],self.observations[0]['operation_elapsed_s'])
        self.assertTrue(self.observations[-1]['original_request_wait']['same_original_request'])
        self.assertFalse(self.observations[-1]['heartbeat_proves_native_progress'])


if __name__=='__main__':unittest.main()
