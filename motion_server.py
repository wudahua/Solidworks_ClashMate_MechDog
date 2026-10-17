"""Public motion-first MCP entry point. All edits target registered copies."""
from __future__ import annotations

import asyncio
import atexit
import json
import math
import re
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from sw_mcp.bridge import Bridge, CadError
from sw_mcp.jobs import Jobs
from sw_mcp.native_grid import GridAdmissionError, require_grid
from sw_mcp.artifacts import Artifacts, ArtifactError

ROOT = Path(__file__).resolve().parent
bridge = Bridge(ROOT)
jobs = Jobs(bridge, ROOT)
artifacts = Artifacts(ROOT)
atexit.register(bridge.close)
mcp = MCPServer("SolidWorks ClashMate MechDog", version="0.4.2-alpha.6", instructions="先 import_assembly 创建隔离副本，再 inspect_model、preflight_motion、list_motion_studies。已有 Motion Analysis 可直接求解；与原生驱动对比时先 list_motion_studies(inspect_native_drives=True)，核对实际组件、轴线位置、相对组件和参数，方向相同不等于同一驱动输入；添加单一恒速驱动时先分页 list_drive_candidates，让用户指定组件、几何参考和方向。两种几何查询不完整时必须读取next_cursor并按geometry_scan.next_queries续查，保留父查询兄弟待办，直到客户端队列为空；单组件scope_geometry_complete不代表模型完成；next_queries_truncated时从inspect_model组件清单查询其余组件，不能把缺席解释为无圆柱面；若仍有skipped/unresolved则报告不完整，不无限重试。不得将候选几何解释为设计意图。补配合先list_mate_references、preview_mate，用户明确确认具体方案后apply_mate；同心默认不锁旋转。verify_motion_preservation是显式试算，仅验证声明的采样运动要求。长任务返回 job_id，get_job 不调用 COM。未知请求状态先 get_recovery_state，然后恢复该模型检查点。get_run_artifacts 和 read_run_poses 可离线读取失败任务，但不得将 inconclusive 解释为通过。reset_study_time 是显式归零操作，不能解除隔离；缺失历史 PID 时须由操作者按官方 CLI 核对，不得自动确认操作已结束。运动曲线来自求解姿态及数值导数，不证明受力或接触精度。")


def packed(data, error=False):
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))], structured_content=data, is_error=error)


def grid_refusal(tool, arguments, duration_key="duration_s", fps_key="output_fps"):
    """Convert expected policy errors before the SDK masks ordinary exceptions."""
    try:
        require_grid(arguments[duration_key], arguments[fps_key])
    except GridAdmissionError as exc:
        options = [{"tool": tool, "arguments": {**arguments, duration_key: d, fps_key: f}}
                   for d, f in exc.alternatives]
        return packed({"ok": False, "error": {"code": exc.code, "message": str(exc),
            "diagnostics": {**exc.diagnostics, "model_id": arguments["model_id"]},
            "next_action": {"automatic_retry": False,
                "instruction": "请用户选择调整参数；保留原目标与其余参数，不自动创建或求解。", "options": options}}}, True)
    return None


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
async def get_environment(solidworks_pid: str = "") -> CallToolResult:
    """读取环境。可显式传正整数PID字符串或auto纠正首次连接：只允许本服务尚未派发任何CAD请求、无未知恢复且旧启动进程已结束时重新选择；不修改客户端配置，不自动换实例。"""
    if solidworks_pid:
        try:
            await asyncio.to_thread(bridge.select_startup_session, solidworks_pid)
        except CadError as exc:
            return packed({"ok": False, "error": {"code": exc.code, "message": str(exc), "restoration_status": exc.restoration_status, "diagnostics": exc.diagnostics}}, True)
    return await call("get_environment")


