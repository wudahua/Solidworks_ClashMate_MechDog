"""Calibrated adapter admission; not a SolidWorks-wide minimum frame claim."""
import math

MINIMUM_INTERVALS = 10
ERROR_CODE = "OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER"


class GridAdmissionError(ValueError):
    """Expected admission refusal; the transport must expose its diagnostics."""

    def __init__(self, duration, fps, aligned=True):
        ratio = MINIMUM_INTERVALS / duration
        minimum_fps = math.ceil(ratio - 1e-8) if math.isfinite(ratio) else None
        self.code = ERROR_CODE if aligned else "OUTPUT_GRID_NOT_FRAME_ALIGNED"
        self.diagnostics = {
            "requested_duration_s": duration, "requested_output_fps": fps,
            "requested_intervals": duration * fps, "nearest_integer_intervals": round(duration * fps),
            "minimum_output_intervals": MINIMUM_INTERVALS,
            "minimum_output_frames": MINIMUM_INTERVALS + 1,
            "policy_scope": "MCP_SW2026_revision_34_calibrated_admission_not_universal_SOLIDWORKS_minimum",
            "minimum_duration_at_requested_fps_s": MINIMUM_INTERVALS / fps,
            "minimum_fps_interval_only": minimum_fps,
            "minimum_fps_interval_only_scope": "lower_bound_ignores_frame_alignment_not_a_callable_suggestion",
            "maximum_supported_output_fps": 120,
            "automatic_duration_or_fps_change": False,
            "example": {"duration_s": .1, "output_fps": 100, "frames": 11},
            "cad_dispatched": False, "job_created": False,
        }
        # Keep exact aligned floating-point arguments in the structured options;
        # a rounded textual value such as .334 at 30fps would fail alignment.
        intervals = max(MINIMUM_INTERVALS, math.ceil(duration * fps - 1e-8))
        self.alternatives = [(intervals / fps, fps)]
        aligned_fps = None
        for candidate in range(5, 121):
            intervals = duration * candidate
            if intervals >= MINIMUM_INTERVALS - 1e-8 and abs(intervals - round(intervals)) <= 1e-8:
                self.alternatives.append((duration, candidate))
                aligned_fps = candidate
                break
        self.diagnostics['minimum_fps_at_requested_duration'] = aligned_fps
        self.diagnostics['minimum_fps_within_supported_range'] = aligned_fps is not None
        self.diagnostics['fixed_duration_status'] = 'aligned_fps_available' if aligned_fps is not None else 'no_aligned_fps_in_5_to_120_choose_adjusted_duration'
        reason = (f"只有 {round(duration*fps)} 个间隔；当前 SW2026 适配要求至少10个间隔（11帧）。" if aligned else
                  f"有 {duration*fps:g} 个间隔，时长×帧率须为整数；未按舍入后的帧数执行。")
        super().__init__(
            f"{self.code}：请求 {duration:g}s × {fps}fps {reason}"
            "请显式选择 next_action.options 中对齐输出帧的参数。"
            "这是本MCP的实测准入范围，并非SolidWorks统一126帧下限；未派发CAD，不自动改参。")


def require_grid(duration, fps):
    if abs(duration * fps - round(duration * fps)) > 1e-8:
        raise GridAdmissionError(duration, fps, aligned=False)
    if duration * fps < MINIMUM_INTERVALS - 1e-8:
        raise GridAdmissionError(duration, fps)


def recommend_exact_native_subset(duration, requested_fps, component_count, observed_rates):
    """Recommend a declared sampling grid that exactly divides known source grids.

    This is a proposal, not evidence of a future solve or permission to execute.
    """
    rates=sorted({r for r in observed_rates if type(r) is int and r>=max(5,requested_fps)})
    if not rates:return None
    candidates=[f for f in range(max(5,requested_fps),121)
                if all(r%f==0 and abs(duration*r-round(duration*r))<=1e-8 and duration*r+1<=100001 for r in rates)
                and abs(duration*f-round(duration*f))<=1e-8 and 10<=round(duration*f)<=1800
                and (round(duration*f)+1)*component_count<=100000]
    if not candidates:raise ValueError('no_exact_native_subset_within_pose_and_grid_budgets')
    fps=candidates[0]
    return {'policy':'exact_grid_or_exact_native_subset','requested_output_fps':requested_fps,
            'recommended_sampling_fps':fps,'recommendation_changed':fps!=requested_fps,
            'observed_historical_native_rates':rates,'requires_plan_confirmation':True,
            'future_native_grid_not_proven':True,'interpolation_allowed':False,
            'clock_tolerance_s':1e-7,'maximum_native_time_points':100001,
            'reason':'select_only_existing_native_times_at_integer_stride_no_interpolation_no_nearest_time_rounding'}
