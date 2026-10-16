# Solidworks_ClashMate_MechDog

SolidWorks ClashMate MechDog MCP（运动仿真）。[GitHub 项目](https://github.com/wudahua/Solidworks_ClashMate_MechDog) · [试用版下载](https://github.com/wudahua/Solidworks_ClashMate_MechDog/releases)

`v0.4.1-alpha.9`基础配合助手与运动验证试用版：让 AI 在本机 SolidWorks 中导入隔离副本，按用户选择创建基础配合，复用或创建 Motion Analysis 算例，再验证所声明的运动、导出曲线和回放截图。

**本版本公开的是运动仿真工具，暂不提供通用静态或动态干涉检查。** 修复范围及验收边界见 [发布说明](发布说明_v0.4.1-alpha.9.md)。

本版本保留另一台电脑安装反馈修复与 MCP 名称统一：增加严格 PID 校验的 COM 回退、英文安装入口、可选下载源、虚拟环境身份校验及启动诊断。

本版核对五份 2026-10-15/16 的 alpha.8 反馈，修正既有高帧率算例归零，完善配合预算、参考定位和连接诊断，并保留此前的检查点与历史结果保护。升级需重新编译执行器，并按下面的异步任务约定调用；旧版本发布包保留。

- `apply_mate`、`create_motion_study`、`convert_motion_study`、`create_model_checkpoint` 和 `reset_study_time` 默认返回 `job_id`；用 `get_job` 轮询，确认 `succeeded` 后使用 `result`。`wait_for_completion=True` 保留同步方式，显式重算归零仍返回任务。默认归零任务不会自动获得计算许可，须明确 `allow_recalculate=True`。
- 上述写操作执行器等待预算为 600 秒；这不是完成时间保证，也不能替代 MCP 客户端自身的等待限制。超时后保留原任务状态，用 `get_job` 查看 `late_response`，或用 `get_recovery_state(request_id=...)` 读取最终原始响应；无响应仍保持未知，不重复写入。`idle` 只说明请求已结束，配合是否应用看原响应与原生参数。
- 完整最终响应及其 SHA-256 保存到 `runs/requests/`；配合预览绑定模型与执行器身份，配合请求日志包含所属模型。`get_job` 可离线读取本安装目录历史任务，标注 `historical_job_read_only`，不自动续跑。旧 `queued/running` 记录的真实执行情况未知；已存结果不证明当前模型或 CAD 状态。
- `create_motion_study` 可指定 `duration_s`、`output_fps`，默认 1 秒、30 fps；仍要求新算例名，不向已有算例追加马达。创建时核验设置，试算可用另一组设置，结束后恢复原设置。重名错误给出换名或复用现有驱动的指引。
- 恢复结果的 `restore_changes` 说明算例移除/恢复、已登记驱动和参考变化；整个文件快照会回退之后新建的内容，历史结果继续保留但可能过期。无法读取当前算例时明确差异未知，不阻断必要恢复。
- `entity_id` 不按每次 revision 变化自动清空；只有查询或 inspect 返回且已登记的 ID 可使用，原生持久引用也须解析通过。恢复旧检查点会回退参考登记表，错误区分“未登记”“登记被恢复回退”和“原生参考失效”，并指引重新查询。方案 `plan_id` 的输入绑定、消费与失效保护继续保留。
- 保存诊断返回 `save_observation`，摘要只包含本次操作，最多 8 条阶段、4 KB；完整阶段与哈希按操作落盘并可离线分页读取；副本 dirty 与源文件未改动是不同观测，unknown 不自动当作 stale。日志派生状态写入一致，旧日志仅只读标注一致性，不自动解除隔离。
- 回放继续使用 `1e-7 m` / `1e-6 rad` 阈值，最差组件诊断增加各轴平移差与前后位置。钟表最终复测首帧通过，但中间帧和末帧出现 p3-33 的 Z 向漂移超限，返回 POSE_MISMATCH 并恢复副本。另一次回放曾全部通过，仍不能承诺该模型重复求解稳定；其他装配也逐次核验。
- 回放超限但副本恢复已核验时，也记录受控保存后的输入哈希和 `last_replay_attempt`，保留 `inconclusive`；恢复未知或模型版本变化不更新旧结果身份。计算后停止播放，按实际时间与全部组件姿态判断回放，不单凭 `SetTime` 布尔返回。末帧浮点值不会被内部偏移推到算例时长以外。
- 元数据原子替换对 Windows 共享读取锁作有限重试，最多约 420 毫秒；不重试求解、保存 CAD 或创建配合，持久权限错误继续失败并保留路径诊断。

- `reset_study_time(..., allow_recalculate=True)` 显式允许按原设置重新计算后归零，返回异步任务。默认对非零动画或未激活算例只读返回该选项，不先切换姿态。归零前保存检查点；失败时恢复，恢复活动算例可能需要按记录设置重建结果缓存。计算限制为 30 秒、1801 帧，超过预算拒绝；类型、时长与帧率保持并回读核对。
- 创建摆动液压缸驱动时，用 `reference_component_id` 指定缸体；验证活塞杆直线运动时也指定同一个参考。创建接口新建一个名称不重复的算例和一个马达，默认 1 秒、30 fps，不向已有算例追加驱动。`linear` 选平面法向、速度 mm/s；`rotary` 选圆柱轴、速度 rpm。
- 校验在每帧参考组件坐标系中测量运动，检查轴变化及相对转动是否在支持范围内；恒速幅值按平均和相邻采样区间核对，容差为 `max(0.001, 请求速度 × 0.5%)`，单位与请求速度相同。它不证明采样之间的瞬时速度或受力精度；方向参数通过原生回读核对，采样的正负号仍不作通用方向证明。
- `verify_motion_preservation` 的 `job.status=succeeded` 表示执行完成；是否通过看 `verification_status` 或 `assertion`。失败也保留最低行程、单位、参考系和未执行原因。独立验证返回试算前检查点；指定已应用配合方案时返回配合前检查点。
- 几何查询容忍已解析空零件，支持实体体和曲面体的平面/圆柱面，报告排除、异常及截断。固定支座可用于配合参考，但不作为驱动目标。`suggested_motor` 是兼容旧客户端的几何类型别名，不证明驱动相容；优先使用 `compatible_geometry_motor_types`。
- 两种几何查询的 `limit` 都是条数上限，还受 16000 UTF-8 字节预算限制。`detail_level="compact"` 减少冗余字段；改变筛选、分组或详情后重新查询第一页。诊断最多展示 20 个组件，另返回完整计数；需详情时按组件查询。
- `export_motion_curve(..., allow_unverified_history=True)` 显式离线导出完整、哈希与原生时间轴已核验的历史采样，保留失败/恢复未知状态及警示。默认导出仍要求当前输入匹配且结果通过验证；CAD 回放继续严格校验输入、全部组件姿态和恢复，不开放未验证回放。
- 原生求解器消息列表接口尚未完成校准，返回 `solver_messages_status=unavailable_api_not_proven`；时间轴诊断不能被解释为过约束等特定原因的证明。
- `python scripts/local_storage.py --output runs/storage.json` 只生成存储清单，不删除数据。清理须显式指定同一个 run ID 两次；默认保留 7 天，最新算例结果、活动/未知任务、恢复未确认数据、检查点和状态快照受保护。扫描不完整或服务运行时拒绝清理。

预检中的原生重建可能令副本变脏，后续保存也可能改变文件哈希；旧结果因此失效时，重新求解并使用新 `run_id`。不能用相同 revision 覆盖文件变化证据。仅查看历史数据可显式使用离线历史接口。

这是供试用的运动仿真版本。已有有效配合的刚体机构可直接进入运动流程；缺少基础配合时可由设计者选定参考和类型，再让助手执行。尚未完成“大部分机械装配均可用”的样本覆盖验收。


## alpha.9 使用变化

- 既有算例显式归零与检查点缓存恢复共用预算：最多30秒、1000fps、1801帧，保留原设置；5秒300fps可在allow_recalculate=True时重建缓存并归零。新建/运行仍最多120fps。配合初始时间阻断给出逐算例预算与参数，超预算不反复指引同一个不可行的重算操作。
- 默认配合移动预算仍为1mm/1度。装配对齐应在preview_mate显式选择两个预算参数；超预算且回滚核验后返回retry_guidance，不自动扩大预算。详见上方发布说明。
- 未解析配合摘要增加名称、ID、组件和原因；候选列表区分计数作用域、参考不支持与扫描预算耗尽。
- COM连接诊断增加进程快照。SolidWorks启动后自行消失时先从交互桌面启动并确认驻留；空快照不证明崩溃，原生退出根因仍未确定。

## 已有 alpha.8 使用变化

- 配合方案绑定 `maximum_translation_mm`（默认1mm）与 `maximum_rotation_deg`（默认1度）。`apply_mate` 在重建后、保存后提交前核验全部组件；超预算返回 `MATE_APPLY_ROLLED_BACK`，原因为 `MATE_POSE_CHANGE_EXCEEDS_CONFIRMED_BUDGET`，带移动数量和最大平移/转角。预算是产品保护策略，不是机构精度标准；较大装配调整须由用户明确选择预算、重新预览确认。健康检查通过仍不代表构型正确，`possible_redundancy` 继续提示复核，不能据此推断必然失败。
- 两种参考列表增加 `mechanical_context`：原生配合名称、ID、类型、锁旋转观测，以及精确持久面或同轴/同平面关联。compact保留标记；扫描受256配合/10秒协作预算约束，截断或参考不支持时明确 `complete=false`。这些关联不证明自由度、可驱动轴或设计意图；不自动逐轴建马达试算。
- 求解采样时间选择最多尝试两次，核验原生返回、实际时钟和停止状态；失败带 `native_steps`、帧号和请求时间，不自动重新Calculate。成功的逐帧记录保存为 `solver-time-selection.json`。偶发失败并非已证明只发生在verify，两条入口共用求解采集实现。
- 历史增加 `saved_input_match_status` 与 `live_memory_input_status`，保留四项保存输入匹配证据。`GetSaveFlag`不能单独证明机械修改，也不能排除未保存零件或配合编辑；仅有Motion Analysis算例与复脏的相关性不能证明原因。因此不清除标志、不追加隐式保存，当前内存未知时仍保留unknown。可显式检查点试算或离线读取历史。
- 创建算例返回的检查点标为 `before_study_creation`；探测旧快照缺少新算例时给出快照修订号和新建检查点指引。探测进度保留checkpoint_id，恢复日志绑定父模型；离线消费探针结果时错误码为 `PROBE_RUN_REQUIRES_HISTORY_MODE`，附 `allow_unverified_history=true` 指引。
- 临时实例的启动、连接、Motion插件加载、打开副本和清理阶段写入 `worker-phase.json`。RPC断连保持inconclusive，只有退出和原副本核验后才可显式新建探测，不自动重试未知原生操作。临时实例可能需要数十秒以上，插件加载或许可交互可能更久，无法给出固定耗时保证。
- `maximum_rotation_coefficient_delta` 是相对首帧的矩阵元素最大绝对差，无量纲；`rotary_origin_translation_mm` 是组件坐标原点相对首帧的全程最大直线距离，不是首末帧距离。旋转采用SOLIDWORKS ArrayData行基轴约定，参见[官方API说明](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IMathUtility~ICreateTransform.html)。新增原生MathUtility生成旋转与向量变换验收，不改变正确的符号公式。

## 已有 alpha.7 使用变化

- 激活动画检查点的恢复预演在**独立创建的临时 SolidWorks 进程**完成；原实例不打开探测装配，保留原生更新标记、组件/配合、配置、时钟和全部姿态的前后核验。临时进程使用明确PID，不选择用户的其他实例，不占用交互执行器互斥锁；只操作隔离副本。首次启动及插件加载有开销，不保证每次配合操作都更快。
- 兼容性探测推荐显式快照：先 `create_model_checkpoint(model_id=...)`，取得成功响应内的 `checkpoint_id`，再调用 `preflight_motion(model_id=..., study=..., compatibility_probe=True, checkpoint_id=..., probe_duration_s=1, probe_output_fps=30)`。由独立进程复制、重定向和试算该快照，不要求原工作副本打开后瞬时 `save_flag=false`；不自动保存原副本或清除修改标志。
- 快照结论明确为 `explicit_checkpoint_snapshot_not_current_unsaved_memory`，不能证明原模型后来未保存的内存编辑相容。旧检查点可能没有新建算例/驱动，须选择包含目标设置的检查点。没有显式检查点而输入脏时返回 `PROBE_REQUIRES_EXPLICIT_CHECKPOINT`，不再指引无限重复保存。结果的`saved_result_query`指向可离线读取的摘要/姿态；`probe_model_id`只属于已退出的隔离worker，不是主安装可继续控制的模型登记ID。最多1秒、121帧的短算预算不变；设置无法回读、结果过期或时间轴不完整仍是 inconclusive，不暗中扩成整段求解。
- 临时实例的PID、退出确认、原生退出码、失败和清理证据均落盘。退出未确认或原副本变化时不继续配合写入；未强杀CAD，也不自动重放AddMate。检查点预演完整证据仍在 `restorability.json`，含独立worker证据及哈希。
- `execution.stage_timings`、`total_elapsed_ms` 使用单调时钟记录配合准备、探测、原生添加、重建及回滚。诊断优先展示新增配合的错误落点，并分别报告 `add_mate_status`、`rebuild_status` 与 `transaction_outcome`。`swAddMateError_e` 的值1表示原生添加调用成功；后续特征健康失败属于不同阶段/错误码域，可以同时成立，不代表事务已提交。
- 默认长操作等待600秒，可在客户端服务环境中设置 `SW_MCP_LONG_OPERATION_WAIT_S`（60–3600，重启MCP生效）。等待超时不是原生COM取消：响应标注 `client_wait_expired=true`、`cad_operation_finished=false`，继续通过原任务读取迟到结果。不要重试写入或删除隔离日志。
- `upgrade.ps1 -DryRun` 与实际升级共用基础Python、既有venv、SW Interop DLL、x64编译器和目标目录访问检查，并核验执行器租约。环境错误在替换源码前拒绝；DryRun不保证未来pip网络、原生编译及安装一定成功。`-PythonPath` 必须是基础Python，此要求早于alpha.6；SW路径按显式参数、`SW_INSTALL_DIR`、默认安装目录解析，非默认安装需正确配置。
- 发布清单列出的文本统一LF，`.editorconfig`约束编辑器；构建和CI拒绝CR行尾。仍按准确字节核验，不把CRLF/LF差异归一化成通过。旧版本包与标签不替换。
- 姿态CSV的 `r00...r22` 保持SolidWorks ArrayData的**行基轴**约定，三行是局部X/Y/Z轴在目标系的分量；行向量通过右乘矩阵变换。现有旋转增量已在声明的参考坐标系，不翻转符号或再转一次全局。`signed_net_travel` 是相对声明轴的正负量，`direction_verified=false` 仍表示未独立认证马达箭头方向。新增倾斜安装、正反向及独立基轴叉积回归。

## 沿用 alpha.6 的功能

- `apply_mate` 的检查点准备、恢复预演、重建和写入纳入同一事务。准备失败且原副本已核验时返回未写入错误；恢复或清理未确认时仍要求恢复。已进入准备阶段的方案被消费，失败后重新预览，不自动重复写入。
- 检查点恢复证据继续核验原姿态、机械输入与文件哈希；alpha.7将恢复预演迁入独立实例，原实例变化仍拒绝。
- 求解与运动验证返回 `history_usage`，提示后续写入/恢复可能使当前绑定失效，并给出离线摘要及曲线读取方法；不删除旧run，也不放松当前输入校验。驱动候选每项（含compact）明确未验证机构相容性并给出几何类型警示，列表统一列出单位。

- 含虚拟组件的装配默认在导入时拒绝，诊断会区分虚拟引用线索与真正缺失的外部零件；不应去旧机器临时目录寻找内嵌零件。可先在自己的装配副本中“保存零件（在外部文件中）”，也可显式调用 `import_assembly(path, materialize_virtual_components=True)`。自动外部化首批只覆盖单配置、全部已加载的顶层实体/空零件装配，最多32个虚拟组件；不支持虚拟子装配、多配置虚拟零件、曲面体或未隔离的虚拟派生/外部依赖。转换、保存和重开核验成功后才允许后续运动操作。
- 外部化可能改变组件名称、持久引用和模型ID；使用返回的model_id及重新检查后的component_id/entity_id。`materialization.conversions` 给出名称和原生引用迁移，最多20组，完整证据在登记目录。失败的 `import_status=incomplete` 副本只作为诊断保留，不能运行运动；复制阶段中断而尚无初始检查点时仍需人工检查隔离副本。
- 旧整数PID配置不会自动迁移。建议在客户端服务配置中选择 `SW_MCP_PROCESS_ID=auto` 并重载；同一服务的首次握手明确失败且进程已结束时，可显式 `get_environment(solidworks_pid="auto")` 或传正整数PID字符串纠正。已有CAD派发、超时、unknown或成功会话不能通过此入口改实例；不会编辑WorkBuddy全局配置，也不停止旧进程。
- `list_motion_studies(model_id, inspect_native_drives=True)` 可以增加原生马达特征及参数观测，不激活或求解。全装配特征可能跨多个算例，`study_membership_status=unproven` 不能视为当前算例的马达清单。按算例API返回null仍保持unknown；激活不能保证枚举成功。
- `replay_motion_frame(run_id, frame, diagnostic_limit=20)` 默认展示最多20个最差组件，另受12000字节行预算限制；全部组件均参与姿态判定。排序使用 `max(平移差/平移门槛, 旋转角差/旋转门槛)`，并按实例名处理并列。要查看完整已保存诊断，用 `get_run_artifacts(run_id=..., replay_diagnostics=True, limit=20)`，再按返回cursor分页；不重新求解。旧版只存前五条时无法凭空补齐。
- 求解摘要的 `component_motion_overview` 是采样运动观察，固定组件不参与从动件静止提示；未登记原生驱动的目标保持unknown。`REGISTERED_TARGET_MOVED_OTHER_MOVABLE_COMPONENTS_NOT_DETECTED` 不是缺陷判定，也不自动建议改摩擦或约束。
- 同一安装目录的多个MCP服务不能同时持有CAD日志租约；各安装目录还共享执行器互斥锁，交互CAD控制只能由一个执行器承担；其内部临时探测worker只连接自己新建的实例。历史摘要、姿态、保存观测、既有图像及恢复日志的离线只读入口无需启动CAD执行器。不能通过删锁或改unknown日志开启并行写入。

## 已有 alpha.5 使用变化

以下为已发布alpha.5的兼容行为。

- 最低行程的浮点尾差有受限数值预算，回显实测、门槛与残差；这不是机械精度容差。
- `inspect_model` 返回 `registered_supported_inspected_face` 的面可直接用于配合或适用驱动，不用重复登记查询；失效引用与不支持的组件仍拒绝。检查不自动改配合或猜运动意图。
- `preflight_motion` 的 `basic_input_ready` 和兼容 `ready` 仅表示基础检查；`solver_compatibility_status=not_checked` 不能显示为求解保证。默认预检会重建副本，dirty 观测保留。
- 显式 `compatibility_probe=True` 指定算例、`probe_duration_s`（最多1秒）和 `probe_output_fps`，在另一个副本异步短算；可按上面的alpha.7流程显式指定检查点，返回 `job_id` 后用 `get_job` 查询。结果只覆盖该输入/短区间，网格异常为 inconclusive，原副本须核验不变。原副本核验失败时按响应中的原模型和检查点恢复；临时实例退出未确认时先核对worker进程及完成证据，不将隔离worker的probe_model_id当作主安装的模型登记。
- `SW_MCP_PROCESS_ID=auto` 或 `start.ps1 -AutoDetect` 可在每次服务启动时选择唯一、身份可核验的同用户会话实例。多个进程（含辅助实例）不按窗口标题猜选；仍可指定整数PID。已有会话丢失或 unknown 不能自动切换后继续写入。
- 旧 journal 的原值在 `observed_dispatch_state`，兼容 `dispatch_state` 给当前派生值；`journal_schema_version` 与响应schema区分。只读显示不会把磁盘日志重写为idle。
- 对原生未登记驱动，`drive_validation=null` 表示没有本项目的独立速度核对；不等于模型没有马达。矩阵系数差为全部组件/帧/矩阵元素的 `max|R_ij(t)-R_ij(0)|`，无量纲，不是角度。

## 原地升级

先停用旧安装目录的MCP服务，保留SolidWorks打开；从新包目录调用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\upgrade.ps1 -SourcePackage 'C:\Downloads\Solidworks_ClashMate_MechDog_v0.4.1-alpha.9_source.zip' -TargetDir 'C:\MCP\ClashMateMechDog' -PythonPath 'C:\Python312\python.exe' -DryRun
# PythonPath填写基础Python；非默认SolidWorks安装请同时指定-SolidWorksInstallDir。
# 预检通过后移除-DryRun；未来网络及编译仍可能失败，保留自动回滚。
```

ZIP与同目录`.sha256`须来自可信发布页。升级先核验清单/哈希/版本，备份将替换的源码与执行器；保留`.venv`、`runs`、`experiments`及未知恢复记录。安装校验基础解释器和旧venv身份后按锁定依赖重新编译。编译失败记录源码/二进制回滚；依赖环境变化不属于快照回滚。备份与收据在`upgrade-backups/`。不自动替换客户端全局配置、不终止用户进程或删除原恢复日志。

ZIP与边车的文件名须逐字对应，浏览器自动加后缀或本地重命名也会被拒绝。报错会给出期望名称与本地名称；将ZIP恢复为边车记录的名称，并将边车命名为该ZIP文件名加`.sha256`，再重试；内容哈希仍须一致。

源码包解压根目录统一为 `Solidworks_ClashMate_MechDog/`；新版升级器同时接受历史 `SolidWorksMotionMCP/` 包，拒绝混合根目录。从新包目录运行升级器，旧安装的升级器不保证理解新版包格式。安装完成后再次逐字节校验，收据必须有 `source_integrity_verified=true` 才算提交成功；失败则按收据记录回滚。

### Git既有检出的行尾差异

`python scripts/verify_release.py` 保持精确字节和SHA256校验。若所有源码差异仅由CRLF/LF转换造成，会以非零退出码返回 `LINE_ENDING_MISMATCH`，列出全部差异文件、实际/期望字节数与哈希；若还存在文本修改，则保留 `RELEASE_SOURCE_MISMATCH` 并逐文件区分原因。编码、BOM、空白或代码改动不会被当成行尾差异放行。

`.gitattributes` 的 `* -text` 保护新检出的原始字节，但新增该文件或改变Git设置不保证已存在文件被重写。先备份自己的源码改动，使用可信ZIP及边车，按上面的 `upgrade.ps1` 流程恢复精确源码并重新编译；自动备份保留旧字节，`.venv`、`runs`、`experiments`及unknown日志保持。不要为排除这个诊断直接删除文件、强制reset或重建Git索引。标准ZIP安装正常情况下不需要行尾修复。

### 无CAD的持续集成检查

Windows CI除清单及 `test_*.py` 外，增加 `tests/alpha5_evidence_checks.py` 的18项与 `tests/session_connection_checks.py` 的30项生产策略检查。两者离线路径不需要安装SolidWorks或复制Interop DLL，使用Windows自带.NET编译器。`--solidworks-pid` 原生验证仍须操作者显式选择，在有SolidWorks的开发机执行，不放进无CAD CI。本地通过不代表尚未运行的远端CI已通过。

同目录升级继续使用原路径与数据；另目录安装不会自动迁移绝对路径登记。名称仍为`SolidWorks ClashMate MechDog`/`solidworks-clashmate-mechdog`。

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
| Python | 64 位 Python 3.11+；完整开发验收使用 3.12.14。用户报告 3.13 安装、编译及连接成功，运动求解/配合/恢复的 3.13 验收待完成，建议先用 3.12 |
| 编译 | .NET Framework 4.8 的 x64 C# 编译器，引用用户本机 SolidWorks interop |
| MCP SDK | 固定为 2.3.0，依赖版本见 requirements.lock.txt |

当前开发机 Windows 10 实测不能作为 SolidWorks 2026 官方系统兼容证明。官方系统要求显示 Windows 10 最后支持版本为 SolidWorks 2025 SP5。[官方系统要求](https://www.solidworks.com/support/system-requirements)

其他 SolidWorks revision 可连接、读取环境，首版拒绝未校准版本的通用求解和新建驱动。跨版本适配尚未验收。不要把 Motion Analysis、Basic Motion 和动画视为相同求解器。[官方算例类型说明](https://help.solidworks.com/2025/english/SolidWorks/motionstudies/c_deciding_which_motion_study.htm)

## 安装

解压到有写权限的短路径，例如 `C:\MCP\ClashMateMechDog`，避免直接放在 Program Files。所有运行结果和隔离副本保存在安装目录的 `runs/` 与 `experiments/`；很长的安装路径或CAD文件名可能触及Windows路径长度限制。

```powershell
# 在解压后的项目目录执行；PythonPath 填自己的 Python 路径。
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PythonPath 'C:\Python312\python.exe'

# 如果 SolidWorks 安装在其他位置：
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PythonPath 'C:\Python312\python.exe' -SolidWorksInstallDir 'D:\SOLIDWORKS'

# 不进入 COM 的安装自检
.\.venv\Scripts\python.exe .\scripts\self_check.py
```

安装脚本默认从 PyPI 安装固定版本依赖，并从本机安装目录引用 DLL。网络环境需要镜像时，可追加 `-PipIndexUrl 'https://pypi.tuna.tsinghua.edu.cn/simple'`，由用户选择可信 HTTPS 源；依赖锁定和 TLS 校验保持生效。发布包不附带 SolidWorks 程序、授权、interop DLL 或预编译执行器。

`-ExecutionPolicy Bypass` 仅对这次启动的 PowerShell 进程及其子进程生效，不永久改变用户或计算机策略，也不能覆盖企业组策略。脚本仍被阻止时先运行 `Get-ExecutionPolicy -List`，核对 `MachinePolicy`/`UserPolicy`，由管理员按组织规定处理。[微软执行策略说明](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_execution_policies)

`-PythonPath` 应指向基础 Python，而不是另一虚拟环境。已有 `.venv` 会核对实际版本、64 位架构、项目目录和基础解释器；不匹配或目录不完整时先停止安装并输出诊断，不自动删除或覆盖。可选择与已有环境匹配的基础 Python，或由用户保留/移走旧 `.venv` 后重新安装。中文 `初始化环境.ps1`、`启动MCP.ps1` 继续转发至英文入口。

若解压后中文文件名乱码，先核对下载包 SHA256 和解压工具。已核验 `v0.4.1-alpha.1` 官方源码资产的中文条目为 UTF-8 且标志位正确；不要强制按 GBK 转换。可以用 Windows PowerShell `Expand-Archive` 解压原 ZIP，并保留文件哈希、工具版本和命令供排查；本版本提供 `install.ps1`/`start.ps1` 英文入口。

启动 SolidWorks 后，在相同 Windows 用户和桌面会话运行服务；双方权限级别应一致。只允许一个执行器运行。多个 SolidWorks 实例时必须选择 PID：

```powershell
Get-Process SLDWORKS | Select-Object Id, ProcessName
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -SolidWorksProcessId 12345
```

将命令登记到支持 stdio MCP 的客户端。示例路径必须改为本机路径；整数 PID 模式填本机值，auto 模式核验唯一实例；服务 stdout 只承载 MCP 协议。

项目统一使用显示名 `SolidWorks ClashMate MechDog`（协议 `serverInfo.name`）和配置键 `solidworks-clashmate-mechdog`（`mcpServers` 下的服务标识）；GitHub 仓库及目录名仍为 `Solidworks_ClashMate_MechDog`。两项 MCP 名称采用空格显示和小写连字符标识的同一品牌。已安装的旧包不会自动改名；在 WorkBuddy 的 `mcp.json` 中把原服务键 `solidworks-motion` 或 `solidworks-clashmate` 改为 `solidworks-clashmate-mechdog`，保留该条目的路径、参数和环境变量，并让客户端重新加载该服务。替换原条目即可，避免同时保留两个指向同一项目的服务。协议显示名由服务源码决定，升级至本版本并重新加载服务后才会更新。

```json
{
  "mcpServers": {
    "solidworks-clashmate-mechdog": {
      "command": "C:\\MCP\\ClashMateMechDog\\.venv\\Scripts\\python.exe",
      "args": ["C:\\MCP\\ClashMateMechDog\\motion_server.py"],
      "env": {"SW_MCP_PROCESS_ID": "auto"}
    }
  }
}
```

示例使用显式自动模式；多实例时把 `auto` 改为所选整数PID。

同样的配置可从 [mcp-config.example.json](mcp-config.example.json) 复制；请替换路径和 PID，项目不会自动修改 WorkBuddy 的全局配置。

可先在终端运行 `.\.venv\Scripts\python.exe .\scripts\self_check.py --connect`；此前通过 `$env:SW_MCP_PROCESS_ID='12345'` 选择实例。交互会话由用户启动和选择；检查点与兼容性探测会启动并关闭自己创建的临时SolidWorks实例，不关闭用户实例。

连接优先使用 PID 注册项；选定 PID 缺少注册项时，才尝试 `GetActiveObject`，并严格核对返回实例的 PID 和可读 revision。不一致返回 `COM_SESSION_ID_MISMATCH`，不发送 CAD 请求。未配置 PID 且没有 PID 注册项时要求用户明确选择；通用活动对象不代表只有一个实例。连接诊断仅输出相关 PID、注册项总数、连接方式和 HRESULT，不列出其他应用的 ROT 对象名称。

只检查 COM 连接、不加载模型登记、不改 `UserControl` 或加载 Motion 时，可运行 `.\executor\bin\SwExecutor.exe check-connection`。安装自检输出 JSON，失败返回非零退出码；`connection_checked=true` 只表示真实环境查询成功。`self_check.py --connect` 使用正常执行器握手，并受已有恢复隔离记录约束。

执行器缺失返回 `EXECUTOR_NOT_BUILT`，可重新运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\executor\build.ps1`。`EXECUTOR_ACCESS_DENIED` 表示启动或文件访问被拒绝，重新编译未必解决；请对比真实 MCP 客户端与 Agent 子进程的启动结果，并保留 `runs/executor.log` 和自检 JSON。`MCP_LEASE_UNAVAILABLE`/`EXECUTOR_LOG_UNAVAILABLE` 则先检查安装目录写权限。编译后生成 `executor/bin/build-manifest.json`，记录 EXE 大小、哈希、源码哈希和时间；没有证据时不把错误归因于杀毒软件、沙箱或 SolidWorks。

## 第一次使用

1. **先启动本机 SolidWorks 并保持打开**，选择正确 PID。保存原装配及全部零件。源文件存在未保存修改时导入会拒绝；虚拟零件先保存到磁盘。确认装配在 SolidWorks 中能按设计意图运动。
2. 调用 `get_environment`，确认 revision 与 Motion 使用条件。
3. 调用 `import_assembly`，传入 `.SLDASM` 绝对路径和可选配置。返回 job_id 后用 `get_job` 等待完成，保存结果中的 model_id 和 checkpoint_id。
4. 调用 `inspect_model`、`preflight_motion`、`list_motion_studies`。
5. 已有 Motion Analysis：直接选算例，并查看 `last_run` 及其输入匹配状态。已有动画/Basic Motion：明确请求 `convert_motion_study`。没有驱动：调用 `list_drive_candidates`，由用户选择组件、参考实体、速度与方向，再 `create_motion_study`。转换和创建默认返回 job_id；等待 get_job 状态为 succeeded 后读取 result，其中包含实际时长、帧率和算例状态。**预检通过或驱动创建成功不保证驱动与配合相容，也不保证求解成功。** 旋转驱动与现有约束不相容时可能只有初始结果，需核对约束和设计意图；直线驱动只可在适用机构中作为对照，不能通用替代旋转驱动。
6. 调用 `run_motion_study`，用 `get_job` 查询。成功结果包含 run_id、时间轴验证和驱动验证范围。复用已有算例时不声称已独立证明物理结果。
7. 调用 `export_motion_curve` 或 `replay_motion_frame`。CAD 回放和默认曲线导出要求当前会话模型输入匹配。重启后可通过 get_run_artifacts、read_run_poses 或显式历史导出读取保存数据；历史记录不证明当前 CAD 状态。

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

配合操作要求各算例时间为0；需要时先显式reset_study_time。用户明确选定两个参考、类型及参数后，先preview_mate，再apply_mate(confirmed=True)，等待返回的 job_id 成功并核对原生参数。方案绑定文件哈希、配置、版本、文档更新标记/脏标志、姿态、算例状态及配合清单；保守地在状态变化后拒绝执行。本会话最多128个方案，执行过的方案不能重放，重连后须重新预览。apply_mate会保存登记副本以建立检查点，不保存源装配。

新增配合成功后仍须验证运动。先选择运动组件、参考轴、算例和minimum_travel，再显式verify_motion_preservation。旋转的最低运动量为deg，直线为mm；返回assertion=pass/fail/inconclusive，不能仅凭job成功判定通过。直线验证检查沿轴位移跨度、偏轴位移和伴随旋转；旋转验证检查累计投影角跨度及偏轴旋转，允许偏置组件原点沿圆周移动。默认偏轴容差为直线0.01mm/旋转0.1deg，直线伴随旋转容差0.1deg。这些是首版验收阈值，不是通用机构精度认证。

要比较配合前后运动，先run_motion_study取得当前模型已验证基线，再preview_mate传入baseline_run_id，应用后以该plan_id调用验证；组件、算例、时长及帧率须一致。前后运动量差容差为基线的5%，下限旋转0.1deg/直线0.01mm。模型再次修改会使plan_id验证失效。无基线时仅验证当前运动要求，不声称运动相对修改前已保留。

运动验证会恢复求解前状态，但不会因验证失败自动删除新配合。保留方案返回的checkpoint_id，由用户决定restore_model_checkpoint。求解不完整、采样歧义或恢复失败不能判定通过；未知恢复继续隔离。已有未登记快速驱动可能产生采样混叠，即使通过也不证明未采样运动或整个机构自由度正确。

本机反例中，固定支座与转轴的同心配合原生LockRotation=True，但Motion Analysis仍返回了转轴旋转数据。验证器核对直接连接固定组件的原生锁旋转配合，发现声明旋转与锁定约束冲突时返回DECLARED_ROTATION_LOCK_CONFLICT及inconclusive，即使采样运动量达标也不通过。该检查只覆盖直接固定组件锁定关系，不是完整约束图分析。

运动要求的结论单独保存在motion-validation.json和solve.json的motion_validation字段，重启后可通过get_run_artifacts离线读取。外层result_validity=verified描述原生数据完整性及状态恢复，不能替代motion_validation.assertion；约束冲突时可能同时出现原生数据verified和运动要求inconclusive。

公开求解与新建驱动最多 30 秒、1801 帧、500 个组件和 10 万条组件姿态；帧率 5–120。既有算例归零/缓存恢复采用上方单列预算。新建旋转驱动要求每帧小于等于 45°，避免角速度微分歧义。已有快速驱动可能发生采样混叠，应提高帧率并另行校验。

默认导入拒绝虚拟零件。显式外部化的限制见下文；丢失引用、SpeedPak、未解析组件及未验收的柔性子装配会被拒绝。刚性嵌套装配、重复实例、复杂配置和外部参照的代码路径仍需扩大样本验收；首版不据此承诺通用支持。接触、弹簧、凸轮或多个驱动可通过已有算例尝试运行，但其物理精度与求解稳定性不在首版认证范围内。

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

默认 `preflight_motion` 明确返回 `ready_scope=basic_model_preflight_only_not_solver_compatibility`、`drive_compatibility_status=not_checked` 和 `compatibility_probe.attempted=False`。同输入曾出现原生结果不完整、求解失败或驱动幅值核验失败，且恢复已核验时，返回 `PREVIOUS_SOLVE_FAILED_SAME_INPUT`。输入尚未确认时返回 `PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED`，只提示历史失败；已明确变化或恢复未知时不输出同输入警告。不自动阻止重试，也不将失败归因为某个配合。历史成功同样不是当前相容性证明。显式 `compatibility_probe=True` 可在另一个隔离副本短算，默认1秒；预算、检查点、恢复及结论范围见上文。默认查询或创建不隐式调用 Calculate。

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

已纳入发布的 2026-10-14 修订：公开工具仍为 24 个。

QZC 更新验收反馈修订：

- `apply_mate` 的 `execution` 分别记录原生对象返回、特征确认、重建、参数核验、保存和提交；`null` 表示该项未检查。`swAddMateError_e` 中 **1 为成功，5 为装配过定义**。过定义原因为 `MATE_OVERDEFINED`，外层保留 `MATE_APPLY_ROLLED_BACK` 及 `rollback_verified`，与创建后重建失败区分。旧 `mate_created` 只表示对象非空，不能当作提交成功；更改参数仍须新预览和确认。
- 写响应的 `save_observation.scope=current_operation`，摘要最多 4 KB，只含本次操作；嵌套检查点保留同一 `operation_id`。完整阶段和哈希分别存入模型目录 `save-observations/`。用 `get_run_artifacts(model_id=..., operation_id=..., limit=5)` 离线分页读取，完整哈希需 `include_file_hashes=True`，响应最多 16 KB；过大的单条记录给出摘要和原文件路径。升级时原累计观测按原字节归档，摘要中的 `archived_legacy_query` 提供 `legacy_` 加 SHA256 的查询标识，不伪造旧操作身份。
- 默认 `replay_motion_frame` 仍要求本会话 run 与当前输入匹配，重算、核验全部组件并恢复。通过后登记独立文件名的 BMP、帧时间、姿态 CSV 哈希、图像哈希和核验范围；`get_run_artifacts(run_id=...)` 列出最近 5 个已登记图像。`replay_motion_frame(run_id, frame, saved_image_only=True)` 可在重启或恢复隔离时读取该帧既有截图，不调用 COM。它不能生成未拍摄的帧；旧无清单 BMP 不自动升级为已核验图像。任意旧输入重新回放仍需未来的不可变输入快照功能。历史图像不证明当前 CAD 或独立物理精度，也不保证所有组件在画面中可见。
- `inspect_model.reference_guidance` 给出本模型的查询路线，配合实体外层也列出 `entity_id` 和几何类型。以实体的登记状态为准：支持的返回面经核验自动登记，其他参考仍需查询且不得自动改绑。驱动查询需找指定面时可用 `group_faces=False`，避免只返回等价几何组的代表面。

恢复字段判读：`status=idle/active/unknown` 分别表示日志中的请求已结束、执行中、未确认；不是机械姿态认证。`current_request_state=completed/dispatching/unconfirmed` 是相应的当前请求状态。`observed_dispatch_state` 保留旧日志原值；`dispatch_field_consistent` 和 `recovery_field_consistent` 分别核对两个派生字段，`journal_derived_fields_consistent` 是两者均一致。旧日志不一致不会自动重写或解除隔离。

`state_scope=current_owner_request_in_progress` 对应本服务请求执行中、`cad_request_policy=wait_for_current_request`；`state_scope=idle` 对应日志 idle、`cad_request_policy=available`；旧或未知请求使用 `prior_or_unknown_operation` 和 `recovery_only`。恢复未知时仍须明确选择检查点并核验恢复；`idle` 不等于配合已提交或运动通过。

客户端配置键更名与历史目录分别处理：同目录升级只替换原键、保留 command/args/env 并重载；换安装目录会形成另一套存储。离线 run 数据可按该目录读取，执行器内 run 缓存不跨会话迁移。模型清单含绝对路径与原生引用，不要只改 JSON 路径就用于 CAD 恢复；目录迁移必须重新登记、重定向及核验隔离。

单位保持原协议：几何坐标 `m`、面积 `m²`、配合距离和直线运动门槛 `mm`、直线驱动 `mm/s`、旋转驱动 `rpm`；导出曲线按 quantity 标明 `m`、`m/s` 或 `rad/s`。内部 API 换算保持不变。几何候选只说明可用的参考类型，相容性仍为 `not_checked`；平动组件上的圆柱孔不代表推荐给该组件加旋转驱动。

- 添加配合前，对激活动画的检查点在另一份独立副本中预演恢复；时间、全体姿态、原副本文件及配合未通过核验时拒绝写入。旧液压反馈检查点仍无法完整恢复记录姿态，此限制没有消除。首次覆盖为顶层刚体零件；激活动画的多层装配会明确拒绝预检，不能假定安全回滚。
- `get_motion_summary(run_id, allow_unverified_history=True)` 可在服务重启或 CAD 隔离时离线查看历史摘要；曲线使用同名选项。历史哈希通过不代表当前模型匹配或物理验证通过。当前 CAD 回放仍要求版本及文件哈希匹配。
- 配合预览检查相同持久化面参考、类型、方向及支持的参数是否确定重复。相同组件对上的其他配合会提示复核；边与面不能自动判等，距离配合参数尚不用于确定判重。`inspect_model` 已登记的受支持顶层面可直接使用；其他参考通过 `list_mate_references` 查询对应页面。
- 显式归零会改变登记副本。查看 `previous_time_s`、`target_time_s`、`pose_change`、`operation_state` 和 `pre_operation_pose_restored`；兼容字段 `restoration_status=restored` 不能单独解释为归零前姿态已恢复。
- 恢复状态返回原始 `observed_dispatch_state` 和当前 `current_request_state`，旧日志矛盾会标出而不会改写。替代会话仍须明确传入 `allow_replacement_session=true`，并核验旧实例已退出。
- `experiments` 在首次生成示例或导入装配时创建；安装后暂时不存在是正常情况。JSON 构建清单写入无 BOM UTF-8，读取仍兼容旧清单。
- PID 可在 PowerShell 用 `Get-Process SLDWORKS | Select-Object Id, MainWindowTitle` 查询，再填入客户端配置。窗口存在不代表 COM 已就绪；多实例仍必须核对实际 COM PID。

当前开发机确认是 Windows 10 19045；Python 实际版本以 `scripts/validate_runtime.py` 输出为准，不按目录名判断。未将第三方报告的 Windows 11 环境记为本机验收。动态钟表的单次成功案例不消除重复求解漂移限制；超限仍返回 inconclusive。

1. Windows 11 独立机器安装、MCP 客户端关闭与恢复回归。
2. 刚性多层子装配、重复零件不同配置、轻量化及外部参照样本矩阵。
3. 配合诊断与驱动向导：明确欠约束/过约束原因、多候选选择、方向预览；保留用户确认设计意图。
4. 扩大机构样本：铰链、滑台、曲柄滑块、齿轮与带链传动、凸轮等；按通过的样本发布支持范围。
5. 更多 SolidWorks revision 单位与时间采样适配；之后再推广通用干涉与参数闭环。

MIT 许可覆盖本项目代码。SolidWorks 及其运行组件由用户自行安装并授权。