@mcp.tool()
async def import_assembly(path: str, configuration: str = "", materialize_virtual_components: bool = False) -> CallToolResult:
    """复制已保存SLDASM和依赖。显式materialize_virtual_components=True才允许在隔离副本外部化顶层虚拟零件；虚拟子装配、未校准配置/依赖拒绝，完整核验后登记。源文件有未保存修改拒绝。返回job_id。"""
    if not Path(path).is_absolute():
        raise ToolError("路径必须是绝对路径。")
    if Path(path).suffix.lower() != ".sldasm":
        raise ToolError(f"仅支持 .SLDASM 装配文件；收到 {Path(path).suffix or '无扩展名'}。")
    if not Path(path).is_file():
        raise ToolError("装配文件不存在或无法读取，请核对路径。")
    return enqueue("import_assembly", {"path": path, "configuration": configuration, "materialize_virtual_components": materialize_virtual_components})


@mcp.tool()
async def list_models() -> CallToolResult:
    """列出本安装目录已登记的隔离模型；model_id 不能替换为任意路径。"""
    return await call("list_models")


@mcp.tool()
async def inspect_model(model_id: str, detail_level: Literal["full", "components"] = "full", wait_for_completion: bool = True) -> CallToolResult:
    """读取组件、当前原生配合健康及几何；detail_level="components"只读组件清单、跳过配合几何，适合大装配；wait_for_completion=False异步取job_id；本次返回的受支持顶层面在核验持久引用/归属后登记，可直接用于配合或驱动。其他参考不自动改绑；不隐式重建，自由度仍unknown。"""
    params = dict(model_id=model_id, detail_level=detail_level)
    return await call("inspect_model", **params) if wait_for_completion else enqueue("inspect_model", params)


@mcp.tool()
async def list_motion_studies(model_id: str, inspect_native_drives: bool = False) -> CallToolResult:
    """列出算例、时间、登记驱动及历史。inspect_native_drives=True显式回读有预算的原生马达组件、方向/位置参考及原始参数观测，不激活或求解；全装配观测不证明算例归属。发现一个马达不证明清单完整或登记身份已匹配，空特征不代表无驱动；历史独立核对见get_run_artifacts.drive_validation。输入匹配带脏标志诊断，unknown不等于已变化。"""
    return await call("list_motion_studies", model_id=model_id, inspect_native_drives=inspect_native_drives)


@mcp.tool()
async def preflight_motion(model_id: str, study: str = "", compatibility_probe: bool = False, probe_duration_s: float = 1.0, probe_output_fps: int = 30, checkpoint_id: str = "") -> CallToolResult:
    """基础预检不保证求解相容。探测至少10个输出间隔（11帧），短网格返回OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER及next_action.options，不自动改参。显式compatibility_probe异步短算，默认1秒；显式最多5秒601帧；推荐传create_model_checkpoint返回的checkpoint_id，在独立SolidWorks实例验证该快照，不能证明当前未保存内存。原副本不隐式保存；用get_job读取结果。"""
    if compatibility_probe:
        if not study or not 0 < probe_duration_s <= 5 or not 5 <= probe_output_fps <= 120 or abs(probe_duration_s * probe_output_fps - round(probe_duration_s * probe_output_fps)) > 1e-8:
            raise ToolError("指定算例和探测预算（默认1秒，显式最多5秒、601帧，时长乘fps须为整数）。")
        refusal = grid_refusal("preflight_motion", dict(model_id=model_id, study=study, compatibility_probe=True, probe_duration_s=probe_duration_s, probe_output_fps=probe_output_fps, checkpoint_id=checkpoint_id), "probe_duration_s", "probe_output_fps")
        if refusal is not None:
            return refusal
        return enqueue("probe_motion_compatibility", {"model_id": model_id, "study": study, "duration_s": probe_duration_s, "output_fps": probe_output_fps, "checkpoint_id": checkpoint_id})
    if checkpoint_id:
        raise ToolError("checkpoint_id 仅用于 compatibility_probe=True 的快照探测。")
    return await call("preflight_motion", model_id=model_id, study=study)


