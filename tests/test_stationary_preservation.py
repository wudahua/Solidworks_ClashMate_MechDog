"""Actual native admission policy compiled without CAD. Eligibility never means verified motion."""
import json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class NativeStationaryPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);exe=pathlib.Path(cls.temp.name)/'scope.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe),str(ROOT/'executor/StationaryPreservationPolicy.cs'),str(ROOT/'tests/StationaryPreservationTests.cs')],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError((r.stdout+r.stderr).decode(errors='replace'))
        r=subprocess.run([str(exe)],capture_output=True,timeout=15)
        if r.returncode:raise AssertionError(r.stderr)
        cls.result=json.loads(r.stdout)
    def test_only_declared_nonfixed_top_level_nonpattern_part_and_fixed_anchor_without_new_constraint_is_eligible(self):self.assertEqual(self.result['cases'],[True,False,False,False,False,False,False])
    def test_only_exact_native_full_status_is_eligible(self):self.assertEqual(self.result['native_states'],[False,False,False,False,True,False])
if __name__=='__main__':unittest.main()
