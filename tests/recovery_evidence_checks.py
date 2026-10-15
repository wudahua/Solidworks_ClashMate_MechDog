"""Exercise compiled error/pose evidence without constructing a CAD session."""
import json, os, shutil, subprocess, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT/'runs/recovery-evidence-tests'/uuid.uuid4().hex[:8]
folder.mkdir(parents=True)
source = folder/'Checks.cs'
source.write_text(r'''using System;using System.Linq;using System.Reflection;using System.Collections.Generic;
class RecoveryChecks {
 static int count;
 static void C(bool ok){if(!ok)throw new Exception("check "+count);count++;}
 static Dictionary<string,object> D(object value){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(value));}
 static object Call(Type type,string method,params object[] args){return type.GetMethod(method,BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,args);}
 static double[] P(double x,double angle){double c=Math.Cos(angle),s=Math.Sin(angle);return new[]{c,s,0,-s,c,0,0,0,1,x,0,0,1,0,0,0};}
 static void Main(){
  var failure=new CadFault("MODEL_REVISION_CHANGED","specific input identity diagnostic",new{revision_match=true,file_hashes_match=false});
  var error=D(Call(typeof(Program),"Error",failure,"unknown","restored"));
  C((string)error["message"]==failure.Message);C((string)error["restoration_status"]=="unknown");
  C((string)D(Call(typeof(Program),"Error",failure,"pending","pending"))["restoration_status"]=="unknown");
  C(!(bool)D(D(error["diagnostics"])["details"])["file_hashes_match"]);
  var evidence=D(Call(typeof(Cad),"FailureEvidence",failure));C((string)evidence["code"]==failure.Code);C(evidence["exception_chain"]!=null);
  var before=new Dictionary<string,double[]>{{"part",P(0,0)}};var after=new Dictionary<string,double[]>{{"part",P(.02,.1)}};
  var change=D(Call(typeof(Cad),"PoseChange",before,after));
  C(Math.Abs(Convert.ToDouble(change["maximum_translation_m"])-.02)<1e-12);
  C(Math.Abs(Convert.ToDouble(change["maximum_rotation_rad"])-.1)<1e-12);C(!(bool)change["within_pose_tolerance"]);
  C((bool)D(Call(typeof(Cad),"PoseChange",before,before))["within_pose_tolerance"]);
  bool rejected=false;try{Call(typeof(Cad),"PoseChange",before,new Dictionary<string,double[]>());}catch(TargetInvocationException){rejected=true;}C(rejected);
  Console.WriteLine(count);
 }
}''', encoding='utf-8')
redist = Path(os.environ.get('SW_INSTALL_DIR',r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'))/'api/redist'
interop = list(redist.glob('SolidWorks.Interop.*.dll'))
for path in interop:
    shutil.copyfile(path,folder/path.name)
compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
exe = folder/'Checks.exe'
args = [str(compiler),'/nologo','/platform:x64','/main:RecoveryChecks','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll','/out:'+str(exe)]
args += ['/reference:'+str(redist/name) for name in ('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')]
subprocess.run(args+[str(p) for p in (ROOT/'executor').glob('*.cs')]+[str(source)],check=True)
count = int(subprocess.check_output([str(exe)],text=True).strip())
manifest = (ROOT/'executor/bin/build-manifest.json').read_bytes()
assert not manifest.startswith(b'\xef\xbb\xbf')
json.loads(manifest.decode('utf-8'))
report = {'all_passed':True,'checks':count+1,'cad_connection_used':False,'build_manifest_plain_utf8':True}
(folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
