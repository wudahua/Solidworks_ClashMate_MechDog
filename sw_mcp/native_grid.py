"""Calibrated adapter admission; not a SolidWorks-wide minimum frame claim."""
import math

MINIMUM_INTERVALS = 10


def require_grid(duration, fps):
    if duration * fps < MINIMUM_INTERVALS - 1e-8:
        raise ValueError(
            f"OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER：请求 {duration:g}s × {fps}fps "
            f"只有 {round(duration*fps)} 个间隔；当前 SW2026 适配要求至少10个间隔（11帧）。"
            f"可显式改用时长≥{MINIMUM_INTERVALS/fps:g}s，或帧率≥{math.ceil(MINIMUM_INTERVALS/duration-1e-8)}fps"
            "（仍须≤120且时长×帧率为整数）。例如0.1s/100fps。"
            "这是本MCP的实测准入范围，并非SolidWorks统一126帧下限；未派发CAD，不自动改参。")
