"""Compile actual native deferral and batch controls; no SolidWorks activation."""
import json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class RestorationGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.exe=pathlib.Path(cls.temp.name)/'gate.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        sources=('executor/CadFault.cs','executor/ComponentInventoryRead.cs','executor/NativeCommandBatch.cs','executor/NativeRestorationGate.cs','tests/NativeRestorationGateTests.cs')
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe),*[str(ROOT/n) for n in sources]],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError((r.stdout+r.stderr).decode(errors='replace'))
    def read(self,mode):
        r=subprocess.run([str(self.exe),mode],capture_output=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def refused(self,mode):
        v=self.read(mode);self.assertTrue(v['deferred']);self.assertFalse(v['restore_callback_ran']);self.assertEqual(v['calls'],0)
    def test_rpc_failure_performs_no_snapshot_restore_callback(self):self.refused('com')
    def test_nested_communication_failure_is_not_hidden_by_wrapper(self):self.refused('nested_com')
    def test_component_inventory_failure_defers_restoration(self):self.refused('inventory')
    def test_command_flag_failure_and_context_change_are_unsafe(self):
        for mode in ('command','context'):
            with self.subTest(mode=mode):self.refused(mode)
    def test_known_rebuild_failure_retains_normal_restore(self):
        v=self.read('normal');self.assertFalse(v['deferred']);self.assertTrue(v['restore_callback_ran']);self.assertEqual(v['calls'],1)
    def test_later_non_native_error_cannot_clear_deferral(self):
        v=self.read('sticky');self.assertTrue(v['deferred']);self.assertEqual(v['calls'],1)
    def test_abandon_batch_does_not_issue_native_setter_or_getter(self):
        v=self.read('batch');self.assertTrue(v['unchanged_callbacks']);self.assertFalse(v['outer']['restored']);self.assertTrue(v['outer']['abandoned_after_native_failure'])
    def test_nested_abandoned_batches_cannot_restore_each_others_flag(self):
        v=self.read('nested_batch');self.assertTrue(v['unchanged_callbacks']);self.assertFalse(v['inner']['restored']);self.assertTrue(v['inner']['abandoned_after_native_failure'])
    def test_failed_batch_enable_does_not_issue_another_native_setter(self):
        v=self.read('constructor_com_write');self.assertEqual(v,{'type':'COMException','reads':1,'writes':1})
    def test_failed_batch_readback_does_not_issue_a_restore_setter(self):
        v=self.read('constructor_com_readback');self.assertEqual(v,{'type':'COMException','reads':2,'writes':1})
    def test_native_failure_during_restore_blocks_subsequent_restore_context_callback(self):
        v=self.read('restore_com');self.assertEqual(v,{'type':'COMException','deferred':True,'calls':1,'subsequent_callback_ran':False})
    def test_failed_restore_stops_further_calls_even_when_error_is_managed(self):
        v=self.read('restore_known_error');self.assertEqual(v,{'type':'InvalidOperationException','deferred':True,'calls':1,'subsequent_callback_ran':False})
if __name__=='__main__':unittest.main()
