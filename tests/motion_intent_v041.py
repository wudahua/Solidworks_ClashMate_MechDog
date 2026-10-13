"""Compile and exercise the production sampled-motion evaluator without COM."""
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT/'runs/intent-tests'/uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    source = folder/'Probe.cs'
    source.write_text('''using System;using System.Linq;
class Probe {
 static int n;
 static double[] P(double x,double y,double z,double a){double c=Math.Cos(a),s=Math.Sin(a);return new[]{c,s,0,-s,c,0,0,0,1,x,y,z,1,0,0,0};}
 static void Check(bool v){if(!v)throw new Exception("case "+n);n++;}
 static string A(double[][] p,double[] axis,string k,double m){return (string)MotionIntent.Evaluate(p,axis,k,m)["assertion"];}
 static void Reject(Action a){bool rejected=false;try{a();}catch(ArgumentException){rejected=true;}Check(rejected);}
 static void Main(){
  var slide=new[]{P(0,0,0,0),P(.005,0,0,0),P(.01,0,0,0)};
  Check(A(slide,new[]{1.0,0,0},"linear",5)=="pass");
  Check(A(slide,new[]{-2.0,0,0},"linear",5)=="pass");
  Check(A(slide,new[]{0.0,1,0},"linear",5)=="fail");
  Check(A(slide,new[]{1.0,0,0},"linear",20)=="fail");
  Check(A(new[]{P(0,0,0,0),P(.01,.001,0,0)},new[]{1.0,0,0},"linear",5)=="fail");
  Check(A(new[]{P(0,0,0,0),P(.01,0,0,.1)},new[]{1.0,0,0},"linear",5)=="fail");
  var rotation=Enumerable.Range(0,31).Select(i=>P(0,0,0,i*Math.PI/75)).ToArray();
  Check(A(rotation,new[]{0.0,0,1},"rotary",30)=="pass");
  Check(A(rotation,new[]{1.0,0,0},"rotary",30)=="fail");
  Check(A(new[]{P(0,0,0,0),P(0,0,0,0)},new[]{0.0,0,1},"rotary",1)=="fail");
  Reject(()=>A(new[]{P(0,0,0,0),P(0,0,0,Math.PI/2)},new[]{0.0,0,1},"rotary",1));
  Reject(()=>A(slide,new[]{0.0,0,0},"linear",1));
  Reject(()=>A(slide,new[]{1.0,0,0},"linear",double.NaN));
  Reject(()=>A(new[]{P(0,0,0,0)},new[]{1.0,0,0},"linear",1));
  Reject(()=>A(new[]{P(0,0,0,0),P(double.PositiveInfinity,0,0,0)},new[]{1.0,0,0},"linear",1));
  Console.WriteLine(n);
 }
}''', encoding='utf-8')
    exe = folder/'Probe.exe'
    subprocess.run([str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'), '/nologo', '/platform:x64', '/out:'+str(exe), str(ROOT/'executor/MotionIntent.cs'), str(source)], check=True)
    checks = int(subprocess.check_output([str(exe)], text=True).strip())
    report = {'all_passed': True, 'checks': checks, 'cad_connection_used': False}
    (ROOT/'runs/motion-intent-v041.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
