"""Compile/run the actual identity admission policy, without CAD or interop."""
import os,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class MotorIdentityTests(unittest.TestCase):
    def test_alias_requires_exact_native_entity_and_component_not_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            exe=Path(folder)/'motor-reference.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            p=subprocess.run([str(compiler),'/nologo','/out:'+str(exe),str(ROOT/'executor/NativeObjectReferenceIdentity.cs'),str(ROOT/'tests/MotorReferenceIdentityTests.cs')],capture_output=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            p=subprocess.run([str(exe)],capture_output=True,timeout=10);self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.decode('utf8'),'6 PASS')
if __name__=='__main__':unittest.main()
