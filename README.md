# Solidworks_ClashMate_MechDog

SolidWorks 运动仿真 MCP。[GitHub 项目](https://github.com/wudahua/Solidworks_ClashMate_MechDog) · [试用版下载](https://github.com/wudahua/Solidworks_ClashMate_MechDog/releases)

`v0.4.0-alpha.3` 修复试用版：让 AI 在本机 SolidWorks 中导入已保存装配的隔离副本、检查运动准备状态、复用 Motion Analysis 算例或添加一个恒速驱动，然后求解、导出曲线和回放截图。

**本版本公开的是运动仿真工具，暂不提供通用静态或动态干涉检查。** 修复范围及验收边界见 [发布说明](发布说明_v0.4.0-alpha.3.md)。

这是供试用的运动仿真版本。已有有效配合的刚体机构是目标输入；没有配合的装配需要先由设计者完成运动约束。尚未完成“大部分机械装配均可用”的样本覆盖验收。

## 能做什么

- 复制装配及磁盘依赖，在副本重定向引用；源文件不交给 SolidWorks 打开或保存，导入与求解后核对源文件 SHA-256。
- 读取组件、配置、顶层配合错误，解析副本轻量化组件；返回明确的预检阻塞原因。配合数量不作为自由度证明。
- 复用已有 Motion Analysis；显式转换算例类型。为用户选定的组件和圆柱轴/平面法向创建一个恒速旋转或直线马达。
- 异步求解，读取真实输出时间轴和组件姿态，独立核对新建驱动的速度幅值；恢复求解前姿态。
- 导出位置、位移、线速度和角速度 CSV；回放采样帧并输出 BMP。速度来自姿态数值微分，参考点为组件坐标原点，不是质心或原生瞬时速度。
- 保存整套副本文件检查点；恢复后核验文件、配置、算例设置和姿态。执行器丢失后阻止普通请求，恢复绑定故障模型和 SolidWorks 实例。

公开入口不提供通用干涉检查、受力精度证明、自动补配合、自动推断设计意图或任意参数优化。原项目的专用干涉与闭环验收能力仍属于开发分支范围。

## 环境与兼容性

| 项目 | 首版要求 / 已验证范围 |
|---|---|
| SolidWorks | 本机已安装并由用户启动；已校准 **2026 SP0，API revision 34.0.0** |
| Motion | 已安装并具备 Motion Analysis 使用许可；Motion 插件加载失败明确拒绝 |
| 系统 | Windows x64；正式试用建议 Windows 11，独立 Windows 11 机器验收待完成 |
| Python | 64 位 Python 3.11+；开发实测为 3.12.14，建议先用 3.12 |
| 编译 | .NET Framework 4.8 的 x64 C# 编译器，引用用户本机 SolidWorks interop |
| MCP SDK | 固定为 2.3.0，依赖版本见 requirements.lock.txt |

当前开发机 Windows 10 实测不能作为 SolidWorks 2026 官方系统兼容证明。官方系统要求显示 Windows 10 最后支持版本为 SolidWorks 2025 SP5。[官方系统要求](https://www.solidworks.com/support/system-requirements)

其他 SolidWorks revision 可连接、读取环境，首版拒绝未校准版本的通用求解和新建驱动。跨版本适配尚未验收。不要把 Motion Analysis、Basic Motion 和动画视为相同求解器。[官方算例类型说明](https://help.solidworks.com/2025/english/SolidWorks/motionstudies/c_deciding_which_motion_study.htm)

## 安装

解压到有写权限的短路径，例如 `C:\MCP\ClashMate`，避免直接放在 Program Files。所有运行结果和隔离副本保存在安装目录的 `runs/` 与 `experiments/`；很长的安装路径或CAD文件名可能触及Windows路径长度限制。

```powershell
# 在解压后的项目目录执行；PythonPath 填自己的 Python 路径。
.\初始化环境.ps1 -PythonPath 'C:\Python312\python.exe'

# 如果 SolidWorks 安装在其他位置：
.\初始化环境.ps1 -PythonPath 'C:\Python312\python.exe' -SolidWorksInstallDir 'D:\SOLIDWORKS'

# 不进入 COM 的安装自检
.\.venv\Scripts\python.exe .\scripts\self_check.py
```

安装脚本会从 PyPI 安装固定版本依赖，并从本机安装目录引用 DLL。发布包不附带 SolidWorks 程序、授权、interop DLL 或预编译执行器。

启动 SolidWorks 后，在相同 Windows 用户和桌面会话运行服务；双方权限级别应一致。只允许一个执行器运行。多个 SolidWorks 实例时必须选择 PID：

```powershell
Get-Process SLDWORKS | Select-Object Id, ProcessName
.\启动MCP.ps1 -SolidWorksProcessId 12345
```

将命令登记到支持 stdio MCP 的客户端。示例中的路径和 PID 必须改为本机值；服务 stdout 只承载 MCP 协议。

```json
{
  "mcpServers": {
    "solidworks-motion": {
      "command": "C:\\MCP\\SolidWorksMotion\\.venv\\Scripts\\python.exe",
      "args": ["C:\\MCP\\SolidWorksMotion\\motion_server.py"],
      "env": {"SW_MCP_PROCESS_ID": "12345"}
    }
  }
}
```

可先在终端运行 `.\.venv\Scripts\python.exe .\scripts\self_check.py --connect`；此前通过 `$env:SW_MCP_PROCESS_ID='12345'` 选择实例。服务不会自动启动或关闭 SolidWorks。

## 第一次使用

1. 保存原装配及全部零件。源文件存在未保存修改时导入会拒绝；虚拟零件先保存到磁盘。确认装配在 SolidWorks 中能按设计意图运动。
2. 调用 `get_environment`，确认 revision 与 Motion 使用条件。
3. 调用 `import_assembly`，传入 `.SLDASM` 绝对路径和可选配置。返回 job_id 后用 `get_job` 等待完成，保存结果中的 model_id 和 checkpoint_id。
4. 调用 `inspect_model`、`preflight_motion`、`list_motion_studies`。
5. 已有 Motion Analysis：直接选算例。已有动画/Basic Motion：明确请求 `convert_motion_study`。没有驱动：调用 `list_drive_candidates`，由用户选择组件、参考实体、速度与方向，再 `create_motion_study`。创建结果返回实际时长、帧率和算例状态。
6. 调用 `run_motion_study`，用 `get_job` 查询。成功结果包含 run_id、时间轴验证和驱动验证范围。复用已有算例时不声称已独立证明物理结果。
7. 调用 `export_motion_curve` 或 `replay_motion_frame`。run_id 仅在当前执行器会话有效；文件导出会保留。

结果描述的是导入时的副本。之后修改源文件会显示源哈希不一致，副本仍可独立求解和恢复；要模拟新设计，请重新导入。导入过程本身出现源哈希变化则拒绝完成导入。

算例特征列表是 API 能枚举的子集；空列表不能作为“没有马达”的证明。复用算例前仍应确认原装配的驱动设置。

可对 AI 说：“导入这个已配好的装配到副本，列出现有运动算例；使用指定算例运行一秒、30 fps，导出指定组件的 X 位移曲线。”新建驱动时应进一步说明选哪个轴或面、速度和方向。

## 工具清单

| 工具 | 用途 |
|---|---|
| get_environment / list_models | 环境与登记模型 |
| import_assembly / inspect_model | 副本导入、组件与顶层配合 |
| preflight_motion / list_motion_studies | 准备检查与算例清单 |
| list_drive_candidates | 按组件、几何类型过滤的分页候选和持久引用 ID；默认按同一轴线/平面位置分组，20项、最多50项 |
| create_motion_study / convert_motion_study | 创建单一恒速驱动 / 显式转换类型 |
| run_motion_study / get_job | 异步求解与缓存进度 |
| get_motion_summary / export_motion_curve | 结果有效性检查与 CSV |
| replay_motion_frame | 核验采样帧并导出截图 |
| create_model_checkpoint / restore_model_checkpoint | 整套副本检查点与恢复 |
| get_recovery_state | 不进入 COM 的请求状态查询 |
| reset_study_time | 显式归零所选算例；先建立回滚检查点，旧结果失效 |
| get_run_artifacts / read_run_poses | 离线摘要与分页姿态；恢复失败、执行器重启后仍可读取保存文件 |

## 限制与恢复

默认最多 30 秒、1801 帧、500 个组件和 10 万条组件姿态；帧率 5–120。新建旋转驱动要求每帧小于等于 45°，避免角速度微分歧义。已有快速驱动可能发生采样混叠，应提高帧率并另行校验。

虚拟零件、丢失引用、SpeedPak、未解析组件及未验收的柔性子装配会被拒绝。刚性嵌套装配、重复实例、复杂配置和外部参照的代码路径仍需扩大样本验收；首版不据此承诺通用支持。接触、弹簧、凸轮或多个驱动可通过已有算例尝试运行，但其物理精度与求解稳定性不在首版认证范围内。

超时意味着结果未知，不能解释为求解已停止，也不能强行并行重试。等待真实响应或查询恢复状态。执行器确认结束后，使用**同一模型**此前保存的 checkpoint_id 恢复；旧 run_id 必须重新求解。默认绑定原 SolidWorks PID，旧实例确实退出时才可显式允许替代实例。恢复会关闭该登记副本及其依赖文档，不关闭用户其他文件。

在首次导入登记完成前中断，可能尚无完整检查点可自动恢复；保留日志和副本，不手动把未知请求记录改成 idle。这个边界以及客户端断开后的实例寿命、独立机器安装，需要继续扩大验证。

求解会保存登记副本的操作前状态并快照全部副本文件，结束后重开副本，核验全部算例的时间、类型、输出设置、激活状态及组件姿态。仅设置时间条不足以证明恢复成功。成功结果的曲线读取已保存姿态；回放会重新求解并与已保存采样帧对照。求解原生数据的完整采集、状态恢复和物理验证范围分别报告，周期运动应检查整个时间区间。

回放核验分别报告平移差异（米）与相对旋转角差异（弧度），默认阈值为 `1e-7 m` 与 `1e-6 rad`。旧 `maximum_pose_difference` 保留为兼容诊断，不再把它当作长度。阈值只用于重新求解的采样姿态对照，不代表模型、受力或接触精度认证；超阈值仍拒绝截图。回放包含重新求解，采用与求解相同的600秒执行器等待预算，超时仍不代表CAD停止。

`Calculate()` 返回成功不足以证明结果覆盖请求时段。原生结果只有初始时刻或提前结束时返回 `MOTION_RESULTS_INCOMPLETE`；长度或采样网格不符返回 `NATIVE_TIME_AXIS_MISMATCH`。诊断含实际点数、首尾时间、步长、偏差和结果载体，完整时间轴保存在该任务目录的 `time-axis.json`。不要用放宽容差或生成伪时间点来绕过。真实夹具旋转驱动曾收到原生“不相容冗余约束导致仿真停止”的提示，需核对模型和驱动相容性；工具不自动修改配合。

驱动候选默认 `group_faces=True`，按组件及轴线/平面位置分组，保留最大面积面作为代表，并返回 `equivalent_face_count`、`reference_point_global_m` 和 `raw_candidate_count`。方向相同但位置不同的轴线保留为不同候选。设为False可查看逐面候选；切换分组会使旧游标失效。只能使用该模型已查询并登记的entity_id；缺失引用需重新查询，不能把其他模型或旧副本的ID直接复制过来。

任务进度在结束后具有 `terminal=True` 和最终stage，并保留 `last_native_stage`。`timed_out`、`executor_lost` 的 `cad_operation_finished=False` 表示没有确认CAD操作结束。错误中的 `document_context_restoration_status` 单独说明活动窗口恢复；`restoration_status` 描述模型/算例恢复，读取候选的窗口恢复不再暗示模型执行过检查点恢复。

在 revision 34.0.0 的额外边界实测中，激活算例停在非输出帧时刻曾导致原生采样阻塞。因此本版在求解或回放前拒绝该状态，返回 `ACTIVE_TIME_NOT_FRAME_ALIGNED`，需先显式调用 `reset_study_time`。这与未激活算例中保存的非零时间不同，后者仍按快照完整保留；不会把全部算例无条件归零。

失败任务也保留 `solve.json`；完整采集时保留姿态 CSV 和哈希。离线接口中的 `current_model_validity=not_checked_offline` 表示没有核查当前模型，不得把历史数据当作当前设计的有效结果。`inconclusive` 仍表示未完成验证。源文件与组件配置名称原样保留，`默认` 和 `Default` 是不同的配置标识。

alpha.1等历史任务只有CSV时，可以受限读取并标记 `manifest_status=absent`、`artifact_integrity=hash_not_recorded`、`restoration_status=unknown`、`result_validity=inconclusive`；当前计算的文件哈希只用于分页一致性，不证明历史结果正确。损坏的现有清单不会被自动替换。不存在的任务、缺清单、缺CSV和文件损坏分别返回明确错误。

首次连接时未找到SolidWorks，且握手明确失败、没有派发任何CAD请求时，启动软件后可在同一MCP会话重试。已经连接后的执行器丢失、超时、协议异常或恢复隔离均不采用这条重连路径。

指纹读取对指定RPC暂时失败可重新获取已打开文档，最多读取3次。此规则只覆盖指纹读取，不重复保存、求解或恢复写操作；最终读取仍失败时维持未知状态和隔离。

官方恢复入口为 `.venv\Scripts\python.exe scripts\recover.py inspect`，此命令不调用 COM。普通恢复用 `restore --model-id <id> --checkpoint-id <id> --solidworks-pid <pid>`；旧实例确认退出时才使用 `--allow-replacement-session`。先停用本目录的 MCP 服务，命令行与服务不能同时持有执行器。

历史日志缺失 SolidWorks PID 时，不能直接放行或删除日志。操作者须确认 CAD 空闲、旧操作已经结束、旧执行器已退出，并核对实际实例及受影响模型；运行 `inspect` 获取当前日志 SHA-256 后，才可使用 `reconcile-missing-identity --model-id <id> --checkpoint-id <id> --solidworks-pid <pid> --journal-sha256 <hash> --confirm-operation-ended`。该命令保留原日志审计副本，将记录继续保持为 unknown，只有指定模型的检查点恢复核验成功后才解除隔离。**AI 不得自动替操作者确认旧操作已经结束。** 身份不明、旧执行器存活、日志变化或没有有效检查点时仍拒绝恢复。

## 示例与测试

示例通过本项目的程序生成，发布包不含用户齿轮泵、零件或第三方 CAD 文件。生成器需要可用的 SolidWorks 零件和装配模板，可显式指定：

```powershell
.\生成运动示例.ps1 -SolidWorksProcessId 12345 -PartTemplate 'D:\Templates\part.prtdot' -AssemblyTemplate 'D:\Templates\assembly.asmdot'
# 输出目录包含 examples.json，填入下面的路径。
.\.venv\Scripts\python.exe .\tests\motion_acceptance_v04.py '生成目录\examples.json'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
.\.venv\Scripts\python.exe .\tests\motion_protocol_v04.py
```

接入实际 COM 的协议测试和故障注入测试属于开发验收：后者需要显式使用自建登记模型，并只终止测试自己创建的执行器，不能对正在处理用户文件的服务执行。见 tests 目录脚本说明。

## 后续路线

1. Windows 11 独立机器安装、MCP 客户端关闭与恢复回归。
2. 刚性多层子装配、重复零件不同配置、轻量化及外部参照样本矩阵。
3. 配合诊断与驱动向导：明确欠约束/过约束原因、多候选选择、方向预览；保留用户确认设计意图。
4. 扩大机构样本：铰链、滑台、曲柄滑块、齿轮与带链传动、凸轮等；按通过的样本发布支持范围。
5. 更多 SolidWorks revision 单位与时间采样适配；之后再推广通用干涉与参数闭环。

MIT 许可覆盖本项目代码。SolidWorks 及其运行组件由用户自行安装并授权。
