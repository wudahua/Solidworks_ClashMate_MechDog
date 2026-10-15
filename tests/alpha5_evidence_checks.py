"""Compile production math, diagnostics and health deltas without COM."""
import json,os,subprocess,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'runs/alpha5-evidence'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
source=folder/'Alpha5Checks.cs'
source.write_text(r'''using System;using System.Linq;using System.Collections.Generic;
class Cad {public static readonly System.Web.Script.Serialization.JavaScriptSerializer Json = new System.Web.Script.Serialization.JavaScriptSerializer { MaxJsonLength=16777216 };}
class Alpha5Checks {
 static int count;
 static void C(bool value){if(!value)throw new Exception("check "+count);count++;}
 static double[] P(double a){double c=Math.Cos(a),s=Math.Sin(a);return new[]{c,s,0,-s,c,0,0,0,1,0,0,0,1,0,0,0};}
 static object M(int id,int error){return new{native_feature_id=id,error=error,name="mate"+id};}
 static Dictionary<string,object> D(object o){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(o));}
 static int Main(){try{
  var turns=Enumerable.Range(0,121).Select(i=>P(i*Math.PI/30)).ToArray();var boundary=MotionIntent.Evaluate(turns,new[]{0.0,0,1},"rotary",720);C((string)boundary["assertion"]=="pass");C((bool)boundary["minimum_travel_rounding_applied"]);C((string)MotionIntent.Evaluate(turns,new[]{0.0,0,1},"rotary",720.01)["assertion"]=="fail");
  var zero=new[]{P(0),P(0)};C((string)MotionIntent.Evaluate(zero,new[]{0.0,0,1},"rotary",1e-12)["assertion"]=="fail");
  var slide=P(0);slide[9]=.02-1e-17;var linear=MotionIntent.Evaluate(new[]{P(0),slide},new[]{1.0,0,0},"linear",20);C((string)linear["assertion"]=="pass");C((string)MotionIntent.Evaluate(new[]{P(0),slide},new[]{1.0,0,0},"linear",20.01)["assertion"]=="fail");
  var tilt=new[]{1.0,0,0,0,0,1,0,-1,0,0,0,0,1,0,0,0};var poses=Enumerable.Range(0,13).Select(i=>{double a=i*Math.PI/36,c=Math.Cos(a),s=Math.Sin(a);var p=(double[])tilt.Clone();double[] delta={c,0,-s,0,1,0,s,0,c};for(int r=0;r<3;r++)for(int j=0;j<3;j++)p[3*r+j]=Enumerable.Range(0,3).Sum(k=>tilt[3*r+k]*delta[3*k+j]);return p;}).ToArray();var tilted=MotionIntent.Evaluate(poses,new[]{0.0,1,0},"rotary",59);C((string)tilted["assertion"]=="pass");C(Math.Abs(Convert.ToDouble(tilted["signed_net_travel"])-60)<1e-8);C((string)MotionIntent.Evaluate(poses,new[]{0.0,0,1},"rotary",1)["assertion"]=="fail");
  try{MotionIntent.Evaluate(new[]{P(0),P(Math.PI/2)},new[]{0.0,0,1},"rotary",1);throw new Exception("missing ambiguity");}catch(MotionSampleException error){var d=D(error.Diagnostics);C(Convert.ToInt32(d["frame_after"])==1);C(Math.Abs(Convert.ToDouble(d["observed_interval_rotation_deg"])-90)<1e-8);}
  C(SolverEvidence.FailedState("pending","SOLVER_SETTINGS_UNVERIFIED")=="not_started");C(SolverEvidence.FailedState("running","RESULTS_STALE")=="failed");C(SolverEvidence.FailedState("completed","MOTION_RESULTS_INCOMPLETE")=="incomplete");
  var deltaHealth=D(MateHealthEvidence.Difference(new[]{M(1,0),M(2,0)},new[]{M(1,1),M(2,0),M(3,0)},new[]{1,2}));C(Convert.ToInt32(deltaHealth["observed_error_count"])==1);C((string)deltaHealth["root_cause"]=="not_proven_from_native_error_location");C(Cad.Json.Serialize(deltaHealth["existing_feature_errors"]).Contains("mate1"));C(Cad.Json.Serialize(deltaHealth["new_feature_errors"])=="[]");
  Console.WriteLine(Cad.Json.Serialize(new{all_passed=true,checks=count,cad_connection_used=false,requires_solidworks_installation=false}));return 0;
 }catch(Exception e){Console.Error.WriteLine(e.ToString());return 1;}}
}''',encoding='utf-8')
# Pure production policies only: no COM types, interop DLLs, or SolidWorks install needed.
exe=folder/'Alpha5Checks.exe';args=[str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/platform:x64','/main:Alpha5Checks','/reference:System.Web.Extensions.dll','/out:'+str(exe)]
sources=[ROOT/'executor'/n for n in ('MotionIntent.cs','MateHealthEvidence.cs','SolverStatus.cs')]
subprocess.run(args+[str(p) for p in sources]+[str(source)],check=True)
result=subprocess.run([str(exe)],capture_output=True,timeout=30);assert result.returncode==0,result.stderr.decode(errors='replace');report=json.loads(result.stdout);(folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
