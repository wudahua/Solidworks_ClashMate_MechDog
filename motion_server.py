"""Public motion-first MCP entry point. All edits target registered copies."""
from __future__ import annotations

import asyncio
import atexit
import json
import math
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from sw_mcp.bridge import Bridge, CadError
from sw_mcp.jobs import Jobs
from sw_mcp.artifacts import Artifacts, ArtifactError

ROOT = Path(__file__).resolve().parent
bridge = Bridge(ROOT)
jobs = Jobs(bridge, ROOT)
artifacts = Artifacts(ROOT)
atexit.register(bridge.close)
mcp = MCPServer("SolidWorks Motion", version="0.4.0-alpha.3", instructions="先 import_assembly 创建隔离副本，再 inspect_model、preflight_motion、list_motion_studies。已有 Motion Analysis 可直接求解；添加单一恒速驱动时先分页 list_drive_candidates，让用户指定组件、几何参考和方向。不得将候选几何解释为设计意图。长任务返回 job_id，get_job 不调用 COM。未知请求状态先 get_recovery_state，然后恢复该模型检查点。get_run_artifacts 和 read_run_poses 可离线读取失败任务，但不得将 inconclusive 解释为通过。reset_study_time 是显式归零操作，不能解除隔离；缺失历史 PID 时须由操作者按官方 CLI 核对，不得自动确认操作已结束。运动曲线来自求解姿态及数值导数，不证明受力或接触精度。")


def packed(data, error=False):
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))], structured_content=data, is_error=error)


async def call(operation, **params):
    try:
        return packed({"ok": True, "result": await asyncio.to_thread(bridge.request, operation, **params)})
    except CadError as exc:
        return packed({"ok": False, "error": {"code": exc.code, "message": str(exc), "restoration_status": exc.restoration_status, "document_context_restoration_status": exc.document_context_restoration_status, "diagnostics": exc.diagnostics, "assertion": "inconclusive"}}, True)


def enqueue(operation, params):
    try:
        return packed(jobs.submit(operation, params))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_environment() -> CallToolResult:
    """连接已有 SolidWorks 实例，读取版本、进程及实际支持范围。"""
    return await call("get_environment")


@mcp.tool()
async def import_assembly(path: str, configuration: str = "") -> CallToolResult:
    """复制已保存 SLDASM 和依赖、在副本重定向引用并登记。源文件有未保存修改则拒绝。异步返回 job_id。"""
    if not Path(path).is_absolute():
        raise ToolError("路径必须是绝对路径。")
    if Path(path).suffix.lower() != ".sldasm":
        raise ToolError(f"仅支持 .SLDASM 装配文件；收到 {Path(path).suffix or '无扩展名'}。")
    if not Path(path).is_file():
        raise ToolError("装配文件不存在或无法读取，请核对路径。")
    return enqueue("import_assembly", {"path": path, "configuration": configuration})


@mcp.tool()
async def list_models() -> CallToolResult:
    """列出本安装目录已登记的隔离模型；model_id 不能替换为任意路径。"""
    return await call("list_models")


@mcp.tool()
async def inspect_model(model_id: str) -> CallToolResult:
    """读取组件实例、配置和顶层配合错误。自由度状态为 unknown，需用户确认机构可运动。"""
    return await call("inspect_model", model_id=model_id)


@mcp.tool()
async def list_motion_studies(model_id: str) -> CallToolResult:
    """列出隔离模型中的原生运动算例、类型和输出设置。"""
    return await call("list_motion_studies", model_id=model_id)


@mcp.tool()
async def preflight_motion(model_id: str, study: str = "") -> CallToolResult:
    """检查副本引用、轻量化解析、重建、固定状态和不支持类型；ready 不等于自由度或物理精度证明。"""
    return await call("preflight_motion", model_id=model_id, study=study)


@mcp.tool()
async def list_drive_candidates(model_id: str, component_id: str = "", kind: Literal["", "cylindrical_axis", "planar_normal"] = "", limit: int = 20, cursor: str = "", group_faces: bool = True) -> CallToolResult:
    """分页读取几何驱动候选；默认按组件及同一轴线/平面位置分组，group_faces=False可查看逐面候选。limit 1–50；修改筛选或分组后重新查询。"""
    if not 1 <= limit <= 50:
        raise ToolError("limit 须在 1–50。")
    return await call("list_drive_candidates", model_id=model_id, component_id=component_id, kind=kind, limit=limit, cursor=cursor, group_faces=group_faces)


@mcp.tool()
async def create_motion_study(model_id: str, study: str, component_id: str, entity_id: str, motor_type: Literal["rotary", "linear"], speed: float, reverse_direction: bool = False) -> CallToolResult:
    """在副本创建单一恒速驱动。旋转单位 rpm，直线 mm/s；方向按 SolidWorks 马达箭头及反向标志。自动创建回滚检查点。"""
    limit = 6000 if motor_type == "rotary" else 500
    if not math.isfinite(speed) or not 0 < speed <= limit:
        raise ToolError(f"速度须为有限正数，最大 {limit}。")
    return await call("create_motion_study", model_id=model_id, study=study, component_id=component_id, entity_id=entity_id, motor_type=motor_type, speed=speed, reverse_direction=reverse_direction)


