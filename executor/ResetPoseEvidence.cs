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
        return result;
    }
    public static string[] WarningCodes(object evidence){
        var d=(Dictionary<string,object>)evidence;
        return Convert.ToBoolean(d["cached_memory_matches_reopened_file"])?new string[0]:new[]{"RESET_CACHED_MEMORY_POSE_DEVIATION_SUPERSEDED_BY_VERIFIED_REOPEN"};
    }
}
