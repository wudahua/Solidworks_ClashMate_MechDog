"""Compare production evaluator to independent row-basis cross-products; no CAD."""
import json
import os
import subprocess
import uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT/'runs/axis-convention'/uuid.uuid4().hex[:8]; folder.mkdir(parents=True)
    source = folder/'AxisCheck.cs'
    source.write_text(r'''using System;using System.Linq;
class AxisCheck {
 static double[] R(int axis,double theta){var p=RelativeMotion.Identity();double c=Math.Cos(theta),s=Math.Sin(theta);int a=(axis+1)%3,b=(axis+2)%3;p[3*a+a]=c;p[3*a+b]=s;p[3*b+a]=-s;p[3*b+b]=c;return p;}
 static double[] M(double[] a,double[] b){var p=RelativeMotion.Identity();for(int i=0;i<3;i++)for(int j=0;j<3;j++)p[3*i+j]=Enumerable.Range(0,3).Sum(k=>a[3*i+k]*b[3*k+j]);return p;}
 static double[] BasisCross(double[] a,double[] b){return Enumerable.Range(0,3).Select(j=>Enumerable.Range(0,3).Sum(i=>a[3*i+(j+1)%3]*b[3*i+(j+2)%3]-a[3*i+(j+2)%3]*b[3*i+(j+1)%3])).ToArray();}
 static int Main(){int n=0;foreach(int axis in new[]{0,1,2})foreach(double sign in new[]{-1.0,1.0})foreach(double tilt in new[]{0.0,Math.PI/2,.41}){
 var poses=Enumerable.Range(0,31).Select(i=>M(R((axis+1)%3,tilt),R(axis,sign*i*.01))).ToArray();var declared=new double[3];declared[axis]=1;
 var result=MotionIntent.Evaluate(poses,declared,"rotary",10);double signed=Convert.ToDouble(result["signed_net_travel"]),off=Convert.ToDouble(result["off_axis_travel"]);
 if((string)result["assertion"]!="pass"||Math.Abs(signed-sign*.3*180/Math.PI)>1e-9||off>1e-8)throw new Exception("pose convention failed");
 double independent=0;for(int i=1;i<poses.Length;i++){var cross=BasisCross(poses[i-1],poses[i]);independent+=cross[axis]*(.01/(2*Math.Sin(.01)))*180/Math.PI;}
 if(Math.Abs(independent-signed)>1e-9)throw new Exception("independent basis disagreement");n++;
 var wrong=new double[3];wrong[(axis+1)%3]=1;if((string)MotionIntent.Evaluate(poses,wrong,"rotary",1)["assertion"]!="fail")throw new Exception("wrong axis certified");n++;
 }Console.WriteLine(n);return 0;}
}''', encoding='utf-8', newline='\n')
    exe = folder/'AxisCheck.exe'
    subprocess.run([str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'), '/nologo', '/out:'+str(exe), str(ROOT/'executor/MotionIntent.cs'), str(ROOT/'executor/RelativeMotion.cs'), str(source)], check=True)
    count = int(subprocess.check_output([str(exe)], text=True).strip())
    result = {'all_passed': True, 'checks': count, 'cad_connection_used': False, 'method': 'independent_previous_basis_cross_current_basis'}
    (folder/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8', newline='\n'); print(json.dumps(result))


if __name__ == '__main__':
    main()
