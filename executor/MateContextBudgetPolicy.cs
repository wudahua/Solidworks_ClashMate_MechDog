using System;
using System.Collections.Generic;
using System.Linq;
using System.Collections;

// Caller-selected cooperative budget. No pre-enumeration to guess mate count,
// no hidden retry and no claim that a single native call can be interrupted.
public static class MateContextBudgetPolicy {
    public static bool Valid(double seconds){return !double.IsNaN(seconds)&&!double.IsInfinity(seconds)&&seconds>=1&&seconds<=30;}
    public static int Milliseconds(double seconds){if(!Valid(seconds))throw new ArgumentOutOfRangeException("mate_context_budget_s");return (int)Math.Round(seconds*1000);}
    public static double? Next(double seconds){Milliseconds(seconds);return seconds<30?(double?)Math.Min(30,seconds*2):null;}
    public static void Apply(Dictionary<string,object> response,bool complete,bool exhausted,string tool,Dictionary<string,object> arguments,double seconds){
        Milliseconds(seconds);
        response["mate_context_complete"]=complete;response["mate_context_scope"]="current_query_candidate_components_not_full_model_geometry_or_DOF";
        response["mate_context_warning"]=complete?null:"配合关联诊断不完整；实体清单仅供几何参考，不能据此推断没有配合或自由轴。";
        response["mate_context_next_query"]=null;
        var reasons=new List<string>();object raw;
        if(!complete){
            if(exhausted)reasons.Add("budget_exhausted");
            var context=response.TryGetValue("mate_context_scan",out raw)?raw as Dictionary<string,object>:null;
            if(context!=null){
                if(context.ContainsKey("feature_limit_exhausted")&&Convert.ToBoolean(context["feature_limit_exhausted"]))reasons.Add("feature_limit_exhausted");
                if(context.ContainsKey("scan_attempted")&&!Convert.ToBoolean(context["scan_attempted"]))reasons.Add("no_candidate_scope");
                if(context.ContainsKey("unresolved_reference_count")&&Convert.ToInt32(context["unresolved_reference_count"])>0){
                    var issues=context.ContainsKey("unresolved_references")?context["unresolved_references"] as IEnumerable:null;bool unsupported=false,other=false;
                    if(issues!=null)foreach(var item in issues){var row=item as Dictionary<string,object>;object cause;if(row!=null&&row.TryGetValue("cause",out cause)&&(string)cause=="unsupported_kind")unsupported=true;else other=true;}
                    if(unsupported)reasons.Add("unsupported_reference_kind");if(other||!unsupported)reasons.Add("reference_unresolved");
                }
            }
            if(reasons.Count==0)reasons.Add("enumeration_or_reference_incomplete");
        }
        response["mate_context_incomplete_reasons"]=reasons.ToArray();response["mate_context_incomplete_reason"]=reasons.Count==0?null:reasons.Count==1?reasons[0]:"multiple_causes";
        if(!exhausted||!Next(seconds).HasValue)return;
        var next=new Dictionary<string,object>(arguments);next["cursor"]="";next["mate_context_budget_s"]=Next(seconds).Value;next["wait_for_completion"]=false;
        response["mate_context_next_query"]=new{tool=tool,arguments=next,automatic_retry=false,mode="explicit_new_scan_from_start_not_continuation_or_merged_proof",preserve_geometry_pending_queue=true,maximum_budget_s=30};
    }
}
