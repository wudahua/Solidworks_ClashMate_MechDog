using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    object MateHealthSummary(object[] rows,string observationScope){
        var values=rows.Select(v=>Json.Deserialize<Dictionary<string,object>>(Json.Serialize(v))).ToArray();
        var unresolved=values.Select(v=>new{mate=v,entities=Json.Deserialize<Dictionary<string,object>[]>(Json.Serialize(v["entities"]))}).Where(v=>v.entities.Any(e=>(string)e["geometry_status"]!="resolved_face")).ToArray();
        var details=unresolved.Take(20).Select(v=>new{name=v.mate["name"],native_feature_id=v.mate["native_feature_id"],components=v.entities.Select(e=>e["instance"]).Where(n=>n!=null).Distinct().Take(8).ToArray(),unresolved_references=v.entities.Select((e,i)=>new{entity=e,index=i}).Where(e=>(string)e.entity["geometry_status"]!="resolved_face").Take(8).Select(e=>new{reference_index=e.index,reason=e.entity["geometry_status"],reference_type=e.entity.ContainsKey("reference_type_name")?e.entity["reference_type_name"]:null}).ToArray()}).ToArray();
        return new{observation_scope=observationScope,mate_count=rows.Length,error_count=values.Count(v=>Convert.ToInt32(v["error"])!=0),geometry_unresolved_mate_count=unresolved.Length,unresolved_mates=details,unresolved_mates_truncated=unresolved.Length>details.Length,unresolved_count_scope="distinct_native_mates_with_any_unresolved_reference_all_top_level_mates",scan_budget_exhausted=false,geometry_unresolved_does_not_imply_unreadable_health=true,claim="native_feature_health_observation_not_DOF_or_solver_compatibility"};
    }
    void RequireMateHealthAfterRebuild(object[] before,object[] after,int[] existingIds){
        var changes=MateHealthEvidence.Difference(before,after,existingIds);
        if(after.Any(v=>Convert.ToInt32(Json.Deserialize<Dictionary<string,object>>(Json.Serialize(v))["error"])!=0))
            throw new CadFault("MATE_REBUILD_FAILED","重建后观察到配合错误；列出的特征是错误落点，尚未证明唯一根因，新增操作将回滚。",changes);
    }
}
