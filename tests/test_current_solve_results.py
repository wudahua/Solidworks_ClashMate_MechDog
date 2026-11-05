"""Real production freshness validation with replaced, stale and failed handles."""
import json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class CurrentResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.exe=pathlib.Path(cls.temp.name)/'results.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe),str(ROOT/'executor/SolverEvidence.cs'),str(ROOT/'tests/CurrentSolveResultsTests.cs')],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError((r.stdout+r.stderr).decode(errors='replace'))
    def read(self,mode):
        r=subprocess.run([str(self.exe),mode],capture_output=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_post_sampling_acquires_current_handle_without_touching_disconnected_old_one(self):
        v=self.read('replace_after_sampling');self.assertIsNone(v['error']);self.assertTrue(v['before'] and v['after']);self.assertEqual((v['gets'],v['old_reads'],v['current_reads']),(2,1,1))
    def test_native_stale_flag_is_not_ignored(self):
        v=self.read('stale');self.assertEqual(v['error'],'RESULTS_STALE');self.assertFalse(v['before']);self.assertEqual((v['gets'],v['old_reads']),(1,1))
    def test_null_results_cannot_pass(self):
        v=self.read('null');self.assertEqual(v['error'],'RESULTS_STALE');self.assertEqual((v['gets'],v['old_reads']),(1,0))
    def test_getter_com_failure_propagates_without_retry(self):
        v=self.read('getter_com');self.assertEqual(v['error'],'COMException');self.assertEqual((v['gets'],v['old_reads']),(1,0))
    def test_current_result_com_failure_propagates_without_retry(self):
        v=self.read('result_com');self.assertEqual(v['error'],'COMException');self.assertEqual((v['gets'],v['old_reads']),(1,1))
