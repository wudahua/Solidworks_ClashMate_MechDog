using System;

// Rehydrate existing caches at their recorded settings, separately from new solve admission.
public static class StudyCacheBudget {
    public static bool Allows(double duration,int fps) {
        return !double.IsNaN(duration)&&!double.IsInfinity(duration)&&duration>0&&duration<=30&&fps>=1&&fps<=1000&&Math.Ceiling(duration*fps-1e-8)+1<=1801;
    }
    public static object Describe(double duration,int fps) {
        return new{scope="existing_study_reset_and_checkpoint_cache_only",recalculation_with_original_settings_allowed=Allows(duration,fps),duration_s=duration,output_fps=fps,maximum_duration_s=30,maximum_output_fps=1000,maximum_frames=1801,settings_changed_automatically=false,new_motion_solve_maximum_output_fps=120,claim="admission_budget_not_native_solve_success_or_time_guarantee"};
    }
    public static object ResetGuidance(string name,double duration,int fps,int type,bool active) {
        bool calculate=Allows(duration,fps),cached=active&&type!=1;
        bool branch=(type==1||type==4)&&Allows(duration,30);
        return new{study=name,budget=Describe(duration,fps),direct_cache_attempt_allowed=cached,legacy_arguments_status=calculate||cached?"in_place_option_not_guaranteed":"unavailable_use_new_model_reset_option_arguments",arguments=calculate||cached?(object)new{study=name,allow_recalculate=calculate}:null,action=calculate?"explicit_reset_then_new_preview":cached?"cached_time_selection_only_or_explicit_checkpoint_new_model":branch?"explicit_checkpoint_then_reset_in_new_model":"designer_prepare_initial_state_in_owned_copy",new_model_reset_option=branch?(object)new{tool="reset_study_time",arguments=new{study=name,allow_recalculate=true,reset_output_fps=30,create_new_model=true},required_first_tool="create_model_checkpoint",checkpoint_id_source="successful_explicit_create_model_checkpoint_response",checkpoint_id_required=true,checkpoint_id_placeholder_is_not_callable=true,original_model_preserved=true,new_model_requires_new_queries=true,target_budget=Describe(duration,30)}:null,reset_success_guaranteed=false};
    }
}