@mcp.tool()
async def list_drive_candidates(model_id: str, component_id: str = "", kind: Literal["", "cylindrical_axis", "planar_normal"] = "", limit: int = 20, cursor: str = "", group_faces: bool = True, detail_level: Literal["full", "compact"] = "full", wait_for_completion: bool = True, face_offset: int = 0) -> CallToolResult:
    """几何驱动候选，不证明关节相容；几何不完整时必须按geometry_scan.next_queries保留父查询全部待办，逐组件续查直到客户端队列为空，不能用单组件scope_pending_query_count=0清空兄弟待办，并读完各页；缺席不证明没有圆柱面。wait_for_completion=False返回job_id，大装配先inspect_model(detail_level="components")再按component_id筛选；排除固定件并报告原因，容忍合法空体。默认分组，group_faces=False查看逐面；limit是1–50条上限，16KB字节预算可能缩页。compact省略冗余字段；改变筛选/分组/详情后重新分页。"""
    if not 1 <= limit <= 50:
        raise ToolError("limit 须在 1–50。")
    if face_offset < 0 or (face_offset and not component_id):
        raise ToolError("非零 face_offset 需要 component_id；修改模型后从0重新查询。")
    params = dict(model_id=model_id, component_id=component_id, kind=kind, limit=limit, cursor=cursor, group_faces=group_faces, detail_level=detail_level, face_offset=face_offset)
    return await call("list_drive_candidates", **params) if wait_for_completion else enqueue("list_drive_candidates", params)


@mcp.tool()
async def create_motion_study(model_id: str, study: str, component_id: str, entity_id: str, motor_type: Literal["rotary", "linear"], speed: float, reverse_direction: bool = False, reference_component_id: str = "", duration_s: float = 1, output_fps: int = 30, wait_for_completion: bool = False) -> CallToolResult:
    """新建算例与单一恒速马达，默认异步job_id，用get_job查询；wait_for_completion=True兼容同步。study须为新名称，不向已有算例追加。时长/fps可选默认1s/30fps；当前适配至少10个输出间隔，0.1s须≥100fps；不足时返回OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER及next_action.options，不自动改参。rotary选圆柱轴、rpm；linear选平面法向、mm/s。reference_component_id指定相对参考零件。创建不证明驱动相容，先建立检查点。"""
    limit = 6000 if motor_type == "rotary" else 500
    if not math.isfinite(speed) or not 0 < speed <= limit:
        raise ToolError(f"速度须为有限正数，最大 {limit}。")
    if not math.isfinite(duration_s) or not 0 < duration_s <= 30 or not 5 <= output_fps <= 120 or abs(duration_s*output_fps-round(duration_s*output_fps)) > 1e-8 or round(duration_s*output_fps)+1 > 1801:
        raise ToolError("创建时长须在(0,30]秒、帧率5–120并对齐输出帧，最多1801帧。")
    params = dict(model_id=model_id, study=study, component_id=component_id, entity_id=entity_id, motor_type=motor_type, speed=speed, reverse_direction=reverse_direction, reference_component_id=reference_component_id, duration_s=duration_s, output_fps=output_fps)
    refusal = grid_refusal("create_motion_study", {**params, "wait_for_completion": wait_for_completion})
    if refusal is not None:
        return refusal
    return await call("create_motion_study", **params) if wait_for_completion else enqueue("create_motion_study", params)


@mcp.tool()
async def list_mate_references(model_id: str, component_id: str = "", kind: Literal["", "cylindrical_axis", "planar_normal"] = "", limit: int = 20, cursor: str = "", detail_level: Literal["full", "compact"] = "full", wait_for_completion: bool = True, face_offset: int = 0) -> CallToolResult:
    """顶层配合面，包含固定支座；geometry_complete=false时必须按geometry_scan.next_queries保留父查询全部待办，逐组件续查至客户端队列为空，单组件scope_geometry_complete不代表全模型完成并读完各页，缺席不证明没有圆柱面；不支持边缘、顶点或草图段，不自动换成邻面；wait_for_completion=False异步取job_id；空体/异常报告原因，不推断缺失配合。每零件最多128面并报告截断；limit条数上限与16KB预算同时限制。compact提供较短结果，改变详情后重查第一页。"""
    if not 1 <= limit <= 50:
        raise ToolError("limit 须在1–50。")
    if face_offset < 0 or (face_offset and not component_id):
        raise ToolError("非零 face_offset 需要 component_id；修改模型后从0重新查询。")
    params = dict(model_id=model_id, component_id=component_id, kind=kind, limit=limit, cursor=cursor, detail_level=detail_level, face_offset=face_offset)
    return await call("list_mate_references", **params) if wait_for_completion else enqueue("list_mate_references", params)


