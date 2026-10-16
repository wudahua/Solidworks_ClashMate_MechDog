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
        return new Dictionary<string,object>{{"accepted",scope&&exceeded==0},{"component_scope_verified",scope},{"checked_component_count",before.Count},{"changed_component_count",changed},{"changed_component_count_total",changed},{"changed_count_semantics","all_components_above_pose_comparison_tolerance_independent_of_confirmed_budget"},{"exceeded_component_count",exceeded},{"maximum_translation_mm",translation},{"maximum_rotation_deg",rotation},{"allowed_translation_mm",mm},{"allowed_rotation_deg",deg},{"exceeded_components",rows.ToArray()},{"components_truncated",exceeded>rows.Count},{"scope","all_component_origins_and_orientations_before_native_add_to_before_commit"},{"claim","movement_budget_only_not_motion_or_design_intent_proof"}};
    }
    public static object RepreviewGuidance(string error,object diagnostics) {
        var audit=diagnostics as Dictionary<string,object>;
        bool budget=error=="MATE_POSE_CHANGE_EXCEEDS_CONFIRMED_BUDGET";
        bool measured=budget&&audit!=null&&audit.ContainsKey("component_scope_verified")&&(bool)audit["component_scope_verified"];
        return new{failure_category=budget?"confirmed_movement_budget_exceeded":"native_or_transaction_failure",re_preview_with_explicit_budget_allowed=measured,required_tool=measured?"preview_mate":null,diagnostic_tools=measured?new[]{"preview_mate"}:new[]{"inspect_model","list_mate_references"},change_budget_requires_new_preview=true,automatic_budget_expansion=false,observed_not_recommended_translation_mm=measured?audit["maximum_translation_mm"]:null,observed_not_recommended_rotation_deg=measured?audit["maximum_rotation_deg"]:null,budget_parameters=new[]{"maximum_translation_mm","maximum_rotation_deg"},next_action=measured?"designer_review_observed_movement_then_choose_explicit_limits_and_confirm_new_plan":"inspect_original_failure_before_new_plan",claim="observed_motion_is_not_proof_of_design_intent_or_recommended_budget"};
    }
}
