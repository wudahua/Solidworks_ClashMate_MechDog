"""Compile the production read-only reference policy, without COM/CAD activation."""
import os,subprocess,json,uuid,unittest
from pathlib import Path
from transport_cleanup import remove_test_root

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt','Windows native executor compiler')
class ReferenceReadTests(unittest.TestCase):
    def test_only_disconnected_pure_read_can_reacquire_once_after_identity_and_audit(self):
        compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():self.skipTest('.NET Framework compiler unavailable')
        base=ROOT/'runs/reference-read-tests';folder=base/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
        self.addCleanup(remove_test_root,folder,base)
        source=folder/'Check.cs';exe=folder/'Check.exe'
        source.write_text('''using System;using System.Runtime.InteropServices;
class Check{
 static void Need(bool x){if(!x)throw new Exception("policy violation");}
 static COMException Disconnected(){return new COMException("stale read",unchecked((int)0x80010108));}
 static void Main(){
  int reads=0,verify=0,audits=0;
  int result=MotionReferenceRead.Read(()=>{reads++;if(reads==1)throw Disconnected();return 7;},()=>verify++,o=>audits++);
  Need(result==7&&reads==2&&verify==1&&audits==2);
  reads=verify=audits=0;
  try{MotionReferenceRead.Read<int>(()=>{reads++;throw new COMException("other",unchecked((int)0x80004005));},()=>verify++,o=>audits++);throw new Exception("accepted");}
  catch(COMException e){Need(e.HResult==unchecked((int)0x80004005)&&reads==1&&verify==0&&audits==0);}
  reads=verify=audits=0;
  try{MotionReferenceRead.Read<int>(()=>{reads++;throw Disconnected();},()=>{verify++;throw new InvalidOperationException("identity changed");},o=>audits++);throw new Exception("accepted");}
  catch(InvalidOperationException){Need(reads==1&&verify==1&&audits==1);}
  reads=verify=audits=0;
  try{MotionReferenceRead.Read<int>(()=>{reads++;throw Disconnected();},()=>verify++,o=>{audits++;throw new System.IO.IOException("audit failed");});throw new Exception("accepted");}
  catch(COMException e){Need(reads==1&&verify==0&&audits==1&&e.HResult==unchecked((int)0x80010108));}
  reads=verify=audits=0;
  try{MotionReferenceRead.Read<int>(()=>{reads++;throw Disconnected();},()=>verify++,o=>audits++);throw new Exception("accepted");}
  catch(COMException e){Need(reads==2&&verify==1&&(int)e.Data["first_read_native_hresult"]==unchecked((int)0x80010108));}
  Console.WriteLine("{\\"status\\":\\"pass\\",\\"scenarios\\":5,\\"CAD_calls\\":0}");
 }
}''',encoding='utf8')
        built=subprocess.run([str(compiler),'/nologo','/out:'+str(exe),str(ROOT/'executor/MotionReferenceRead.cs'),str(source)],capture_output=True,timeout=30)
        self.assertEqual(built.returncode,0,(built.stdout+built.stderr).decode('utf8',errors='replace'))
        p=subprocess.run([str(exe)],capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr.decode('utf8',errors='replace'))
        self.assertEqual(json.loads(p.stdout)['scenarios'],5)


if __name__=='__main__':unittest.main()
