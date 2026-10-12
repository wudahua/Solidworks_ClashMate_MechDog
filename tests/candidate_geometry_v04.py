"""Compile and exercise the production geometry grouper and rigid-pose tolerances; no CAD connection."""
import json,os,subprocess,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'runs/geometry'/uuid.uuid4().hex[:8]
folder.mkdir(parents=True)
source=folder/'Probe.cs'
source.write_text('''using System;
class Probe {
 static int Main(){
  string a=CandidateGeometry.Key("a","cylindrical_axis",new[]{0.0,1.0,0.0},new[]{0.0,0.0,0.0});
  if(a!=CandidateGeometry.Key("a","cylindrical_axis",new[]{0.0,-1.0,0.0},new[]{0.0,5.0,0.0}))return 1;
  if(a==CandidateGeometry.Key("a","cylindrical_axis",new[]{0.0,1.0,0.0},new[]{0.001,0.0,0.0}))return 2;
  if(a==CandidateGeometry.Key("b","cylindrical_axis",new[]{0.0,1.0,0.0},new[]{0.0,0.0,0.0}))return 3;
  string p=CandidateGeometry.Key("a","planar_normal",new[]{0.0,1.0,0.0},new[]{0.0,0.0,0.0});
  if(p!=CandidateGeometry.Key("a","planar_normal",new[]{0.0,-1.0,0.0},new[]{5.0,0.0,2.0}))return 4;
  if(p==CandidateGeometry.Key("a","planar_normal",new[]{0.0,1.0,0.0},new[]{0.0,0.001,0.0}))return 5;
  try{CandidateGeometry.Key("a","cylindrical_axis",new[]{0.0,0.0,0.0},new[]{0.0,0.0,0.0});return 6;}catch(ArgumentException){}
  var pose=new[]{1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0};
  var tiny=(double[])pose.Clone();double t=5e-7;tiny[0]=Math.Cos(t);tiny[2]=Math.Sin(t);tiny[6]=-Math.Sin(t);tiny[8]=Math.Cos(t);
  if(!PoseValidation.Matches(pose,tiny)||Math.Abs(PoseValidation.RotationDistance(pose,tiny)-t)>1e-12)return 7;
  var large=(double[])pose.Clone();large[9]=2e-7;if(PoseValidation.Matches(pose,large))return 8;
  t=2e-6;tiny[0]=Math.Cos(t);tiny[2]=Math.Sin(t);tiny[6]=-Math.Sin(t);tiny[8]=Math.Cos(t);if(PoseValidation.Matches(pose,tiny))return 9;
  tiny[0]=double.NaN;if(PoseValidation.Matches(pose,tiny))return 10;
  Console.WriteLine("geometry and pose invariants PASS");return 0;
 }
}''',encoding='utf-8')
exe=folder/'Probe.exe'
csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
subprocess.run([str(csc),'/nologo','/platform:x64','/out:'+str(exe),str(ROOT/'executor/CandidateGeometry.cs'),str(ROOT/'executor/PoseValidation.cs'),str(source)],check=True)
subprocess.run([str(exe)],check=True)
(ROOT/'runs/candidate-geometry-v04.json').write_text(json.dumps({'all_passed':True,'checks':10,'geometry_checks':6,'pose_checks':4,'source':['executor/CandidateGeometry.cs','executor/PoseValidation.cs'],'no_cad_connection':True},indent=2),encoding='utf-8')
