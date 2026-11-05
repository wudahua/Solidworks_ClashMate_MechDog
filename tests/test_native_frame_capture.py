"""Compile actual per-frame batch boundaries. No CAD is activated."""
import json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class FrameCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.exe=pathlib.Path(cls.temp.name)/'frame.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        sources=('executor/NativeCommandBatch.cs','executor/NativeFrameCapture.cs','tests/NativeFrameCaptureTests.cs')
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe),*[str(ROOT/n) for n in sources]],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError((r.stdout+r.stderr).decode(errors='replace'))
    def read(self,mode):
        r=subprocess.run([str(self.exe),mode],capture_output=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_every_frame_selects_outside_read_batch_and_restores_before_next_frame(self):
        v=self.read('two_frames');self.assertIsNone(v['error']);self.assertEqual(v['events'],['select:False','write:True','read:True','write:False','observed:False']*2);self.assertEqual(v['poses'],2)
    def test_foreign_command_at_entry_is_not_cleared_or_used_for_selection(self):
        v=self.read('foreign_entry');self.assertEqual((v['selections'],v['poses'],v['writes']),(0,0,0));self.assertTrue(v['flag']);self.assertEqual(v['error'],'NativeCommandStateException')
    def test_selection_failure_does_not_enter_a_batch_or_retry_selection(self):
        v=self.read('select_com');self.assertEqual((v['selections'],v['poses'],v['writes']),(1,0,0));self.assertFalse(v['flag']);self.assertEqual(v['error'],'COMException')
    def test_unowned_command_change_after_selection_is_not_cleared(self):
        v=self.read('foreign_after_selection');self.assertEqual((v['selections'],v['poses'],v['writes']),(1,0,0));self.assertTrue(v['flag']);self.assertEqual(v['error'],'NativeCommandStateException')
    def test_native_pose_failure_abandons_without_another_native_setter(self):
        v=self.read('read_com');self.assertTrue(v['flag']);self.assertEqual((v['writes'],v['notifications'],v['poses']),(1,1,1));self.assertEqual(v['error'],'COMException')
    def test_known_managed_read_failure_restores_owned_flag_once(self):
        v=self.read('read_known');self.assertFalse(v['flag']);self.assertEqual((v['writes'],v['notifications']),(2,0));self.assertEqual(v['error'],'InvalidOperationException')
    def test_failed_batch_enable_never_reads_poses_or_tries_a_second_setter(self):
        v=self.read('enter_com');self.assertEqual((v['poses'],v['writes'],v['notifications']),(0,1,1));self.assertEqual(v['error'],'COMException')
    def test_failed_restore_does_not_retry_and_cannot_produce_a_successful_frame(self):
        v=self.read('restore_com');self.assertTrue(v['flag']);self.assertEqual((v['poses'],v['writes'],v['notifications']),(1,2,1));self.assertEqual(v['error'],'NativeCommandStateException')
if __name__=='__main__':unittest.main()
