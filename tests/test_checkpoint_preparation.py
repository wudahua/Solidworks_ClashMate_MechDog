"""Protocol journals preserve verified preparation failures and uncertain cleanup."""
import csv,hashlib,json,sys,uuid,unittest
from pathlib import Path
from io import StringIO
from types import SimpleNamespace
from concurrent.futures import Future
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge
from sw_mcp.artifacts import Artifacts
from transport_cleanup import remove_test_root
class PreparationProtocolTests(unittest.TestCase):
    def setUp(self):
        self.base=ROOT/'runs/prep-unit';self.root=self.base/uuid.uuid4().hex[:8];self.root.mkdir(parents=True);self.addCleanup(remove_test_root,self.root,self.base)
    def response(self,restoration):
        bridge=Bridge(self.root);identifier='b'*32
        bridge._journal({'status':'active','request_id':identifier,'owner_id':bridge._owner_id,'operation':'apply_mate','model_id':'user_'+'a'*32})
        payload={'id':identifier,'ok':False,'error':{'code':'CHECKPOINT_PROBE_FAILED' if restoration=='restored' else 'MATE_PREPARATION_RECOVERY_REQUIRED','message':'controlled response','restoration_status':restoration,'diagnostics':{'mate_created':False,'write_committed':False,'rollback_verified':restoration=='restored'}}}
        bridge._process=SimpleNamespace(pid=2147480000,poll=lambda:0,stdout=StringIO(json.dumps(payload)+'\n'));bridge._pending[identifier]=Future();bridge._read();return bridge,identifier
    def test_verified_no_write_failure_returns_idle_without_repeating_request(self):
        bridge,identifier=self.response('restored');state=bridge.recovery_state();self.assertEqual(state['status'],'idle');self.assertFalse(state['recovery_required']);record=bridge.get_request_result(identifier);self.assertFalse(record['response']['ok']);self.assertFalse(record['response']['error']['diagnostics']['mate_created'])
    def test_unverified_context_or_cleanup_keeps_recovery_required(self):
        bridge,identifier=self.response('unknown');state=bridge.recovery_state();self.assertEqual(state['status'],'unknown');self.assertTrue(state['recovery_required']);self.assertEqual(state['cad_request_policy'],'recovery_only');self.assertFalse(bridge.get_request_result(identifier)['response']['error']['diagnostics']['rollback_verified'])
    def test_history_guidance_survives_offline_summary_without_revalidating_cad(self):
        identifier='c'*32;folder=self.root/'runs'/identifier;folder.mkdir(parents=True);path=folder/'component-poses.csv'
        with path.open('w',newline='',encoding='utf-8') as stream:
            writer=csv.writer(stream);writer.writerow(['frame','time_s','component_id','instance','x_m','y_m','z_m','r00','r01','r02','r10','r11','r12','r20','r21','r22']);writer.writerow([0,0,'component_a','moving',0,0,0,1,0,0,0,1,0,0,0,1]);writer.writerow([1,1,'component_a','moving',.01,0,0,1,0,0,0,1,0,0,0,1])
        (folder/'solve.json').write_text(json.dumps({'run_id':identifier,'poses_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'history_usage':{'later_write_or_checkpoint_restore_may_invalidate_current_binding':True},'restoration_status':'unknown'}),encoding='utf-8')
        result=Artifacts(self.root).summary(identifier);self.assertTrue(result['history_usage']['later_write_or_checkpoint_restore_may_invalidate_current_binding']);self.assertEqual(result['current_model_validity'],'not_checked_offline')
if __name__=='__main__':unittest.main()