@mcp.tool()
async def preview_mate(model_id: str, entity_a: str, entity_b: str, mate_type: Literal["concentric", "coincident", "distance", "parallel", "perpendicular"], alignment: Literal["aligned", "anti_aligned"] = "aligned", distance_mm: float = 0, lock_rotation: bool = False, baseline_run_id: str = "", maximum_translation_mm: float = 1, maximum_rotation_deg: float = 1) -> CallToolResult:
    """生成描述性配合方案，不移动零件、不保存或试算。同心选圆柱面，其余选平面。可绑定本会话当前模型的已验证运动基线。默认位姿预算1mm/1度，保护已有构型；装配对齐可能需要更大移动，请用户预先明确maximum_translation_mm/maximum_rotation_deg。仅描述预览不预测移动；超预算回滚后需新方案，原生配合成功不等于构型符合意图。方案在状态变化或重连后失效。"""
    if not math.isfinite(distance_mm) or not 0 <= distance_mm <= 10000 or (mate_type != "distance" and distance_mm != 0) or (lock_rotation and mate_type != "concentric"):
        raise ToolError("距离须在0–10000mm且仅用于距离配合；锁旋转仅适用于同心配合。")
    if not math.isfinite(maximum_translation_mm) or not 0 <= maximum_translation_mm <= 10000 or not math.isfinite(maximum_rotation_deg) or not 0 <= maximum_rotation_deg <= 180:
        raise ToolError("位姿预算须为有限数：平移0–10000mm，旋转0–180度。")
    return await call("preview_mate", model_id=model_id, entity_a=entity_a, entity_b=entity_b, mate_type=mate_type, alignment=alignment, distance_mm=distance_mm, lock_rotation=lock_rotation, baseline_run_id=baseline_run_id, maximum_translation_mm=maximum_translation_mm, maximum_rotation_deg=maximum_rotation_deg)


@mcp.tool()
async def apply_mate(plan_id: str, confirmed: bool = False, wait_for_completion: bool = False) -> CallToolResult:
    """用户确认具体方案后异步执行，返回job_id并轮询get_job；wait_for_completion=True兼容同步。默认方案预算1mm/1度，装配对齐等较大移动需在preview_mate显式选择maximum_translation_mm/maximum_rotation_deg后确认。建检查点、独立恢复预演、建配合并重建，超预算回滚后给retry_guidance；启动/插件开销不保证固定耗时。超时不重试写入，查询迟到最终响应；成功后另验运动。"""
    if not confirmed:
        raise ToolError("须由用户明确确认配合方案后传入confirmed=True。")
    if re.fullmatch(r"[0-9a-f]{32}", plan_id) is None:
        return packed({"ok": False, "error": {"code": "INVALID_MATE_PLAN_ID", "message": "配合方案标识须为32位小写十六进制；请先调用preview_mate并确认返回的具体方案。", "diagnostics": {"cad_dispatched": False, "job_created": False}, "next_action": {"tool": "preview_mate", "automatic_retry": False}}}, True)
    return await call("apply_mate", plan_id=plan_id, confirmed=confirmed) if wait_for_completion else enqueue("apply_mate", {"plan_id": plan_id, "confirmed": confirmed})


