"""Compile the production signature diagnostic; real admission remains exact hash equality."""
import json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class SignatureDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.exe=pathlib.Path(cls.temp.name)/'signature.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe),str(ROOT/'executor/ConnectionSignatureDiff.cs'),str(ROOT/'tests/ConnectionSignatureDiffTests.cs')],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError((r.stdout+r.stderr).decode(errors='replace'))
    def diff(self,a,b):
        r=subprocess.run([str(self.exe),json.dumps(a),json.dumps(b)],capture_output=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr)
        return json.loads(r.stdout)
    def test_identical_input(self):self.assertEqual(self.diff({'poses':{'a':[0,1]},'documents':[{'dirty':False}]},{'poses':{'a':[0,1]},'documents':[{'dirty':False}]}),[])
    def test_dirty_and_stamp_remain_visible(self):self.assertEqual(self.diff({'documents':[{'dirty':False,'stamp':1}]},{'documents':[{'dirty':True,'stamp':2}]}),['documents'])
    def test_mechanical_pose_and_mate_changes_are_not_normalized(self):self.assertEqual(self.diff({'poses':[0],'mates':[1]},{'poses':[1e-12],'mates':[2]}),['mates','poses'])
    def test_missing_and_null_are_distinct(self):self.assertEqual(self.diff({'a':None},{'b':None}),['a','b'])
    def test_inventory_order_changes_are_reported(self):self.assertEqual(self.diff({'mates':[1,2]},{'mates':[2,1]}),['mates'])
    def test_configuration_and_file_hash_remain_visible(self):self.assertEqual(self.diff({'configuration':'a','files':{'a':'x'}},{'configuration':'b','files':{'a':'y'}}),['configuration','files'])
if __name__=='__main__':unittest.main()
