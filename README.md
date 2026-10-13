# Solidworks_ClashMate_MechDog

SolidWorks 运动仿真 MCP。[GitHub 项目](https://github.com/wudahua/Solidworks_ClashMate_MechDog) · [试用版下载](https://github.com/wudahua/Solidworks_ClashMate_MechDog/releases)

`v0.4.1-alpha.1` 基础配合助手与运动验证试用版：让 AI 在本机 SolidWorks 中导入隔离副本，按用户选择创建基础配合，复用或创建 Motion Analysis 算例，再验证所声明的运动、导出曲线和回放截图。

**本版本公开的是运动仿真工具，暂不提供通用静态或动态干涉检查。** 修复范围及验收边界见 [发布说明](发布说明_v0.4.1-alpha.1.md)。

这是供试用的运动仿真版本。已有有效配合的刚体机构可直接进入运动流程；缺少基础配合时可由设计者选定参考和类型，再让助手执行。尚未完成“大部分机械装配均可用”的样本覆盖验收。

## 能做什么

- 复制装配及磁盘依赖，在副本重定向引用；源文件不交给 SolidWorks 打开或保存，导入与求解后核对源文件 SHA-256。
- 读取组件、配置、顶层配合错误，解析副本轻量化组件；返回明确的预检阻塞原因。配合数量不作为自由度证明。
- 复用已有 Motion Analysis；显式转换算例类型。为用户选定的组件和圆柱轴/平面法向创建一个恒速旋转或直线马达。
- 异步求解，读取真实输出时间轴和组件姿态，独立核对新建驱动的速度幅值；恢复求解前姿态。
- 导出位置、位移、线速度和角速度 CSV；回放采样帧并输出 BMP。速度来自姿态数值微分，参考点为组件坐标原点，不是质心或原生瞬时速度。
- 保存整套副本文件检查点；恢复后核验文件、配置、算例设置和姿态。执行器丢失后阻止普通请求，恢复绑定故障模型和 SolidWorks 实例。
- 查询包括固定支座在内的顶层零件配合参考，预览具体方案，确认后添加同心、重合、距离、平行或垂直配合；创建或重建失败回滚。
- 显式验证指定组件沿指定轴的旋转/直线运动；可比较绑定基线的前后运动量。通过结论仅覆盖这项采样运动要求。

公开入口不提供通用干涉检查、受力精度证明、自动推断缺失配合或设计意图、任意装配自动补齐配合或任意参数优化。原项目的专用干涉与闭环验收能力仍属于开发分支范围。

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
5. 已有 Motion Analysis：直接选算例，并查看 `last_run` 及其输入匹配状态。已有动画/Basic Motion：明确请求 `convert_motion_study`。没有驱动：调用 `list_drive_candidates`，由用户选择组件、参考实体、速度与方向，再 `create_motion_study`。创建结果返回实际时长、帧率和算例状态。**预检通过或驱动创建成功不保证驱动与配合相容，也不保证求解成功。** 旋转驱动与现有约束不相容时可能只有初始结果，需核对约束和设计意图；直线驱动只可在适用机构中作为对照，不能通用替代旋转驱动。
6. 调用 `run_motion_study`，用 `get_job` 查询。成功结果包含 run_id、时间轴验证和驱动验证范围。复用已有算例时不声称已独立证明物理结果。
7. 调用 `export_motion_curve` 或 `replay_motion_frame`。run_id 仅在当前执行器会话有效；文件导出会保留。

结果描述的是导入时的副本。之后修改源文件会显示源哈希不一致，副本仍可独立求解和恢复；要模拟新设计，请重新导入。导入过程本身出现源哈希变化则拒绝完成导入。

算例特征列表是 API 能枚举的子集；空列表不能作为“没有马达”的证明。`feature_information_source=native_api` 与 `drive_information_source=project_registration` 分别表示原生枚举和项目登记，登记驱动通过 `registered_drive` 单独返回，不声称已由当前原生枚举核实。`native_null_study_active`/`native_null_study_inactive` 表示返回null时的观测上下文，不证明必须激活才能枚举。空列表的 `feature_presence=unknown`，`empty_feature_list_means_no_drive=False`；查询不自动切换算例。复用算例前仍应确认原装配的驱动设置。

可对 AI 说：“导入这个已配好的装配到副本，列出现有运动算例；使用指定算例运行一秒、30 fps，导出指定组件的 X 位移曲线。”新建驱动时应进一步说明选哪个轴或面、速度和方向。

## 工具清单

| 工具 | 用途 |
|---|---|
| get_environment / list_models | 环境与登记模型 |
| import_assembly / inspect_model | 副本导入、组件与顶层配合 |
| preflight_motion / list_motion_studies | 准备检查与算例清单 |
| list_drive_candidates | 按组件、几何类型过滤的分页候选和持久引用 ID；默认按同一轴线/平面位置分组，20项、最多50项 |
| list_mate_references | 顶层零件平面/圆柱面分页查询，含固定支座；每零件最多128面，报告截断 |
| preview_mate / apply_mate | 描述性方案预览 / 明确确认后建立检查点并创建配合 |
| verify_motion_preservation | 显式异步试算指定运动要求，最多5秒601帧；可比较方案绑定的运行基线 |
| create_motion_study / convert_motion_study | 创建单一恒速驱动 / 显式转换类型 |
| run_motion_study / get_job | 异步求解与缓存进度 |
| get_motion_summary / export_motion_curve | 结果有效性检查与 CSV |
| replay_motion_frame | 核验采样帧并导出截图 |
| create_model_checkpoint / restore_model_checkpoint | 整套副本检查点与恢复 |
| get_recovery_state | 不进入 COM 的请求状态查询 |
| reset_study_time | 显式归零所选算例；先建立回滚检查点，旧结果失效 |
| get_run_artifacts / read_run_poses | 离线摘要与分页姿态；恢复失败、执行器重启后仍可读取保存文件 |

## 限制与恢复

公开工具共24个。基础配合首版只支持已解析、非SpeedPak的顶层SLDPRT实例；不支持子装配内部参考、边线/顶点/基准面或复杂机械配合。同心选两个圆柱面，其余类型选两个平面；方向必须明确为aligned或anti_aligned，距离单位mm，同心默认不锁定旋转。候选列表不根据面积或距离猜测设计意图。描述性预览不移动零件，不产生几何动画预览。

配合操作要求各算例时间为0；需要时先显式reset_study_time。用户明确选定两个参考、类型及参数后，先preview_mate，再apply_mate(confirmed=True)。方案绑定文件哈希、配置、版本、文档更新标记/脏标志、姿态、算例状态及配合清单；保守地在状态变化后拒绝执行。本会话最多128个方案，执行过的方案不能重放，重连后须重新预览。apply_mate会保存登记副本以建立检查点，不保存源装配。

新增配合成功后仍须验证运动。先选择运动组件、参考轴、算例和minimum_travel，再显式verify_motion_preservation。旋转的最低运动量为deg，直线为mm；返回assertion=pass/fail/inconclusive，不能仅凭job成功判定通过。直线验证检查沿轴位移跨度、偏轴位移和伴随旋转；旋转验证检查累计投影角跨度及偏轴旋转，允许偏置组件原点沿圆周移动。默认偏轴容差为直线0.01mm/旋转0.1deg，直线伴随旋转容差0.1deg。这些是首版验收阈值，不是通用机构精度认证。

要比较配合前后运动，先run_motion_study取得当前模型已验证基线，再preview_mate传入baseline_run_id，应用后以该plan_id调用验证；组件、算例、时长及帧率须一致。前后运动量差容差为基线的5%，下限旋转0.1deg/直线0.01mm。模型再次修改会使plan_id验证失效。无基线时仅验证当前运动要求，不声称运动相对修改前已保留。

运动验证会恢复求解前状态，但不会因验证失败自动删除新配合。保留方案返回的checkpoint_id，由用户决定restore_model_checkpoint。求解不完整、采样歧义或恢复失败不能判定通过；未知恢复继续隔离。已有未登记快速驱动可能产生采样混叠，即使通过也不证明未采样运动或整个机构自由度正确。

本机反例中，固定支座与转轴的同心配合原生LockRotation=True，但Motion Analysis仍返回了转轴旋转数据。验证器核对直接连接固定组件的原生锁旋转配合，发现声明旋转与锁定约束冲突时返回DECLARED_ROTATION_LOCK_CONFLICT及inconclusive，即使采样运动量达标也不通过。该检查只覆盖直接固定组件锁定关系，不是完整约束图分析。

运动要求的结论单独保存在motion-validation.json和solve.json的motion_validation字段，重启后可通过get_run_artifacts离线读取。外层result_validity=verified描述原生数据完整性及状态恢复，不能替代motion_validation.assertion；约束冲突时可能同时出现原生数据verified和运动要求inconclusive。

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

`list_motion_studies` 的 `drive_status` 只说明驱动登记情况。`last_run` 独立回显最近一次已索引的求解状态、错误、恢复状态、结果有效性、请求时长/帧率及UTC开始/结束时间。`matches_recorded_input` 表示已记录的版本、配置、文件以及新记录中的算例类型/时长/帧率匹配，且本次观测完整、没有脏文档；这不是对任意未记录机械语义的证明。`stale` 表示至少一项输入已证实变化；`unknown` 表示脏标志、观测失败或资料不足使一致性尚未确认。单独的GetSaveFlag不能证明用户修改了仿真输入，也不能被直接忽略。

`last_run.input_match_diagnostics` 分别报告版本、配置、文件哈希、算例设置匹配情况和判定原因。顶层 `input_observation` 记录插件加载、打开、重建或枚举等步骤的脏文档观测；求解清单同时记录恢复后的观测。每阶段最多列出8个脏文档，总数独立报告。无法解释脏标志时保持unknown，不自动保存、清除标志或丢弃未保存修改。

历史保存在运行目录，检查点恢复不删除历史；恢复后版本改变会使历史过期。记录中断的任务没有伪造结束时间。alpha.4之前没有索引的任务仍可按run_id离线读取，但不自动猜测哪次是最近求解；缺失索引返回 `run_history_status=none`，损坏索引或清单返回 `unavailable`。

`preflight_motion` 明确返回 `ready_scope=basic_model_preflight_only_not_solver_compatibility`、`drive_compatibility_status=not_checked` 和 `compatibility_probe.attempted=False`。同输入曾出现原生结果不完整、求解失败或驱动幅值核验失败，且恢复已核验时，返回 `PREVIOUS_SOLVE_FAILED_SAME_INPUT`。输入尚未确认时返回 `PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED`，只提示历史失败；已明确变化或恢复未知时不输出同输入警告。不自动阻止重试，也不将失败归因为某个配合。历史成功同样不是当前相容性证明。短时探测尚未实现，不在查询或创建过程中隐式调用Calculate；即便将来支持，也须明确预算、检查点、恢复及验证范围。

`INVALID_MODEL_ID` 表示标识格式错误；`MODEL_NOT_REGISTERED` 表示该标识未在当前安装目录登记。请使用 `list_models` 或 `import_assembly` 返回的完整model_id；它不因服务重启自动过期，不能与会话内run_id混淆。

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
