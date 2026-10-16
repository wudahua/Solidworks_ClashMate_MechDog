using System;

public static class MotionBudgets {
    public static bool ProbeAllows(double seconds,int fps) {
        return !double.IsNaN(seconds)&&!double.IsInfinity(seconds)&&seconds>0&&seconds<=5&&fps>=5&&fps<=120&&Math.Abs(seconds*fps-Math.Round(seconds*fps))<=1e-8&&Math.Round(seconds*fps)+1<=601;
    }
    public static object Describe() {
        return new{new_solve=new{maximum_duration_s=30,maximum_output_fps=120,maximum_frames=1801},motion_verification=new{maximum_duration_s=5,maximum_output_fps=120,maximum_frames=601},compatibility_probe=new{default_duration_s=1,maximum_duration_s=5,maximum_output_fps=120,maximum_frames=601,explicit_extension_required=true},existing_cache_reset=new{maximum_duration_s=30,maximum_output_fps=1000,maximum_frames=1801},claim="admission_limits_not_native_success_or_elapsed_time_guarantees"};
    }
}