@mcp.tool()
async def verify_motion_preservation(model_id: str, study: str, component_id: str, entity_id: str, expected_motion: Literal["rotary", "linear"], minimum_travel: float, duration_s: float = 1, output_fps: int = 30, plan_id: str = "", reference_component_id: str = "") -> CallToolResult:
    """显式异步试算声明的运动要求（最低量deg/mm），至少10个输出间隔（11帧），短网格返回OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER及next_action.options，不自动改参；不是所有DOF证明。linear要求参考系中的直线平动；摆动液压杆须指定reference_component_id为缸体。返回verification_status=pass/fail/inconclusive，job succeeded只表示执行完成。指定已应用plan_id可比较基线并返回配合前检查点；独立验证返回试算前检查点。失败不自动删除新增配合。"""
    if not math.isfinite(minimum_travel) or minimum_travel <= 0:
        raise ToolError("minimum_travel须为有限正数，旋转单位deg、直线单位mm。")
    if not math.isfinite(duration_s) or not 0 < duration_s <= 5 or not 5 <= output_fps <= 120 or abs(duration_s*output_fps-round(duration_s*output_fps)) > 1e-8 or round(duration_s*output_fps)+1 > 601:
        raise ToolError("验证时长须在(0,5]秒、帧率5–120并对齐输出帧，最多601帧。")
    params = dict(model_id=model_id, study=study, component_id=component_id, entity_id=entity_id, expected_motion=expected_motion, minimum_travel=minimum_travel, duration_s=duration_s, output_fps=output_fps, plan_id=plan_id, reference_component_id=reference_component_id)
    refusal = grid_refusal("verify_motion_preservation", params)
    if refusal is not None:
        return refusal
    return enqueue("verify_motion_preservation", params)


@mcp.tool()
async def convert_motion_study(model_id: str, study: str, wait_for_completion: bool = False) -> CallToolResult:
    """显式转换副本算例为Motion Analysis，先建检查点，回读时长/fps及差异；默认异步job_id，wait_for_completion=True兼容同步。"""
    return await call("convert_motion_study", model_id=model_id, study=study) if wait_for_completion else enqueue("convert_motion_study", {"model_id": model_id, "study": study})


@mcp.tool()
async def run_motion_study(model_id: str, study: str, duration_s: float = 1, output_fps: int = 30) -> CallToolResult:
    """异步求解 Motion Analysis。至少10个输出间隔（11帧），短网格返回OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER及next_action.options，不自动改参。最多30秒、1801帧、10万组件姿态；验证实际时间轴，核对新建驱动速度并恢复姿态。"""
    if not math.isfinite(duration_s) or not 0 < duration_s <= 30 or not 5 <= output_fps <= 120 or abs(duration_s*output_fps-round(duration_s*output_fps)) > 1e-8 or round(duration_s*output_fps)+1 > 1801:
        raise ToolError("时长须在 (0,30] 秒、帧率5–120并对齐输出帧，总帧数不超过1801。")
    params = dict(model_id=model_id, study=study, duration_s=duration_s, output_fps=output_fps)
    refusal = grid_refusal("run_motion_study", params)
    if refusal is not None:
        return refusal
    return enqueue("run_user_study", params)


@mcp.tool()
async def get_job(job_id: str, response_artifact_id: str = "", offset: int = 0, limit: int = 2000, response_json_pointer: str = "") -> CallToolResult:
    """读取缓存状态/进度，不进入COM队列。超大响应保留根因链与完整控制令牌；response_artifact_id按SHA256核验完整工件；response_json_pointer可指定RFC6901子树，offset是该子树Unicode字符位置，limit为1–2000。succeeded只表示执行完成；运动是否通过看verification_status。超时后不可假定CAD已停止，恢复未确认时必须按检查点恢复。"""
    try:
        return packed(jobs.get(job_id, response_artifact_id, offset, limit, response_json_pointer))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_motion_summary(run_id: str, allow_unverified_history: bool = False) -> CallToolResult:
    """默认核验当前会话的输入匹配；显式 allow_unverified_history=True 离线读取保存摘要，支持重启和隔离状态，不证明当前模型有效或运动通过。"""
    if allow_unverified_history:
        try:
            return packed({"ok": True, "result": await asyncio.to_thread(artifacts.summary, run_id)})
        except (ArtifactError, ValueError) as exc:
            return packed({"ok": False, "error": {"code": getattr(exc, "code", "INVALID_HISTORY_SUMMARY"), "message": str(exc)}}, True)
    return await call("get_motion_summary", run_id=run_id)


