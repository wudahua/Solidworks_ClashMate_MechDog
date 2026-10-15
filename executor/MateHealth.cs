using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    object MateHealthSummary(object[] rows,string observationScope){
        var values=rows.Select(v=>Json.Deserialize<Dictionary<string,object>>(Json.Serialize(v))).ToArray();
        int unparsed=values.Count(v=>Json.Deserialize<Dictionary<string,object>[]>(Json.Serialize(v["entities"])).Any(e=>(string)e["geometry_status"]!="resolved_face"));
        return new{observation_scope=observationScope,mate_count=rows.Length,error_count=values.Count(v=>Convert.ToInt32(v["error"])!=0),geometry_unresolved_mate_count=unparsed,geometry_unresolved_does_not_imply_unreadable_health=true,claim="native_feature_health_observation_not_DOF_or_solver_compatibility"};
    }
    void RequireMateHealthAfterRebuild(object[] before,object[] after,int[] existingIds){
        var changes=MateHealthEvidence.Difference(before,after,existingIds);
        if(after.Any(v=>Convert.ToInt32(Json.Deserialize<Dictionary<string,object>>(Json.Serialize(v))["error"])!=0))
            throw new CadFault("MATE_REBUILD_FAILED","重建后观察到配合错误；列出的特征是错误落点，尚未证明唯一根因，新增操作将回滚。",changes);
    }
}
