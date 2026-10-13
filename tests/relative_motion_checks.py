"""Numerical regressions for moving reference frames; production C# evaluator."""
import json,os,subprocess,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'runs/relative-motion-tests'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    source=folder/'Probe.cs'
    source.write_text('''using System;using System.Linq;
class Probe {
 static int n;
 static double[] P(double x,double y,double z,double a){double c=Math.Cos(a),s=Math.Sin(a);return new[]{c,s,0,-s,c,0,0,0,1,x,y,z,1,0,0,0};}
 static double[] X(double a){double c=Math.Cos(a),s=Math.Sin(a);return new[]{1.0,0,0,0,c,s,0,-s,c,0,0,0,1,0,0,0};}
 static double[] Compose(double[] parent,double[] local){var p=RelativeMotion.Identity();for(int r=0;r<3;r++){var v=RelativeMotion.Vector(parent,local.Skip(3*r).Take(3).ToArray());for(int j=0;j<3;j++)p[3*r+j]=v[j];}var q=RelativeMotion.Vector(parent,local.Skip(9).Take(3).ToArray());for(int j=0;j<3;j++)p[9+j]=q[j]+parent[9+j];return p;}
 static void C(bool ok){if(!ok)throw new Exception("case "+n);n++;}
 static void Reject(Action a){bool ok=false;try{a();}catch(ArgumentException){ok=true;}C(ok);}
 static void Main(){
  var t=Enumerable.Range(0,31).Select(i=>i/30.0).ToArray();
  var reference=t.Select(v=>P(.04*v,-.03*v,.02*v,.6*v)).ToArray();
  var moving=t.Select((v,i)=>Compose(reference[i],P(.1+.02*v,0,0,0))).ToArray();
  var point=new[]{.05,.03,0};var axis=new[]{1.0,0,0};
  var audit=RelativeMotion.DriveAudit(moving,reference,axis,point,"linear",20,1);
  C((string)audit["status"]=="pass");C(Math.Abs(Convert.ToDouble(audit["observed_signed"])-20)<1e-9);
  C((string)RelativeMotion.DriveAudit(moving,null,axis,point,"linear",20,1)["status"]=="inconclusive");
  C((string)RelativeMotion.DriveAudit(moving,reference,axis,point,"linear",21,1)["status"]=="fail");
  var samples=RelativeMotion.Samples(moving,reference,point);
  C((string)MotionIntent.Evaluate(samples,axis,"linear",15)["assertion"]=="pass");
  C((string)MotionIntent.Evaluate(samples,axis,"linear",25)["assertion"]=="fail");
  C((string)MotionIntent.Evaluate(RelativeMotion.Samples(moving,null,point),RelativeMotion.Vector(moving[0],axis),"linear",15)["assertion"]=="fail");
  var negative=t.Select((v,i)=>Compose(reference[i],P(.1-.02*v,0,0,0))).ToArray();
  var reverse=RelativeMotion.DriveAudit(negative,reference,axis,point,"linear",20,1);C((string)reverse["status"]=="pass"&&Convert.ToDouble(reverse["observed_signed"])<0);C(!(bool)reverse["direction_verified"]);
  var ref3=t.Select(v=>X(.5*v)).ToArray();var rotary=t.Select((v,i)=>Compose(ref3[i],P(.1,0,0,.4*v))).ToArray();
  var ra=RelativeMotion.DriveAudit(rotary,ref3,new[]{0.0,0,1},new double[3],"rotary",.4*30/Math.PI,1);C((string)ra["status"]=="pass");C(Math.Abs(Convert.ToDouble(ra["observed_signed"])-.4*30/Math.PI)<1e-8);
  C((string)RelativeMotion.DriveAudit(rotary,null,new[]{0.0,0,1},new double[3],"rotary",.4*30/Math.PI,1)["status"]=="inconclusive");
  Reject(()=>RelativeMotion.Samples(moving,reference.Take(2).ToArray(),point));
  var scaled=P(0,0,0,0);scaled[12]=2;Reject(()=>RelativeMotion.InReference(scaled,RelativeMotion.Identity(),point));
  Reject(()=>RelativeMotion.Unit(new[]{double.NaN,0,1}));
  var nonuniform=new[]{P(0,0,0,0),P(.002,0,0,0),P(.02,0,0,0)};
  C((string)RelativeMotion.DriveAudit(nonuniform,null,axis,new double[3],"linear",20,1)["status"]=="fail");
  var bad=P(0,0,0,0);bad[0]=.9;Reject(()=>RelativeMotion.InReference(bad,RelativeMotion.Identity(),point));
  Console.WriteLine(n);
 }
}''',encoding='utf-8')
    exe=folder/'Probe.exe'
    subprocess.run([str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/out:'+str(exe),str(ROOT/'executor/RelativeMotion.cs'),str(ROOT/'executor/MotionIntent.cs'),str(source)],check=True)
    count=int(subprocess.check_output([str(exe)],text=True).strip())
    report={'all_passed':True,'checks':count,'production_evaluator':True,'cad_connection_used':False}
    (ROOT/'runs/relative-motion-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main()