@mcp.tool()
async def export_motion_curve(run_id: str, component_id: str, quantity: Literal["position", "displacement", "linear_velocity", "angular_velocity"], axis: Literal["x", "y", "z", "magnitude"] = "magnitude", allow_unverified_history: bool = False) -> CallToolResult:
    """导出全局组件原点CSV；速度是采样数值导数。默认要求当前输入匹配且结果verified。显式allow_unverified_history=True只离线导出哈希与时间轴已核验的历史采样，带状态和警示，不调用COM、不证明物理验证通过。"""
    if allow_unverified_history:
        try:
            return packed({"ok": True, "result": await asyncio.to_thread(artifacts.export_history_curve, run_id, component_id, quantity, axis)})
        except (ArtifactError, ValueError) as exc:
            return packed({"ok": False, "error": {"code": getattr(exc, "code", "INVALID_HISTORY_EXPORT"), "message": str(exc)}}, True)
    return await call("export_motion_curve", run_id=run_id, component_id=component_id, quantity=quantity, axis=axis)


@mcp.tool()
async def replay_motion_frame(run_id: str, frame: int, saved_image_only: bool = False, diagnostic_limit: int = 20, use_input_snapshot: bool = False, wait_for_completion: bool = True) -> CallToolResult:
    """use_input_snapshot=True显式以本版本新run绑定的冻结输入在独立实例重算，不证明当前模型有效；支持重启后读取，有预算并核对全组件帧姿态，无绑定快照的旧run拒绝猜测。wait_for_completion=False异步返回job_id。默认仅回放本会话输入匹配的run：重算、全组件姿态核验、截图并恢复。diagnostic_limit默认20、范围1–100，字节预算可能缩短展示；全部组件仍核验，完整诊断可用get_run_artifacts(replay_diagnostics=True)离线分页。saved_image_only=True离线读取该帧已记录且哈希通过的历史BMP，不调用COM、不检查当前模型；未曾生成该帧图像则明确报缺失，不强行摆位。"""
    if saved_image_only and use_input_snapshot:
        raise ToolError("saved_image_only与use_input_snapshot不能同时启用。")
    if saved_image_only:
        try:
            return packed({"ok": True, "result": await asyncio.to_thread(artifacts.saved_frame_image, run_id, frame)})
        except (ArtifactError, ValueError, OSError) as exc:
            return packed({"ok": False, "error": {"code": getattr(exc, "code", "SAVED_IMAGE_ACCESS_FAILED"), "message": str(exc), "assertion": "inconclusive", "restoration_status": "not_required"}}, True)
    if type(diagnostic_limit) is not int or not 1 <= diagnostic_limit <= 100:
        raise ToolError("diagnostic_limit须为1–100整数。")
    params = dict(run_id=run_id, frame=frame, diagnostic_limit=diagnostic_limit, use_input_snapshot=use_input_snapshot)
    return await call("replay_motion_frame", **params) if wait_for_completion else enqueue("replay_motion_frame", params)


@mcp.tool()
async def create_model_checkpoint(model_id: str, wait_for_completion: bool = False) -> CallToolResult:
    """快照副本全部CAD文件、配置、算例与姿态，不自动归零；默认异步job_id，wait_for_completion=True兼容同步。"""
    return await call("create_model_checkpoint", model_id=model_id) if wait_for_completion else enqueue("create_model_checkpoint", {"model_id": model_id})


@mcp.tool()
async def reset_study_time(model_id: str, study: str, allow_recalculate: bool = False, wait_for_completion: bool = False, reset_output_fps: int = 0, create_new_model: bool = False, checkpoint_id: str = "") -> CallToolResult:
    """reset_output_fps与create_new_model=True、allow_recalculate=True组合，显式指定checkpoint_id，从冻结输入在新登记副本降帧归零，不保存当前脏内存，返回新model_id；保留原模型，新副本失败则隔离。归零并保存副本，先建立检查点。默认不求解；可显式allow_recalculate=True按原设置重建缓存后归零，预算同时限制30秒、1000fps、1801帧（5秒300fps允许；新建/运行仍最多120fps）。超预算在检查点前拒绝，查看逐算例指引；不忽略非零算例、不自动降fps。旧结果失效；隔离期间禁止。"""
    if reset_output_fps:
        if not create_new_model or not allow_recalculate or not 5 <= reset_output_fps <= 1000 or not re.fullmatch(r"[a-f0-9]{32}", checkpoint_id):
            raise ToolError("reset_output_fps要求create_new_model=True、allow_recalculate=True、checkpoint_id和5–1000fps。原模型保留，成功后使用返回的新model_id。")
        return enqueue("reset_study_time", dict(model_id=model_id, study=study, allow_recalculate=True, reset_output_fps=reset_output_fps, create_new_model=True, checkpoint_id=checkpoint_id))
    if checkpoint_id and not reset_output_fps:
        raise ToolError("checkpoint_id仅用于显式新副本降帧归零。")
    if create_new_model:
        raise ToolError("create_new_model须同时指定reset_output_fps。")
    if allow_recalculate or not wait_for_completion:
        return enqueue("reset_study_time", {"model_id": model_id, "study": study, "allow_recalculate": allow_recalculate})
    return await call("reset_study_time", model_id=model_id, study=study, allow_recalculate=False)


