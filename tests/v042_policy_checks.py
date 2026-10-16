"""Explicit probe budget boundaries; no CAD or process enumeration."""
import json, os, subprocess, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'runs/v042-policy'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    source=folder/'Checks.cs'
    source.write_text(r'''using System;using System.Linq;using System.Collections.Generic;using System.Web.Script.Serialization;
class Checks {
 static int n;static void Check(bool x){n++;if(!x)throw new Exception("check "+n);}
 static Dictionary<string,object> D(object o){var j=new JavaScriptSerializer();return j.Deserialize<Dictionary<string,object>>(j.Serialize(o));}
 static double[] P(double x=0,double t=0){double c=Math.Cos(t),s=Math.Sin(t);return new[]{c,s,0,-s,c,0,0,0,1,x,0,0,1,0,0,0};}
 static int Main(){
 Check(MotionBudgets.ProbeAllows(1,30));Check(MotionBudgets.ProbeAllows(5,25));Check(MotionBudgets.ProbeAllows(5,120));
 foreach(double v in new[]{0,-1,5.001,double.NaN,double.PositiveInfinity,double.NegativeInfinity,1.01})Check(!MotionBudgets.ProbeAllows(v,25));
 Check(!MotionBudgets.ProbeAllows(1,4));Check(!MotionBudgets.ProbeAllows(1,121));Check(MotionBudgets.ProbeAllows(.2,5));
 var budgets=D(MotionBudgets.Describe());var probe=D(budgets["compatibility_probe"]);Check(Convert.ToInt32(probe["default_duration_s"])==1);Check(Convert.ToInt32(probe["maximum_duration_s"])==5);Check(Convert.ToInt32(probe["maximum_frames"])==601);Check((bool)probe["explicit_extension_required"]);
 Console.WriteLine(n);return 0;}}
''',encoding='utf-8',newline='\n')
    exe=folder/'Checks.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe)]+[str(ROOT/'executor'/n) for n in ['MotionBudgets.cs']]+[str(source)],check=True)
    count=int(subprocess.check_output([str(exe)],text=True).strip());result={'all_passed':True,'checks':count,'cad_connection_used':False}
    (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
