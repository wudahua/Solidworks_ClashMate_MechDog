using System;

// Adapter admission based on SW2026 revision 34.0.0 tests, NOT a vendor-wide minimum.
public static class NativeOutputGridPolicy {
    public const int MinimumIntervals=10;
    public static bool Allows(double duration,int fps){return !double.IsNaN(duration)&&!double.IsInfinity(duration)&&duration>0&&fps>=5&&fps<=120&&duration*fps>=MinimumIntervals-1e-8;}
    public static int? MinimumAlignedFps(double duration){if(double.IsNaN(duration)||double.IsInfinity(duration)||duration<=0)return null;for(int f=5;f<=120;f++){double intervals=duration*f;if(intervals>=MinimumIntervals-1e-8&&Math.Abs(intervals-Math.Round(intervals))<=1e-8)return f;}return null;}
    public static object Describe(double duration,int fps){int? aligned=MinimumAlignedFps(duration);double lower=duration>0?Math.Ceiling(MinimumIntervals/duration-1e-8):double.PositiveInfinity;return new{requested_duration_s=duration,requested_output_fps=fps,requested_intervals=duration*fps,nearest_integer_intervals=Math.Round(duration*fps),minimum_output_intervals=MinimumIntervals,minimum_output_frames=MinimumIntervals+1,policy_scope="MCP_SW2026_revision_34_calibrated_admission_not_universal_SOLIDWORKS_minimum",minimum_duration_at_requested_fps_s=(double)MinimumIntervals/fps,minimum_fps_at_requested_duration=aligned,minimum_fps_within_supported_range=aligned.HasValue,minimum_fps_interval_only=double.IsNaN(lower)||double.IsInfinity(lower)?(double?)null:lower,minimum_fps_interval_only_scope="lower_bound_ignores_frame_alignment_not_a_callable_suggestion",maximum_supported_output_fps=120,automatic_duration_or_fps_change=false,example_kind="grid_values_only",example_scope="grid_values_only_not_tool_arguments",example=new{duration_s=.1,output_fps=100,frames=11}};}
}
