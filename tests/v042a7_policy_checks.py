"""Pure production diagnostic policy tests; no CAD is started or connected."""
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT/'runs/v042a7-policy'/uuid.uuid4().hex[:8]; folder.mkdir(parents=True)
    source = folder/'Checks.cs'
    source.write_text(r'''
using System;using System.Linq;using System.Collections.Generic;using System.Web.Script.Serialization;
class Checks {
 static int count;static JavaScriptSerializer json=new JavaScriptSerializer();
 static Dictionary<string,object> D(object o){return json.Deserialize<Dictionary<string,object>>(json.Serialize(o));}
 static void Check(bool b){count++;if(!b)throw new Exception("check "+count);}
 static int Main(){try{
 foreach(double duration in new[]{.001,.01,.05,.09,.1,.11,.14,.19,.2,.3,1.0/3,.4,.5,.9,1,1.01,2}){
 var possible=Enumerable.Range(5,116).Where(f=>duration*f>=10-1e-8&&Math.Abs(duration*f-Math.Round(duration*f))<=1e-8).ToArray();int? actual=NativeOutputGridPolicy.MinimumAlignedFps(duration);Check(actual==(possible.Length==0?(int?)null:possible.First()));var diag=D(NativeOutputGridPolicy.Describe(duration,30));Check((bool)diag["minimum_fps_within_supported_range"]==actual.HasValue);}
 Check(NativeOutputGridPolicy.MinimumAlignedFps(.09)==null);Check(NativeOutputGridPolicy.MinimumAlignedFps(.14)==100);
 foreach(double ratio in new[]{0,1.1,999,1000,24495}){
 bool matched=ratio<=1;var e=D(ResetPoseEvidence.CachedDeviation(new Dictionary<string,object>{{"within_pose_tolerance",matched},{"maximum_translation_m",ratio*PoseValidation.TranslationToleranceM},{"maximum_rotation_rad",0}}));Check(Math.Abs(Convert.ToDouble(e["translation_tolerance_ratio"])-ratio)<1e-8);Check((string)e["severity"]==(matched?"info":ratio>=1000?"high_warning":"warning"));Check(ResetPoseEvidence.WarningCodes(e).Length==(matched?0:ratio>=1000?2:1));Check((string)e["mechanical_cause"]=="not_proven");}
 var profile=new Dictionary<string,object>();var order=new List<string>();SolverTimeCapture.Select(0,0,0,()=>{order.Add("set");return true;},()=>{order.Add("clock");return 0;},()=>{order.Add("playing");return false;},()=>order.Add("stop"),()=>order.Add("pump"),()=>order.Add("activate"),profile);
 Check(string.Join(",",order)=="activate,stop,clock,set,pump,stop,pump,clock,playing");Check((int)profile["attempts"]==1);Check(profile.ContainsKey("set_time_ms")&&profile.ContainsKey("pump_after_select_ms")&&profile.ContainsKey("activate_scope_ms"));
 var summary=D(SamplingPerformance.Summary(new[]{new Dictionary<string,object>{{"set_time_ms",20.0},{"activate_scope_ms",10.0}}},new[]{new Dictionary<string,object>{{"get_total_transform_ms",30.0},{"names_ms",15.0},{"inventory_ms",5.0}}},100,2));Check((string)summary["dominant_measured_stage"]=="pose_read.get_total_transform_ms");Check(Convert.ToDouble(summary["mean_frame_ms"])==50);Check(Convert.ToDouble(summary["unattributed_elapsed_ms"])==20);Check((bool)summary["complete_component_checks_preserved"]);
 foreach(bool success in new[]{false,true}){var worker=D(ProbeWorkerSummary.Project(new Dictionary<string,object>{{"success",success},{"worker_exit_code",success?0:1},{"native_exit_code",success?1:0}},"record","sha"));Check((int)worker["worker_exit_code"]==(success?0:1));Check((int)worker["native_exit_code"]==(success?1:0));Check((bool)worker["missing_fields_are_unknown_not_derived_from_other_exit_code"]);}var legacy=D(ProbeWorkerSummary.Project(new Dictionary<string,object>{{"native_exit_code",1}},"record","sha"));Check(legacy["worker_exit_code"]==null);Console.WriteLine(count);return 0;}catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
''', encoding='utf-8', newline='\n')
    compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'; exe=folder/'Checks.exe'
    subprocess.run([str(compiler), '/nologo', '/reference:System.Web.Extensions.dll', '/out:'+str(exe)] +
                   [str(ROOT/'executor'/n) for n in ('CadFault.cs','ProbeWorkerSummary.cs','SolverTimeCapture.cs','SamplingPerformance.cs','ResetPoseEvidence.cs','PoseValidation.cs','NativeOutputGridPolicy.cs')] + [str(source)], check=True)
    count=int(subprocess.check_output([str(exe)],text=True).strip());result={'all_passed':True,'checks':count,'cad_connection_used':False}
    (folder/'result.json').write_text(json.dumps(result),encoding='utf-8');print(json.dumps(result))


if __name__ == '__main__': main()
