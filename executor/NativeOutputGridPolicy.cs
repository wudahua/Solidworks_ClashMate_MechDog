using System;

// Adapter admission based on SW2026 revision 34.0.0 tests, NOT a vendor-wide minimum.
public static class NativeOutputGridPolicy {
    public const int MinimumIntervals=10;
    public static bool Allows(double duration,int fps){return !double.IsNaN(duration)&&!double.IsInfinity(duration)&&duration>0&&fps>=5&&fps<=120&&duration*fps>=MinimumIntervals-1e-8;}
    public static object Describe(double duration,int fps){return new{requested_duration_s=duration,requested_output_fps=fps,requested_intervals=Math.Round(duration*fps),minimum_output_intervals=MinimumIntervals,minimum_output_frames=MinimumIntervals+1,policy_scope="MCP_SW2026_revision_34_calibrated_admission_not_universal_SOLIDWORKS_minimum",minimum_duration_at_requested_fps_s=(double)MinimumIntervals/fps,minimum_fps_at_requested_duration=duration>0?(int?)Math.Ceiling(MinimumIntervals/duration-1e-8):null,maximum_supported_output_fps=120,automatic_duration_or_fps_change=false,example=new{duration_s=.1,output_fps=100,frames=11}};}
}