@mcp.tool()
async def convert_motion_study(model_id: str, study: str) -> CallToolResult:
    """显式将副本算例转换成 Motion Analysis；保留已有配合和特征，先创建检查点。"""
    return await call("convert_motion_study", model_id=model_id, study=study)


@mcp.tool()
async def run_motion_study(model_id: str, study: str, duration_s: float = 1, output_fps: int = 30) -> CallToolResult:
    """异步求解 Motion Analysis。最多30秒、1801帧、10万组件姿态；验证实际时间轴，核对新建驱动速度并恢复姿态。"""
    if not math.isfinite(duration_s) or not 0 < duration_s <= 30 or not 5 <= output_fps <= 120 or abs(duration_s*output_fps-round(duration_s*output_fps)) > 1e-8 or round(duration_s*output_fps)+1 > 1801:
        raise ToolError("时长须在 (0,30] 秒、帧率5–120并对齐输出帧，总帧数不超过1801。")
    return enqueue("run_user_study", {"model_id": model_id, "study": study, "duration_s": duration_s, "output_fps": output_fps})


@mcp.tool()
async def get_job(job_id: str) -> CallToolResult:
    """读取缓存状态和进度，不进入 COM 队列。超时后不可假定 CAD 已停止。"""
    try:
        return packed(jobs.get(job_id))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_motion_summary(run_id: str) -> CallToolResult:
    """检查结果是否过期并返回求解摘要、验证范围和文件位置。run_id 仅在当前执行器会话有效。"""
    return await call("get_motion_summary", run_id=run_id)


@mcp.tool()
async def export_motion_curve(run_id: str, component_id: str, quantity: Literal["position", "displacement", "linear_velocity", "angular_velocity"], axis: Literal["x", "y", "z", "magnitude"] = "magnitude") -> CallToolResult:
    """导出全局坐标 CSV，参考点为组件坐标原点；速度为采样姿态的数值导数，不是质心或原生瞬时速度。"""
    return await call("export_motion_curve", run_id=run_id, component_id=component_id, quantity=quantity, axis=axis)


@mcp.tool()
async def replay_motion_frame(run_id: str, frame: int) -> CallToolResult:
    """核验所选帧姿态并导出 BMP 截图，然后恢复操作前姿态。"""
    return await call("replay_motion_frame", run_id=run_id, frame=frame)


@mcp.tool()
async def create_model_checkpoint(model_id: str) -> CallToolResult:
    """快照副本全部 CAD 文件、配置、全部算例时间及激活状态和组件姿态；不自动归零。"""
    return await call("create_model_checkpoint", model_id=model_id)


@mcp.tool()
async def reset_study_time(model_id: str, study: str) -> CallToolResult:
    """显式把所选算例归零并保存副本；先建立回滚检查点，旧运行结果失效。隔离期间不允许此操作。"""
    return await call("reset_study_time", model_id=model_id, study=study)


@mcp.tool()
async def get_run_artifacts(run_id: str) -> CallToolResult:
    """离线读取保存的求解摘要，恢复失败或重启后仍可调用；不证明当前 CAD 状态或结果物理精度。"""
    try:
        return packed(await asyncio.to_thread(artifacts.summary, run_id))
    except ArtifactError as exc:
        return packed({"ok": False, "error": {"code": exc.code, "message": str(exc), "assertion": "inconclusive", "restoration_status": "not_required"}}, True)
    except (ValueError, OSError, KeyError) as exc:
        raise ToolError(str(exc) if isinstance(exc, ValueError) else "结果文件无法读取；请核对文件格式和访问权限。") from exc


@mcp.tool()
async def read_run_poses(run_id: str, component_id: str = "", frame_start: int = 0, limit: int = 20, cursor: str = "") -> CallToolResult:
    """分页读取已保存的姿态 CSV，不调用 COM；未知恢复状态下可用。数据有效性与当前模型状态分别标示。"""
    try:
        return packed(await asyncio.to_thread(artifacts.poses, run_id, component_id, frame_start, limit, cursor))
    except ArtifactError as exc:
        return packed({"ok": False, "error": {"code": exc.code, "message": str(exc), "assertion": "inconclusive", "restoration_status": "not_required"}}, True)
    except (ValueError, OSError, KeyError) as exc:
        raise ToolError(str(exc) if isinstance(exc, ValueError) else "姿态文件无法读取；请核对文件格式和访问权限。") from exc


@mcp.tool()
async def get_recovery_state() -> CallToolResult:
    """读取请求日志，不调用 COM。unknown/active 时拒绝普通 CAD 调用。"""
    return packed(bridge.recovery_state())


@mcp.tool()
async def restore_model_checkpoint(model_id: str, checkpoint_id: str, allow_replacement_session: bool = False) -> CallToolResult:
    """关闭登记副本文档、恢复全部文件并核验配置、算例与姿态；旧结果失效。旧执行器必须停止，默认绑定原 SolidWorks 进程。"""
    return await call("restore_model_checkpoint", model_id=model_id, checkpoint_id=checkpoint_id, allow_replacement_session=allow_replacement_session)


if __name__ == "__main__":
    mcp.run(transport="stdio")
