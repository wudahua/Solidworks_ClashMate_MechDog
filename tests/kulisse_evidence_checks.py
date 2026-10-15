"""Compile production sources and run pure evidence checks without starting COM."""
import json,os,subprocess,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CS=r'''using System;using System.Linq;using System.Collections.Generic;
public partial class Cad {public static void EvidenceImportGuard(UserModel model,bool allow){RequireCompleteImport(model,allow);}}
class KulisseEvidence {
 static int count;static void Require(bool v,string name){if(!v)throw new Exception(name);count++;}
 static double[] Pose(double angle,double x=0){double c=Math.Cos(angle),s=Math.Sin(angle);return new[]{c,s,0.0,-s,c,0,0,0,1,x,0,0,1,0,0,0};}
 static int Main(){try{return RunChecks();}catch(Exception e){Console.Error.WriteLine(e.ToString());return 1;}}
 static int RunChecks(){
  Require(ImportReferences.VirtualHint(@"C:\Temp\swx12\VC~~\parent\part^parent.SLDPRT"),"virtual hint");
  Require(!ImportReferences.VirtualHint(@"C:\Parts\part^parent.SLDPRT"),"caret alone");Require(!ImportReferences.VirtualHint(@"C:\Parts\VC~~\ordinary.SLDPRT"),"directory alone");
  try{ImportReferences.RequireExternal(@"C:\Temp\VC~~\parent\part^parent.SLDPRT");throw new Exception("no rejection");}catch(CadFault e){Require(e.Code=="VIRTUAL_COMPONENT_REFERENCE_UNSUPPORTED"&&!Cad.Json.Serialize(e.Diagnostics).Contains("C:\\\\Temp"),"redacted hint");}
  try{ImportReferences.RequireExternal(@"C:\no_such_file_458734.SLDPRT");throw new Exception("no missing");}catch(CadFault e){Require(e.Code=="SOURCE_REFERENCE_MISSING","actual external missing");}
  try{ImportReferences.RequireExternal(@"C:\part.step");throw new Exception("no type");}catch(CadFault e){Require(e.Code=="SOURCE_REFERENCE_TYPE_UNSUPPORTED","unsupported type");}
  try{Cad.EvidenceImportGuard(new Cad.UserModel{Id="user_test",ImportState="incomplete"},false);throw new Exception("unsafe model allowed");}catch(CadFault e){Require(e.Code=="MODEL_IMPORT_INCOMPLETE","incomplete guard");}Cad.EvidenceImportGuard(new Cad.UserModel{ImportState="incomplete"},true);Require(true,"read catalog of incomplete model");
  var expected=Enumerable.Range(0,6).ToDictionary(i=>"part"+i,i=>Pose(0));var actual=expected.ToDictionary(p=>p.Key,p=>p.Value.ToArray());actual["part0"]=Pose(0,1e-7);actual["part1"]=Pose(1e-5);
  var rows=ReplayDiagnostics.Rows(expected,actual);Require((string)rows[0]["instance"]=="part1","dimensionless severity ranking");Require((double)rows[0]["severity_tolerance_ratio"]>9.9,"angle ratio");Require(ReplayDiagnostics.Bounded(rows,20).Length==6,"six all rows");Require(ReplayDiagnostics.Bounded(rows,3).Length==3,"limited display");
  var equal=ReplayDiagnostics.Rows(expected,expected);Require(equal.Select(r=>(string)r["instance"]).SequenceEqual(expected.Keys.OrderBy(v=>v,StringComparer.Ordinal)),"deterministic ties");
  actual.Remove("part5");try{ReplayDiagnostics.Rows(expected,actual);throw new Exception("scope not checked");}catch(Exception e){Require(e.Message=="COMPONENT_SCOPE_CHANGED","full identity scope");}
  var poses=new Dictionary<string,double[][]>{{"drive",new[]{Pose(0),Pose(Math.PI/2),Pose(Math.PI)}},{"follower",new[]{Pose(0),Pose(0),Pose(0)}},{"fixed",new[]{Pose(0),Pose(0),Pose(0)}}};var roles=new Dictionary<string,bool>{{"drive",false},{"follower",false},{"fixed",true}};
  var motion=ComponentMotionOverview.Analyze(poses,roles,"drive");Require((string)motion["informational"]=="REGISTERED_TARGET_MOVED_OTHER_MOVABLE_COMPONENTS_NOT_DETECTED","follower notice");Require((int)motion["other_movable_components_checked"]==1,"exclude fixed components");
  Require(ComponentMotionOverview.Analyze(poses,roles,null)["informational"]==null,"unknown native targets not guessed");poses["follower"][1]=Pose(0,0.01);Require(ComponentMotionOverview.Analyze(poses,roles,"drive")["informational"]==null,"moving follower does not warn");
  Console.WriteLine(Cad.Json.Serialize(new{all_passed=true,checks=count,cad_started=false}));return 0;
 }
}'''
def main():
 folder=ROOT/'runs/kulisse-evidence'/uuid.uuid4().hex[:8];folder.mkdir(parents=True);helper=folder/'test.cs';helper.write_text(CS,encoding='utf-8');redist=Path(os.environ.get('SW_INSTALL_DIR',r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'))/'api/redist';names=('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')
 for n in names:(folder/n).write_bytes((redist/n).read_bytes())
 exe=folder/'Checks.exe';command=[str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/platform:x64','/main:KulisseEvidence','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll','/out:'+str(exe)]+['/reference:'+str(redist/n) for n in names]+[str(p) for p in (ROOT/'executor').glob('*.cs')]+[str(helper)];subprocess.run(command,check=True);result=subprocess.run([str(exe)],capture_output=True,timeout=60);(folder/"stdout.log").write_bytes(result.stdout);(folder/"stderr.log").write_bytes(result.stderr);
 if result.returncode:raise RuntimeError("Evidence helper failed without an unhandled exception popup: "+result.stderr.decode("utf-8",errors="replace"))
 data=json.loads(result.stdout);(folder/'result.json').write_text(json.dumps(data,indent=2));print(json.dumps({'directory':str(folder),**data}))
if __name__=='__main__':main()