@mcp.tool()
async def get_run_artifacts(run_id: str = "", model_id: str = "", operation_id: str = "", limit: int = 5, cursor: str = "", include_file_hashes: bool = False, replay_diagnostics: bool = False) -> CallToolResult:
    """离线：传run_id读求解摘要及已记录截图，摘要忽略limit；replay_diagnostics=True按limit（1–100）/cursor分页读取哈希绑定的完整回放诊断。或传model_id/operation_id分页读本次保存观测（operation_id为空选最近已记录操作）。完整哈希须include_file_hashes=True，限1–20条/16KB；大记录给受限摘要和文件路径。两种身份不可混用。重启/隔离可用，不证明当前CAD状态或物理精度。"""
    try:
        if model_id:
            if run_id:
                raise ValueError("run_id 与 model_id 保存观测查询不能混用。")
            if replay_diagnostics:
                raise ValueError("回放诊断分页须指定run_id，不能与model_id保存观测混用。")
            return packed(await asyncio.to_thread(artifacts.save_observations, model_id, operation_id, limit, cursor, include_file_hashes))
        if run_id:
            if replay_diagnostics:
                if operation_id or include_file_hashes:
                    raise ValueError("回放诊断查询不使用operation_id/include_file_hashes。")
                return packed(await asyncio.to_thread(artifacts.replay_diagnostics, run_id, limit, cursor))
            if operation_id or cursor or include_file_hashes:
                raise ValueError("run_id摘要不使用operation_id/cursor/include_file_hashes；保存观测分页请改用model_id，回放诊断分页请显式replay_diagnostics=True。")
            data = await asyncio.to_thread(artifacts.summary, run_id)
            return packed({**data, "query_scope": "run_summary", "limit_applied": False})
        if replay_diagnostics:
            raise ValueError("回放诊断分页须指定run_id。")
        if operation_id or cursor or include_file_hashes or limit != 5:
            raise ValueError("保存观测分页参数须同时指定 model_id。")
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
async def get_recovery_state(request_id: str = "") -> CallToolResult:
    """离线读日志/迟到响应。status: idle=请求结束，active=记录执行中，unknown=未确认；不证明CAD姿态。current_request_state为completed/dispatching/unconfirmed。observed_dispatch_state保留旧原值；*_field_consistent核对派生字段，false不自动改日志或解除隔离。state_scope区分本owner执行中、idle和旧/未知请求；cad_request_policy为available/wait_for_current_request/recovery_only。恢复未知须显式恢复检查点。"""
    state = bridge.recovery_state()
    if request_id:
        try:
            state["request_result"] = await asyncio.to_thread(bridge.get_request_result, request_id)
            state["current_model_validity"] = "not_checked_offline"
        except CadError as exc:
            return packed({"ok": False, "error": {"code": exc.code, "message": str(exc), "diagnostics": exc.diagnostics}}, True)
    return packed(state)


@mcp.tool()
async def restore_model_checkpoint(model_id: str, checkpoint_id: str, allow_replacement_session: bool = False) -> CallToolResult:
    """关闭登记副本文档、恢复全部文件并核验配置、算例与姿态；旧结果失效。旧执行器必须停止，默认绑定原 SolidWorks 进程。"""
    return await call("restore_model_checkpoint", model_id=model_id, checkpoint_id=checkpoint_id, allow_replacement_session=allow_replacement_session)


if __name__ == "__main__":
    mcp.run(transport="stdio")
