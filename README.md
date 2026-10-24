# Solidworks_ClashMate_MechDog

**SolidWorks ClashMate MechDog MCP**：通过 AI 对话，在本机 SolidWorks 中检查装配体、推荐驱动、运行运动仿真、导出曲线，并验证与恢复副本。

版本：`v0.4.3-alpha.8`（预发布）。保留原有 24 个工具，新增 6 个对话任务与收尾工具，共 30 项。日常使用不需要网页或另一套桌面助手。

[项目与下载](https://github.com/wudahua/Solidworks_ClashMate_MechDog/releases) · [本轮说明](发布说明_v0.4.3-alpha.8.md)

## 用户如何使用

首次安装仍需要 Windows、64 位 Python 3.11+、可用的 SolidWorks/Motion Analysis 及许可。本机驱动适配当前校准到 SolidWorks 2026 revision 34.0.0；其他版本不会假定兼容。源码包不包含 CAD 模型、SolidWorks、许可、Interop、虚拟环境或预编译执行器。

安装与升级工作可以交给 AI 完成，入口仍是项目虚拟环境的 Python 和 `motion_server.py`，配置键仍为 `solidworks-clashmate-mechdog`。保留已有正式服务，更新同一个安装目录即可；不要同时启用旧测试服务或旧桌面助手的执行器。

配置示例中的路径需由安装 AI 按实际目录填写：

```json
{
  "mcpServers": {
    "solidworks-clashmate-mechdog": {
      "command": "C:\\ClashMate\\.venv\\Scripts\\python.exe",
      "args": ["C:\\ClashMate\\motion_server.py"],
      "env": {"SW_MCP_PROCESS_ID": "auto", "PYTHONIOENCODING": "utf-8"}
    }
  }
}
```

完成接入后，直接对 AI 说：

- “检查这个装配体，推荐旋转驱动。先解释目标零件、参考、轴线和参数，我确认后再试算。”
- “让滑块2-1相对导轨-1以 1 mm/s 运动 2 秒，导出曲线；完成后恢复副本。”
- “检查轴与支座的圆边，推荐一项保留旋转的同轴配合，说明约束影响后再执行。”
- “刚才连接断了，先找回原任务，不要重新创建或重复执行。”
- “读取失败诊断并整理已有证据，不再求解。”

AI 应定位文件、读取任务、检查与推荐；只有零件/轴线/机械起点存在歧义，或需要具体写入授权时才询问用户。实体 ID、任务 ID、方案令牌由 AI 管理。

## 对话任务流程

1. `get_mechanism_task` 找回已有任务；没有任务再 `prepare_mechanism_task`。
2. 自动创建专用 CAD 实例和隔离副本，推荐目标、参考与几何方向。几何排序不是设计意图或自由度证明。
3. `plan_mechanism_task` 生成待确认方案；需要时用名称、用途或实例后缀澄清。
4. 用户确认后 `execute_mechanism_task` 一次执行。后续查询使用 `get_mechanism_task`，不能重放写入。
5. 明确报告声明运动是否通过、方向观测、曲线及范围；`finish_mechanism_task` 恢复导入检查点并核对专用执行器/CAD 退出，再开始下一轮。

默认从导入时的机械姿态试算。未激活旧动画的非零时钟不等于机械姿态无效；不自动重算所有旧算例。明确选择 `study_zero` 会在副本重算并归零，可能遇到原生失败；不会以时间显示为零替代姿态证明。创建前、创建后与实际求解首帧的全部组件起点按 `1e-7 m / 1e-6 rad` 核对。

当前对话运动流程限旋转/直线恒速、5 秒、601 帧，要求现有装配配合有效；不自动解除固定。参考件可以未固定，测量相对运动。旋转速度为 rpm，直线速度为 mm/s；最低行程是度或毫米。原有低层工具保留 30 秒/1801 帧等各自预算。

圆边同轴任务当前是受限验证：一个浮动件与一个固定件，12 rpm、1 秒、30 fps；只补一项同轴约束，默认不锁旋转。允许消除预先确认的轴线横向偏移和倾斜，分别报告旋转、轴向位移、其他组件和初态保留。声明范围通过不等于完整轨迹等价、整机自由度或整泵传动通过。结束默认恢复导入检查点。

需要保留已验证成果时，AI 可以明确使用 `finish_mechanism_task(keep_result=true)`；成果保存为独立副本，原装配不覆盖。此分支目前仍是试验能力：本机圆边副本两次出现 CAD 已退出但退出码为 1，任务保留“清理警告”，不会报告正常退出或已恢复导入检查点。默认恢复收尾已通过连续执行验证。保留成果、检查点恢复、资源已退出、正常退出码是四个分别报告的结论。

## 重连接续与失败处理

任务由 Windows 当前登录用户的按需宿主持有，独立于 MCP 客户端进程树；首次调用自动核验/登记。本登记没有定时或登录触发器、不保存密码、不请求提升权限；无任务时空闲退出。退出客户端不代表丢弃任务，重连会核对进程创建身份、源码指纹和同一桌面会话。

旧宿主已退出时可以加载旧记录，不能从 JSON 重建 COM 或重放令牌。对于未进入执行的失败任务，只有用户明确同意、且旧资源退出、空闲日志、源文件均有证明，才能用 `close_unrestored=true` 关闭失败记录；记录明确保持“恢复未验证”。未知或已开始执行的原生状态继续保护。

原受管连接仍然存活时，`get_recovery_state` 读取该任务自己的恢复日志；AI 只有在旧请求已结束、原执行器和 CAD 身份一致时，才可用 `restore_model_checkpoint` 恢复该任务的导入检查点。恢复后独立核对组件姿态、固定状态与配合数，撤销旧确认并引导收尾。超时请求尚未结束时不会派发恢复，也不从其他安装目录借用“空闲”状态。

`get_mechanism_task(collect_evidence=true)` 由 AI 自动整理现有诊断 ZIP，不要求用户搜日志。包排除 CAD 模型与 IPC 认证信封/密钥，但仍可能含模型名和路径；对外分享前核对范围。收集动作不发起 CAD 求解。

原有低层工具会话在切换受管任务前，AI 使用 `finish_motion_session`，仅在无执行中任务且恢复状态明确时释放本服务执行器；该动作不关闭用户 SolidWorks、不证明副本已恢复。受管任务用自己的 finish 工具。更新源码不会接管活任务或解除未知状态。

## 原有工具仍可使用

- 环境、隔离导入与模型登记：`get_environment`、`import_assembly`、`list_models`、`inspect_model`。
- 运动：`list_motion_studies`、`preflight_motion`、`list_drive_candidates`、`create_motion_study`、`convert_motion_study`、`run_motion_study`、`verify_motion_preservation`。
- 基础配合：`list_mate_references`、`preview_mate`、`apply_mate`。同轴支持圆柱面和本轮新增圆形边线；重合、距离、平行、垂直使用受支持平面，不自动换成邻面。
- 结果：`get_job`、`get_motion_summary`、`export_motion_curve`、`replay_motion_frame`、`get_run_artifacts`、`read_run_poses`。
- 检查点与恢复：`create_model_checkpoint`、`reset_study_time`、`get_recovery_state`、`restore_model_checkpoint`。

长操作保留异步 job 查询。执行成功、运动判据通过、恢复成功是不同结论。超时不代表 CAD 停止；未知状态下不重复写入。离线历史读取不证明当前 CAD 适用性。完整最终响应及 SHA256 仍保存，可分页读取，已有协议错误码和保护继续保留。

## 范围与验证

本机真实 CAD 已验证准备齿轮泵的正反旋转、方槽直线导轨的正反直线运动，以及受限圆边同轴任务。一个宿主依次完成旋转、直线、圆边恢复、圆边保留成果及警告后的下一次旋转；前三轮及最后一轮恢复、CAD/执行器退出码 0，保留成果轮单列清理警告。真实 MCP 前端断开重连、旧确认拒绝及显式检查点恢复均有本机证据。本轮没有新增跨机真人 WorkBuddy 验收声明，具体批次见发布说明。历史各模型证据继续保留，不合并为任意装配兼容性认证。

尚未支持任意机构设计意图理解、任意装配自动补齐配合、草图段/任意边缘新增配合、通用静态和动态干涉检查。曲线来自采样姿态及数值导数，不认证接触/受力物理精度。旧保存/退出停滞、钟表重复求解漂移等原生边界没有被宣称根治。

开发检查由 AI 执行：Python 回归、离线 C# 策略、真实 MCP/宿主生命周期、自己的 CAD 副本实测、源码包完整性及升级预演。普通使用者无需执行这些开发命令。工作流为本机验证 → GitHub 更新 → 另一台电脑正常使用 → MD 反馈。

历史发布说明与旧 Release 资产保留。MIT 许可见 [LICENSE](LICENSE)。
