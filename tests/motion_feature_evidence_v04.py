"""Check production enumeration semantics; no CAD connection."""
import json
import os
import subprocess
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'runs/feature-tests'/uuid.uuid4().hex[:8]
folder.mkdir(parents=True)
source=folder/'Probe.cs'
source.write_text('''using System;
class Probe {
 static void Main(){
  if(MotionFeatureEvidence.Status("native_null",false)!="native_null_study_inactive")throw new Exception("inactive");
  if(MotionFeatureEvidence.Status("native_null",true)!="native_null_study_active")throw new Exception("active null");
  if(MotionFeatureEvidence.Status("enumerated",false)!="enumerated")throw new Exception("inactive enumeration remains observable");
  if(MotionFeatureEvidence.Status("com_enumeration_failed",true)!="com_enumeration_failed")throw new Exception("error retained");
  if(MotionFeatureEvidence.Presence("enumerated",0)!="unknown")throw new Exception("empty not absence");
  if(MotionFeatureEvidence.Presence("native_null",0)!="unknown")throw new Exception("null not absence");
  if(MotionFeatureEvidence.Presence("enumerated",1)!="features_observed")throw new Exception("positive observation");
  Console.WriteLine("7");
 }
}''',encoding='utf-8')
exe=folder/'Probe.exe'
subprocess.run([str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/platform:x64','/out:'+str(exe),str(ROOT/'executor/MotionFeatureEvidence.cs'),str(source)],check=True)
subprocess.run([str(exe)],check=True)
report={'all_passed':True,'checks':7,'cad_connection_used':False}
(ROOT/'runs/motion-feature-evidence-v04.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
