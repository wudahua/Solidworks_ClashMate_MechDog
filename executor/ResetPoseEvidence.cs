using System;
using System.Collections.Generic;

public static class ResetPoseEvidence {
    public static object CachedDeviation(Dictionary<string,object> difference){
        bool matches=Convert.ToBoolean(difference["within_pose_tolerance"]);
        var result=new Dictionary<string,object>(difference);
        result.Remove("within_pose_tolerance");
        result["cached_memory_matches_reopened_file"]=matches;
        result["comparison"]="post_save_cached_memory_vs_reopened_saved_live_document";
        result["disposition"]=matches?"matched":"cached_pose_superseded_by_reopened_document_requires_final_live_and_checkpoint_proof";
        result["mechanical_cause"]="not_proven";
        result["not_a_zero_pose_oracle"]=true;
        result["comparison_translation_tolerance_m"]=PoseValidation.TranslationToleranceM;
        result["comparison_rotation_tolerance_rad"]=PoseValidation.RotationToleranceRad;
        result["subsequent_baseline_policy"]="use_verified_reopened_live_state_and_its_checkpoint_not_superseded_cached_memory";
        double translation=Convert.ToDouble(difference["maximum_translation_m"])/PoseValidation.TranslationToleranceM;
        double rotation=Convert.ToDouble(difference["maximum_rotation_rad"])/PoseValidation.RotationToleranceRad;
        result["translation_tolerance_ratio"]=translation;result["rotation_tolerance_ratio"]=rotation;
        result["severity"]=matches?"info":Math.Max(translation,rotation)>=1000?"high_warning":"warning";
        result["severity_policy"]=new{high_warning_ratio=1000,scope="observation_triage_only_not_mechanical_acceptance_or_write_permission",does_not_override_final_live_or_checkpoint_proof=true};
        result["subsequent_baseline_impact"]="superseded_cache_not_used_for_preview_pose_budget; reopened_live_baseline_requires_new_preview; clearance_interference_and_mechanical_zero_not_certified";
        return result;
    }
    public static string[] WarningCodes(object evidence){
        var d=(Dictionary<string,object>)evidence;
        if(Convert.ToBoolean(d["cached_memory_matches_reopened_file"]))return new string[0];
        return (string)d["severity"]=="high_warning"?new[]{"RESET_CACHED_MEMORY_POSE_DEVIATION_SUPERSEDED_BY_VERIFIED_REOPEN","RESET_CACHED_MEMORY_POSE_DEVIATION_HIGH_MAGNITUDE"}:new[]{"RESET_CACHED_MEMORY_POSE_DEVIATION_SUPERSEDED_BY_VERIFIED_REOPEN"};
    }
}
