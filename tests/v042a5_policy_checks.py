"""Pure production policy regressions; never starts or connects to CAD."""
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT/'runs/v042a5-policy'/uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    source = folder/'Checks.cs'
    source.write_text(r'''
using System;using System.Linq;using System.Collections.Generic;using System.Web.Script.Serialization;
class Checks {
 static int count;static JavaScriptSerializer json=new JavaScriptSerializer();
 static Dictionary<string,object> D(object v){return json.Deserialize<Dictionary<string,object>>(json.Serialize(v));}
 static void Check(bool ok){count++;if(!ok)throw new Exception("check "+count);}
 static int Main(){try{
 var parent=new Dictionary<string,object>();GeometryQueryScope.Apply(parent,"",3,3,false,2);
 Check(!(bool)parent["geometry_complete"]);Check(!(bool)parent["model_geometry_complete"]);
 var child=new Dictionary<string,object>();GeometryQueryScope.Apply(child,"part_b",3,1,true,0);
 Check(!(bool)child["geometry_complete"]);Check((bool)child["scope_geometry_complete"]);Check(child["model_geometry_complete"]==null);
 Check((int)child["filtered_out_component_count"]==2);Check((string)child["total_scope"]=="scoped_component_observed_subset");
 Check(((string)child["client_next_action"]).Contains("retain")||((string)child["client_next_action"]).Contains("retained"));
 var contract=D(child["client_queue_contract"]);Check((bool)contract["component_result_cannot_complete_parent"]);Check(!(bool)contract["service_model_pending_ledger"]);
 var full=new Dictionary<string,object>();GeometryQueryScope.Apply(full,"",3,3,true,0);Check((bool)full["geometry_complete"]);Check((bool)full["model_geometry_complete"]);
 var unresolved=new Dictionary<string,object>();GeometryQueryScope.Apply(unresolved,"",3,3,false,0);Check(!(bool)unresolved["geometry_complete"]);Check(!(bool)unresolved["absence_of_kind_proven"]);
 var budget=new GeometryScanBudget();var scoped=D(budget.Export(new object[0],0,true));Check(scoped["pending_query_count"]==null);Check((int)scoped["scope_pending_query_count"]==0);Check((bool)scoped["component_completion_does_not_clear_siblings"]);
 var unfiltered=D(budget.Export(new object[0],2));Check((int)unfiltered["pending_query_count"]==2);
 foreach(bool matches in new[]{false,true}){var e=ResetPoseEvidence.CachedDeviation(new Dictionary<string,object>{{"within_pose_tolerance",matches},{"maximum_translation_m",matches?0:.4},{"maximum_rotation_rad",0},{"checked_component_count",15}});var d=D(e);Check(!d.ContainsKey("within_pose_tolerance"));Check((bool)d["cached_memory_matches_reopened_file"]==matches);Check(ResetPoseEvidence.WarningCodes(e).Length==(matches?0:2));Check((string)d["comparison"]=="post_save_cached_memory_vs_reopened_saved_live_document");Check(Convert.ToDouble(d["comparison_translation_tolerance_m"])==PoseValidation.TranslationToleranceM);Check(Convert.ToDouble(d["comparison_rotation_tolerance_rad"])==PoseValidation.RotationToleranceRad);Check(((string)d["subsequent_baseline_policy"]).Contains("not_superseded_cached_memory"));}
 Check(!NativeOutputGridPolicy.Allows(.1,30));Check(!NativeOutputGridPolicy.Allows(.3,30));Check(NativeOutputGridPolicy.Allows(.1,100));Check(NativeOutputGridPolicy.Allows(1.0/3,30));Check(NativeOutputGridPolicy.Allows(.5,30));Check(NativeOutputGridPolicy.Allows(.1,120));
 Console.WriteLine(count);return 0;}catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}
''', encoding='utf-8', newline='\n')
    compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    exe = folder/'Checks.exe'
    subprocess.run([str(compiler), '/nologo', '/reference:System.Web.Extensions.dll', '/out:'+str(exe)] +
                   [str(ROOT/'executor'/n) for n in ('GeometryQueryScope.cs', 'GeometryScanBudget.cs', 'ResetPoseEvidence.cs', 'PoseValidation.cs', 'NativeOutputGridPolicy.cs')] + [str(source)], check=True)
    count = int(subprocess.check_output([str(exe)], text=True).strip())
    result = {'all_passed': True, 'checks': count, 'cad_connection_used': False}
    (folder/'result.json').write_text(json.dumps(result), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__': main()
