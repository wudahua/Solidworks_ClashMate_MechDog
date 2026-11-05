"""Actual formal tool routing; SDK and native request are controlled stand-ins."""
import uuid,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from sw_mcp.conversation.formal_engine import FormalEngine,_ManagedRecoveryBridge
from sw_mcp.conversation import core
from transport_cleanup import remove_test_root

ROOT=Path(__file__).resolve().parents[1]
class Result:
    def __init__(self,value,okay=True):self.structured_content={'ok':okay,**({'result':value} if okay else {'error':value})};self.is_error=not okay
    def model_dump(self,**unused):return {'structured_content':self.structured_content,'is_error':self.is_error}

class ManagedRecoveryRouteTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'runs/recovery-route-tests';self.folder=base/uuid.uuid4().hex[:8];self.folder.mkdir(parents=True)
        self.addCleanup(remove_test_root,self.folder,base)
        self.restored={'model_id':'user_model','checkpoint_id':'checkpoint','restoration_status':'restored','source_files_unchanged':True,'maximum_transform_delta':0}
        native=SimpleNamespace(_process=None,request=Mock(side_effect=AssertionError('SDK bypassed original-session managed wait')),recovery_state=Mock(return_value={'status':'idle'}))
        self.session=SimpleNamespace(bridge=native,call=Mock(return_value=self.restored),admit_owned_recovery=Mock(),accept_owned_recovery=Mock())
        self.engine=FormalEngine.__new__(FormalEngine);self.engine.managed_upgrade_guard=False
        self.engine.tasks=SimpleNamespace(active='task',prior_unfinished=[],sessions={'task':self.session},tasks={'task':{'busy':False}},work=self.folder,mark_recovered=Mock())
        self.original_bridge=SimpleNamespace(_process=None)
        product=SimpleNamespace(bridge=self.original_bridge,artifacts=object(),jobs=SimpleNamespace(_jobs={}))
        async def sdk(name,arguments):
            try:
                value=(product.bridge.request(name,**arguments) if name=='restore_model_checkpoint' else product.bridge.recovery_state())
                return Result(value)
            except core.StopBatch as failure:return Result({'code':failure.code},False)
        product.mcp=SimpleNamespace(call_tool=sdk);self.engine.product=product
        self.arguments={'model_id':'user_model','checkpoint_id':'checkpoint'}
    def test_restore_uses_existing_session_wait_and_marks_recovered_only_after_success(self):
        value=self.engine.tool('restore_model_checkpoint',self.arguments)
        self.assertTrue(value['structured_content']['ok']);self.session.call.assert_called_once_with('restore_model_checkpoint',**self.arguments)
        self.session.bridge.request.assert_not_called();self.session.accept_owned_recovery.assert_called_once_with(self.restored)
        self.engine.tasks.mark_recovered.assert_called_once_with('task',self.restored);self.assertIs(self.engine.product.bridge,self.original_bridge)
    def test_timeout_does_not_mark_recovered_or_dispatch_again(self):
        self.session.call.side_effect=core.StopBatch('CAD_TIMEOUT')
        value=self.engine.tool('restore_model_checkpoint',self.arguments)
        self.assertFalse(value['structured_content']['ok']);self.assertEqual(value['structured_content']['error']['code'],'CAD_TIMEOUT')
        self.assertEqual(self.session.call.call_count,1);self.session.bridge.request.assert_not_called()
        self.session.accept_owned_recovery.assert_not_called();self.engine.tasks.mark_recovered.assert_not_called()
        self.assertIs(self.engine.product.bridge,self.original_bridge)
    def test_reading_recovery_state_does_not_invoke_session_restore(self):
        value=self.engine.tool('get_recovery_state',{})
        self.assertEqual(value['structured_content']['result']['status'],'idle');self.session.call.assert_not_called()
        self.session.accept_owned_recovery.assert_not_called();self.assertIs(self.engine.product.bridge,self.original_bridge)
    def test_recovery_scope_refusal_precedes_any_dispatch(self):
        self.session.admit_owned_recovery.side_effect=core.StopBatch('MANAGED_RECOVERY_SCOPE_MISMATCH')
        with self.assertRaises(core.StopBatch):self.engine.tool('restore_model_checkpoint',self.arguments)
        self.session.call.assert_not_called();self.session.bridge.request.assert_not_called()
        self.assertIs(self.engine.product.bridge,self.original_bridge)
    def test_adapter_does_not_intercept_other_native_operations(self):
        self.session.bridge.request=Mock(return_value={'count':1})
        proxy=_ManagedRecoveryBridge(self.session)
        self.assertEqual(proxy.request('inspect_model',model_id='m'),{'count':1});self.session.call.assert_not_called()
        self.session.bridge.request.assert_called_once_with('inspect_model',model_id='m')
if __name__=='__main__':unittest.main()
