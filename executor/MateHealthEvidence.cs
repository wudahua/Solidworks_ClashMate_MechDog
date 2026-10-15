using System;
using System.Linq;
using System.Collections.Generic;

public static class MateHealthEvidence {
    public static object Difference(object[] before,object[] after,int[] existingIds){
        var previous=before.Select(v=>Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(v))).ToDictionary(v=>Convert.ToInt32(v["native_feature_id"]));
        var current=after.Select(v=>Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(v))).ToArray();
        var errors=current.Where(v=>Convert.ToInt32(v["error"])!=0).ToArray();
        var newly=errors.Where(v=>!previous.ContainsKey(Convert.ToInt32(v["native_feature_id"]))||Convert.ToInt32(previous[Convert.ToInt32(v["native_feature_id"])]["error"])==0).ToArray();
        return new{before_count=before.Length,after_count=after.Length,observed_error_count=errors.Length,observed_error_features=errors.Take(8).ToArray(),new_error_features=newly.Take(8).ToArray(),existing_feature_errors=errors.Where(v=>existingIds.Contains(Convert.ToInt32(v["native_feature_id"]))).Take(8).ToArray(),new_feature_errors=errors.Where(v=>!existingIds.Contains(Convert.ToInt32(v["native_feature_id"]))).Take(8).ToArray(),diagnostic_limit=8,error_features_truncated=errors.Length>8,root_cause="not_proven_from_native_error_location",error_code_source="IFeature.GetErrorCode2_not_swAddMateError_e"};
    }
}

