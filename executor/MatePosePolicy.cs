using System;
using System.Linq;
using System.Collections.Generic;

// A plan-bound movement budget, independent of native mate health.
public static class MatePosePolicy {
    public static void Validate(double mm,double deg) {
        if(double.IsNaN(mm)||double.IsInfinity(mm)||mm<0||mm>10000||double.IsNaN(deg)||double.IsInfinity(deg)||deg<0||deg>180)
            throw new CadFault("INVALID_MATE_POSE_BUDGET","配合位姿预算须为有限数：平移0–10000mm、旋转0–180度。");
    }
    public static Dictionary<string,object> Evaluate(Dictionary<string,double[]> before,Dictionary<string,double[]> after,double mm,double deg) {
        Validate(mm,deg);bool scope=before.Count>0&&before.Keys.OrderBy(x=>x).SequenceEqual(after.Keys.OrderBy(x=>x));
        var rows=new List<object>();double translation=0,rotation=0;int changed=0,exceeded=0;
        if(scope)foreach(string name in before.Keys.OrderBy(x=>x)) {
            var a=before[name];var b=after[name];if(a==null||b==null||a.Length<12||b.Length<12||a.Concat(b).Any(x=>double.IsNaN(x)||double.IsInfinity(x))){scope=false;continue;}
            double t=PoseValidation.TranslationDistance(a,b)*1000,r=PoseValidation.RotationDistance(a,b)*180/Math.PI;translation=Math.Max(translation,t);rotation=Math.Max(rotation,r);
            if(t>PoseValidation.TranslationToleranceM*1000||r>PoseValidation.RotationToleranceRad*180/Math.PI)changed++;
            if(t>mm+1e-7||r>deg+1e-7){exceeded++;if(rows.Count<20)rows.Add(new{instance=name,translation_mm=t,rotation_deg=r});}
        }
        return new Dictionary<string,object>{{"accepted",scope&&exceeded==0},{"component_scope_verified",scope},{"checked_component_count",before.Count},{"changed_component_count",changed},{"exceeded_component_count",exceeded},{"maximum_translation_mm",translation},{"maximum_rotation_deg",rotation},{"allowed_translation_mm",mm},{"allowed_rotation_deg",deg},{"exceeded_components",rows.ToArray()},{"components_truncated",exceeded>rows.Count},{"scope","all_component_origins_and_orientations_before_native_add_to_before_commit"},{"claim","movement_budget_only_not_motion_or_design_intent_proof"}};
    }
}
