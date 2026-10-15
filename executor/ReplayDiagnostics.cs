using System;
using System.Linq;
using System.Text;
using System.Collections.Generic;

public static class ReplayDiagnostics {
    public static Dictionary<string,object>[] Rows(Dictionary<string,double[]> expected,Dictionary<string,double[]> actual) {
        if(!expected.Keys.OrderBy(v=>v,StringComparer.Ordinal).SequenceEqual(actual.Keys.OrderBy(v=>v,StringComparer.Ordinal)))throw new Exception("COMPONENT_SCOPE_CHANGED");
        return actual.Select(p=>{
            var a=expected[p.Key];var b=p.Value;
            if(a==null||b==null||a.Length<12||b.Length<12||a.Concat(b).Any(v=>double.IsNaN(v)||double.IsInfinity(v)))throw new Exception("NONFINITE_SOLVER_POSE");
            double translation=PoseValidation.TranslationDistance(a,b),rotation=PoseValidation.RotationDistance(a,b);
            return new Dictionary<string,object>{{"instance",p.Key},{"translation_m",translation},{"rotation_rad",rotation},{"rotation_coefficient_delta",Enumerable.Range(0,9).Max(k=>Math.Abs(b[k]-a[k]))},{"severity_tolerance_ratio",Math.Max(translation/PoseValidation.TranslationToleranceM,rotation/PoseValidation.RotationToleranceRad)},{"translation_axis_delta_m",Enumerable.Range(9,3).Select(k=>b[k]-a[k]).ToArray()},{"expected_translation_m",a.Skip(9).Take(3).ToArray()},{"actual_translation_m",b.Skip(9).Take(3).ToArray()}};
        }).OrderByDescending(r=>(double)r["severity_tolerance_ratio"]).ThenBy(r=>(string)r["instance"],StringComparer.Ordinal).ToArray();
    }
    public static Dictionary<string,object>[] Bounded(Dictionary<string,object>[] rows,int limit) {
        if(limit<1||limit>100)throw new Exception("REPLAY_DIAGNOSTIC_LIMIT_INVALID");
        var result=new List<Dictionary<string,object>>();int bytes=0;
        foreach(var row in rows.Take(limit)){int size=Encoding.UTF8.GetByteCount(Cad.Json.Serialize(row))+1;if(bytes+size>12000)break;result.Add(row);bytes+=size;}
        return result.ToArray();
    }
}
