"""Calibrated adapter admission; not a SolidWorks-wide minimum frame claim."""
import math

MINIMUM_INTERVALS = 10
ERROR_CODE = "OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER"


class GridAdmissionError(ValueError):
    """Expected admission refusal; the transport must expose its diagnostics."""

    def __init__(self, duration, fps):
        ratio = MINIMUM_INTERVALS / duration
        minimum_fps = math.ceil(ratio - 1e-8) if math.isfinite(ratio) else None
        self.code = ERROR_CODE
        self.diagnostics = {
            "requested_duration_s": duration, "requested_output_fps": fps,
            "requested_intervals": round(duration * fps),
            "minimum_output_intervals": MINIMUM_INTERVALS,
            "minimum_output_frames": MINIMUM_INTERVALS + 1,
            "policy_scope": "MCP_SW2026_revision_34_calibrated_admission_not_universal_SOLIDWORKS_minimum",
            "minimum_duration_at_requested_fps_s": MINIMUM_INTERVALS / fps,
            "minimum_fps_at_requested_duration": minimum_fps,
            "minimum_fps_within_supported_range": minimum_fps is not None and minimum_fps <= 120,
            "maximum_supported_output_fps": 120,
            "automatic_duration_or_fps_change": False,
            "example": {"duration_s": .1, "output_fps": 100, "frames": 11},
            "cad_dispatched": False, "job_created": False,
        }
        # Keep exact aligned floating-point arguments in the structured options;
        # a rounded textual value such as .334 at 30fps would fail alignment.
        self.alternatives = [(MINIMUM_INTERVALS / fps, fps)]
        for candidate in range(5, 121):
            intervals = duration * candidate
            if intervals >= MINIMUM_INTERVALS - 1e-8 and abs(intervals - round(intervals)) <= 1e-8:
                self.alternatives.append((duration, candidate))
                break
        super().__init__(
            f"{ERROR_CODE}：请求 {duration:g}s × {fps}fps 只有 {round(duration*fps)} 个间隔；"
            "当前 SW2026 适配要求至少10个间隔（11帧）。"
            "请显式选择 next_action.options 中对齐输出帧的参数，例如0.1s/100fps。"
            "这是本MCP的实测准入范围，并非SolidWorks统一126帧下限；未派发CAD，不自动改参。")


def require_grid(duration, fps):
    if duration * fps < MINIMUM_INTERVALS - 1e-8:
        raise GridAdmissionError(duration, fps)
