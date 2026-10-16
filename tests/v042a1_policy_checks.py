"""Bounded checkpoint cache reconstruction and monotonic timing accounting; no CAD or process enumeration."""
import json, os, subprocess, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'runs/v042a1-policy'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    source=folder/'Checks.cs'
    source.write_text(r'''using System;using System.Linq;using System.Collections.Generic;using System.Web.Script.Serialization;
class Checks {
 static int n;static void Check(bool x){n++;if(!x)throw new Exception("check "+n);}
 static Dictionary<string,object> D(object o){var j=new JavaScriptSerializer();return j.Deserialize<Dictionary<string,object>>(j.Serialize(o));}
 static double[] P(double x=0,double t=0){double c=Math.Cos(t),s=Math.Sin(t);return new[]{c,s,0,-s,c,0,0,0,1,x,0,0,1,0,0,0};}
 static int Main(){try{return Run();}catch(Exception e){Console.Error.WriteLine(e.GetType().Name+":"+e.Message);return 1;}}
 static int Run(){
 foreach(int type in new[]{1,4}){Check(CheckpointCachePolicy.Allows(type,true,false,5,25));Check(CheckpointCachePolicy.Allows(type,true,false,5,300));Check(!CheckpointCachePolicy.Allows(type,false,false,5,25));Check(!CheckpointCachePolicy.Allows(type,true,true,5,25));Check(!CheckpointCachePolicy.Allows(type,true,false,5,1000));}
 foreach(int type in new[]{-1,0,2,3,5})Check(!CheckpointCachePolicy.Allows(type,true,false,5,25));
 foreach(double duration in new[]{0,-1,double.NaN,double.PositiveInfinity,30.001})Check(!CheckpointCachePolicy.Allows(4,true,false,duration,25));
 Check(CheckpointCachePolicy.Allows(4,true,false,30,60));Check(!CheckpointCachePolicy.Allows(4,true,false,30,61));
 var timing=new OperationTiming();timing.Start("copy");timing.Start("worker_round_trip");timing.Finish();timing.Finish();var summary=D(timing.Export());var rows=((System.Collections.IEnumerable)summary["phases"]).Cast<object>().ToArray();Check(rows.Length==2);Check(summary["current_stage"]==null);Check((string)D(rows[0])["stage"]=="copy");Check((string)D(rows[1])["stage"]=="worker_round_trip");Check(rows.All(v=>Convert.ToInt64(D(v)["elapsed_ms"])>=0));Check(rows.Sum(v=>Convert.ToInt64(D(v)["elapsed_ms"]))<=Convert.ToInt64(summary["total_elapsed_ms"]));
 Console.WriteLine(n);return 0;}}
''',encoding='utf-8',newline='\n')
    exe=folder/'Checks.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe)]+[str(ROOT/'executor'/n) for n in ['CheckpointCachePolicy.cs','StudyCacheBudget.cs','OperationTiming.cs']]+[str(source)],check=True)
    count=int(subprocess.check_output([str(exe)],text=True).strip());result={'all_passed':True,'checks':count,'cad_connection_used':False}
    (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
