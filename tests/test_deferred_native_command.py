"""Compile the production command recovery controls, without starting CAD."""
import json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class DeferredCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.exe=pathlib.Path(cls.temp.name)/'command.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        sources=('executor/NativeCommandBatch.cs','executor/DeferredNativeCommandState.cs','tests/DeferredNativeCommandStateTests.cs')
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe),*[str(ROOT/n) for n in sources]],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError((r.stdout+r.stderr).decode(errors='replace'))
    def read(self,mode):
        r=subprocess.run([str(self.exe),mode],capture_output=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_normal_checkpoint_and_unowned_true_flag_make_no_native_calls(self):
        for mode in ('empty','not_owned'):
            with self.subTest(mode=mode):
                v=self.read(mode);self.assertFalse(v['pending']);self.assertFalse(v['prepared']);self.assertEqual((v['reads'],v['writes'],v['validated']),(0,0,0))
    def test_exact_model_required_before_any_native_call(self):
        for mode in ('wrong_model','conflict'):
            with self.subTest(mode=mode):
                v=self.read(mode);self.assertEqual(v['error'],'NativeCommandStateException');self.assertTrue(v['pending']);self.assertEqual((v['reads'],v['writes'],v['validated']),(0,0,0))
    def test_foreign_document_rejection_precedes_flag_read_or_write(self):
        v=self.read('foreign_documents');self.assertEqual(v['error'],'InvalidOperationException');self.assertTrue(v['pending']);self.assertEqual((v['reads'],v['writes'],v['validated']),(0,0,1))
    def test_prepare_resets_owned_flag_once_but_does_not_certify_restoration(self):
        v=self.read('prepare');self.assertTrue(v['prepared']);self.assertTrue(v['pending']);self.assertFalse(v['flag']);self.assertEqual((v['reads'],v['writes'],v['validated']),(2,1,1))
    def test_already_false_flag_is_observed_without_rewriting(self):
        v=self.read('already_false');self.assertTrue(v['pending']);self.assertTrue(v['prepared']);self.assertEqual(v['writes'],0);self.assertEqual(v['reads'],2)
    def test_only_complete_verified_restore_clears_pending(self):
        v=self.read('complete');self.assertFalse(v['pending']);self.assertIsNone(v['error']);self.assertEqual((v['reads'],v['writes']),(3,1))
    def test_flag_changed_during_restore_retains_unresolved_state(self):
        v=self.read('changed_during_restore');self.assertTrue(v['pending']);self.assertEqual(v['error'],'NativeCommandStateException')
    def test_read_write_or_readback_failure_retains_state_without_retry(self):
        for mode,reads,writes,error in (('read_failure',1,0,'COMException'),('write_failure',1,1,'COMException'),('bad_readback',2,1,'NativeCommandStateException')):
            with self.subTest(mode=mode):
                v=self.read(mode);self.assertTrue(v['pending']);self.assertEqual((v['reads'],v['writes'],v['error']),(reads,writes,error))
    def test_abandon_notifies_only_owning_batch_without_native_restore(self):
        for mode,reads in (('batch_notification',2),('nested_notification',3)):
            with self.subTest(mode=mode):
                v=self.read(mode);self.assertTrue(v['pending']);self.assertEqual(v['notifications'],1);self.assertEqual((v['reads'],v['writes']),(reads,1));self.assertTrue(v['flag'])
    def test_failed_constructor_captures_owned_state_without_retry(self):
        v=self.read('constructor_notification');self.assertTrue(v['pending']);self.assertEqual((v['reads'],v['writes'],v['notifications'],v['error']),(1,1,1,'COMException'))
    def test_failed_dispose_captures_owned_state_without_second_restore(self):
        v=self.read('restore_notification');self.assertTrue(v['pending']);self.assertEqual((v['reads'],v['writes'],v['notifications'],v['error']),(2,2,1,'NativeCommandStateException'))
if __name__=='__main__':unittest.main()
