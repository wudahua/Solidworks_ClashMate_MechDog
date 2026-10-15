"""Exercise movement and native-time admission policies without SolidWorks."""
import json,os,subprocess,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'runs/alpha8-policy'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    source=folder/'Checks.cs'
    source.write_text(r'''using System;using System.Linq;using System.Collections.Generic;
class Checks {
 static int n;static void Check(bool x){n++;if(!x)throw new Exception("policy check "+n);}
 static double[] P(double x=0,double theta=0){double c=Math.Cos(theta),s=Math.Sin(theta);return new[]{c,s,0,-s,c,0,0,0,1,x,0,0,1,0,0,0};}
 static Dictionary<string,double[]> D(double x=0,double theta=0){return new Dictionary<string,double[]>{{"fixed",P()},{"moving",P(x,theta)}};}
 static int Main(){
 Check((bool)MatePosePolicy.Evaluate(D(),D(),1,1)["accepted"]);
 var huge=MatePosePolicy.Evaluate(D(),D(.5376307736041883,Math.PI),1,1);Check(!(bool)huge["accepted"]);Check((int)huge["changed_component_count"]==1);Check((int)huge["exceeded_component_count"]==1);Check(Math.Abs((double)huge["maximum_translation_mm"]-537.6307736041883)<1e-9);Check(Math.Abs((double)huge["maximum_rotation_deg"]-180)<1e-9);
 Check(!(bool)MatePosePolicy.Evaluate(D(),D(0,.1),1,1)["accepted"]);Check(!(bool)MatePosePolicy.Evaluate(D(),D(.1,0),1,1)["accepted"]);Check((bool)MatePosePolicy.Evaluate(D(),D(.1,.1),101,6)["accepted"]);
 var missing=D();missing.Remove("moving");Check(!(bool)MatePosePolicy.Evaluate(D(),missing,10000,180)["accepted"]);
 var bad=D();bad["moving"][9]=double.NaN;Check(!(bool)MatePosePolicy.Evaluate(D(),bad,10000,180)["accepted"]);
 foreach(var value in new[]{double.NaN,double.PositiveInfinity,-1.0,10001}){try{MatePosePolicy.Validate(value,1);throw new Exception("bad budget accepted");}catch(CadFault e){Check(e.Code=="INVALID_MATE_POSE_BUDGET");}}
 int calls=0;SolverTimeCapture.Select(0,0,0,()=>++calls>1,()=>0,()=>false,()=>{},()=>{},()=>{});Check(calls==2);
 calls=0;SolverTimeCapture.Select(0,1,1,()=>{calls++;return true;},()=>1,()=>false,()=>{},()=>{},()=>{});Check(calls==1);
 foreach(var mode in new[]{"false","wrong_clock","playing","nan"}){calls=0;try{SolverTimeCapture.Select(7,1,1,()=>{calls++;return mode!="false";},()=>mode=="nan"?double.NaN:mode=="wrong_clock"?0:1,()=>mode=="playing",()=>{},()=>{},()=>{});throw new Exception("unsafe time accepted");}catch(CadFault e){Check(e.Code=="SOLVER_TIME_SELECTION_FAILED"&&e.Diagnostics!=null&&calls==2);}}
 Console.WriteLine(n);return 0;}}
''',encoding='utf-8',newline='\n')
    exe=folder/'Checks.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/out:'+str(exe)]+[str(ROOT/'executor'/n) for n in ['CadFault.cs','PoseValidation.cs','MatePosePolicy.cs','SolverTimeCapture.cs']]+[str(source)],check=True)
    count=int(subprocess.check_output([str(exe)],text=True).strip())
    result={'all_passed':True,'checks':count,'cad_connection_used':False}
    (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
