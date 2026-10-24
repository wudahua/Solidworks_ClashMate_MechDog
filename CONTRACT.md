# AI 客户端与开发者契约

本文件随源码包交付。正式入口为 `motion_server.py`，协议握手名称为 `SolidWorks ClashMate MechDog`，推荐配置键为 `solidworks-clashmate-mechdog`，共30项工具。实际字段、枚举和默认值以当前连接的 `tools/list` 为准；不要用历史发布说明替代当前 schema。

## 输入与单位

所有工具输入均为封闭 JSON 对象（`additionalProperties=false`）；未知键拒绝，不改名、不丢弃。原始 JSON 按 schema 校验，布尔值不能代替数字，字符串不能代替数值，枚举非法值及非有限数值拒绝，返回 `INVALID_ARGUMENT` 或相应专用参数码。只有 schema 明确允许时才可传 null；空字符串与 null 不等价。

| 范围 | 约束 |
| --- | --- |
| 对话 `task_kind` / `motion` | `motion`或`concentric` / `rotary`或`linear` |
| 对话运动 | `0 < duration_s <= 5`，整数 `5 <= output_fps <= 120`，`duration_s * output_fps <= 600`，最多601帧；还须满足原生网格准入规则 |
| 对话速度 | 旋转 `0 < speed <= 6000` rpm；直线 `0 < speed <= 500` mm/s；方向用布尔 `reverse_direction` |
| 对话最低行程 | 0至理论行程；0采用理论行程95%；旋转为度、直线为毫米 |
| 圆边同轴任务 | 固定12rpm、1秒、30fps；一个浮动件与一个固定件，默认保留旋转；其他运动参数明确拒绝 |
| 几何查询 `geometry_scan_budget_s` | 默认10，1–60秒有限数值 |
| 几何查询 `mate_context_budget_s` | 默认10，1–30秒有限数值 |
| 几何查询 `limit` / `face_offset` / `edge_offset` | limit为1–50整数；偏移为非负整数，edge_offset仅配合引用查询可用；字节预算可能缩页 |
| 任务ID | 32位小写十六进制；AI管理；未知时不传ID查询现有任务，不猜造ID |
| 原有低层工具 | 各自还有参数与预算校验；不能把对话5秒预算外推给低层工具，也不能把低层预算用于对话任务 |

短网格拒绝保留完整诊断及建议，AI核对帧数、帧对齐和实际时长后再提出参数；不自行改参数重跑。方向只证明相对所选原生轴线及反向开关的符号，不推断未说明的机械意图。

## 对话任务、授权与恢复

`get_mechanism_task`查找或读取任务；无任务时`prepare_mechanism_task`创建专用实例与副本；`plan_mechanism_task`生成方案；人工明确确认后`execute_mechanism_task`一次执行；`finish_mechanism_task`默认恢复导入检查点并核对资源退出。一次性令牌只绑定该任务和方案；缺少任一确认不得消耗令牌、排队求解或写入。

prepare/plan/execute/finish可能返回 `{ok:true,result:{task_id,accepted:true,next_tool:"get_mechanism_task"}}`。**受理不等于执行或验证成功**。get返回任务快照，检查`busy`、`phase`、`verification`、`error`和`finish`。常见阶段为`preparing`、`proposal_ready`、`awaiting_component_selection`、`planning`、`awaiting_confirmation`、`running`、`verified`、`verification_failed`、`failed`、`recovered`、`finishing`、`closed`、`closed_with_cleanup_warning`、`closed_unverified`；阶段清单不是放行规则，须同时检查具体证据。

后台失败位于成功查询的`result.error`，采用与同步`error`相同的分类与`next_action`；不能只检查外层`ok=true`。名称歧义可进入`awaiting_component_selection`，AI解释候选后将自然语言选择交给plan复用副本。几何排序不证明意图。

`confirmed`和`scope_confirmed`默认false。不得因工具返回了查询提示、存在候选、或已有旧授权，就自行把它们改为true。`keep_result`仅适用于已验证成果；与`close_unrestored`互斥。关闭失败记录需另行明确同意；旧资源身份、退出与空闲日志未证明时继续阻断。归档失败不等于恢复成功。

客户端重连可继续原宿主的活任务；宿主丢失时只能读旧记录，不能从JSON重建COM或复用旧令牌。`get_recovery_state`与`restore_model_checkpoint`仅可对原受管活连接、已结束旧请求、原实例身份与导入检查点一致的任务恢复。恢复独立核对姿态、固定状态和配合数，并撤销旧确认。超时不代表CAD已停止。新源码不得接管活任务。

## 错误信封与下一步

任务同步拒绝及后台失败保留：`code`、`message`、`assertion`、`restoration_status`、`document_context_restoration_status`、`diagnostics`、`next_action`。`next_action`包含`automatic_retry:false`、`options:[]`、`options_status`、自然语言`instruction`，必要时给出`tool`、`arguments`和恢复查询。**出现tool只是路由提示，不代表参数需要用户输入，也不表示已经获准执行。人工确认分类优先于工具提示和选项。**

`assertion`为`pass`、`fail`或`inconclusive`；派发前输入/授权拒绝可为`not_applicable`。任务错误不据错误码推断已经恢复：`restoration_status=unknown`仍保留；`diagnostics.cad_dispatched`和`job_created`在结果未知时为null，不得解读为false。确认/参数门禁已证明当前请求未派发时为false，也不证明之前任务已恢复。后台错误不能因名字像参数错误就声称未触及CAD。

低层运行结果仍分别报告执行、采样断言、恢复和源文件状态。`verification.declared_scope_passed=true`不代表完整轨迹等价、整机自由度或物理接触精度通过。原生退出码非零的清理警告不等于正常退出。历史低层离线工件读取错误仍可能只有code/message/assertion/restoration_status；客户端应检查字段是否存在，不补造缺失的恢复或下一步证据。

分类表由`sw_mcp/task_errors.py`与`sw_mcp/errors.py`实现；新增任务错误出口由AST穷举测试守护。任务分类如下（同一分类有多个错误码）：

| options_status | AI处理原则 |
| --- | --- |
| `explicit_human_confirmation_required` | 向用户解释具体方案、机械范围与恢复或保留方式，取得明确授权；不得自行把确认字段改为true，不自动重试写入。 |
| `user_parameter_correction_required` | AI核对工具声明、字段范围及原调用；定位文件或修正参数后显式调用。仅机械选择或授权确有必要时询问用户，不要求用户手抄ID或命令。 |
| `mechanical_selection_required` | AI用现有候选的名称、角色、位置及轴线解释歧义，请用户以机械用途或名称澄清；复用当前副本，不把几何排名当设计意图。 |
| `task_state_review_required_no_write_retry` | AI读取已有任务的阶段、busy和结果；运行中只查询，完成后安全收尾。不要重复prepare或execute，也不通过重启绕过一次性执行保护。 |
| `fresh_task_plan_required_no_write_retry` | AI核对原任务、已选零件对、引用和一次性令牌；旧方案失效。先读取现场并按安全收尾结论决定重新规划，新方案须重新确认，不换绑旧基线或重放写入。 |
| `task_record_selection_required` | AI不传task_id调用get_mechanism_task查找现有记录；不猜测ID，不因找不到记录就重复创建或执行任务。 |
| `task_owner_recovery_review_required` | AI读取旧任务、原资源身份和现有恢复记录；不能从JSON重建COM、重放令牌或自动关闭失败记录。只有明确授权且资源退出证据齐全时才可异常归档，恢复仍按未验证报告。 |
| `native_outcome_review_required_no_write_retry` | AI读取原请求、归属和恢复日志；超时或进程存在都不证明请求结束。未知状态不重试写入、不自动恢复或强制结束；原请求结束且同一活连接核对通过后才提出恢复。 |
| `mechanical_evidence_review_required_no_parameter_change` | AI读取已有初态、轨迹、组件身份和验证证据，报告不完整或不一致；不是简单参数错误，不放宽容差、改绑基线或为补诊断重复求解。 |
| `supported_mechanical_scope_review_required` | AI说明当前受支持的零件、引用及验证范围，依据现有证据推荐可行方案；不自动解固定、替换几何或声称任意机构可用。必要时请用户澄清机械目标。 |
| `geometry_completeness_review_required` | AI读取已保存的扫描范围、预算及续查待办；不把截断当完成，不循环使用自指游标，不为补材料重跑运动求解。 |
| `installation_and_evidence_review_required` | AI核对现有安装、路径、构建或证据收集回执并自动整理诊断；不要求用户手工改配置，不删除现场或任意放宽路径保护。 |
| `host_infrastructure_review_required_no_parameter_change` | AI离线整理已有宿主回执和任务诊断，核对契约、SID及源码身份；这不是用户参数错误。不循环查询不可用宿主、不删除未知记录或重建活会话。 |
| `legacy_session_finish_required` | AI先读取旧工具任务及恢复状态；确认无执行中或未知请求后使用finish_motion_session释放本服务执行器，再准备受管任务，不结束其他进程。 |
| `checkpoint_recovery_review_required` | AI读取原检查点和恢复证据；核对设置、时间和全组件姿态，不自动换检查点或重试写入。 |
| `fresh_geometry_reference_required` | AI重新只读查询该组件的引用并核对归属；旧引用和游标不可重用，新的写入方案需要重新确认。 |
| `mechanical_initial_state_review_required` | AI核对当前算例时间与机械姿态，明确归零或恢复方案后再操作；不因时钟为零就认定姿态正确。 |
| `model_and_study_review_required` | AI读取模型、算例和预检阻断项，确认存在且适用后再提出方案，不猜测或忽略重建失败。 |
| `native_result_evidence_review_required` | AI先读取已保存时间轴、采样和失败工件；不把不完整结果记为通过，不为补诊断重复求解。 |
| `native_session_identity_review_required` | AI核对SolidWorks实例与COM身份；仅在明确、安全的会话选择条件下重新选择，不能把进程存在当作COM可用。 |
| `registered_model_selection_required` | AI从已有任务或登记清单核对model_id；不能用文件路径或其他会话ID冒充，也不自动重复导入。 |

低层通用分类还包括：`explicit_user_selection_required`（从明确选项选择）、`tool_identified_arguments_require_user_input`（例如无配合方案ID，先preview并提供所需参数，绝不覆盖人工确认）、`manual_service_disconnect_required_no_parameter_change`（执行器占用，停止重复启动，由AI明确引导停用冲突服务）、`manual_constraint_review_required_no_safe_geometry_inferred`（过定义，核对真实约束）、`explicit_diagnostic_read_choice_not_verification`（只读失败工件）、`no_safe_parameter_change_inferred_from_error_code`（未识别错误，不猜测安全参数）。未识别错误采用保守分类，不自动重试；不能把本表当成永不扩展的SDK枚举。

## 分页、摘要与工件

几何查询有两层待办：当前冻结快照分页的`next_cursor`，以及`geometry_scan.next_queries`中的组件/偏移续查。保留父查询的所有兄弟待办；单组件`scope_geometry_complete`或`scope_pending_query_count=0`不能清空全模型队列。`next_queries_truncated`时结合`inspect_model`组件清单继续核对遗漏；仍有skipped/unresolved则报告不完整。缺席不证明没有几何。游标须推进且不能自指；更改筛选、预算、分组或详情时清空游标重新查询。配合关联`mate_context_complete=false`不代表没有配合，`mate_context_next_query`是额外重扫建议，不得覆盖几何队列。

长任务返回`job_id`，`get_job`查询不新增COM调用。摘要可能按16KB预算缩减；`summary_degraded`表明摘要降级，省略字段不等于结果不存在或通过。优先读取失败码、结论、复核提示及完整结果指针；通过`get_run_artifacts`、`read_run_poses`和已有最终响应/哈希取回证据，不为补材料重新求解。读完整结果时校验实际路径、SHA256、游标与范围。历史输入哈希和基线绑定仍须验证，不能静默换绑。

`get_mechanism_task(collect_evidence=true)`在前端离线整理已有文件，即使宿主启动失败也可调用；无CAD求解、不包含模型与IPC认证密钥。证据可能含文件名、路径，应按实际范围分享。保存失败、恢复未知、原请求结果未知均保留证据。

## 安装、升级与开发验收

AI核验官方ZIP与SHA256并解压到独立目录，使用**新包内**`upgrade.ps1`，`TargetDir`指向原安装。包装脚本按`$PSScriptRoot/scripts/upgrade.py`定位自己的Python入口，**不按TargetDir定位入口**。回执的`upgrade_entry`和`path_policy_source=running_upgrade_entry`证明实际升级器。不能从“备份脚本预演通过”推断旧校验器变得前向兼容；应核对实际文件与入口。

`upgrade-backups`是升级器管理的恢复快照，不是完整独立的安装或降级工具。不要从任意备份目录启动旧包装脚本或先覆盖校验器。不同入口、缺失先决条件或租约占用可能先报不同门禁，只有真实入口回执能证明走了哪条路径。

alpha.11起，宿主登记/启动、OwnerClient及owner入口在创建会话前核对路径：精确的`upgrade-backups`路径段或祖先`.clashmate-recovery-snapshot.json`标记返回`HOST_BACKUP_TREE_REFUSED`，属于宿主基础设施问题。AI应回到正式安装，不删除标记绕过保护。查询/注销仍可由可信维护器对旧契约执行。新恢复快照包含`managed-files.zip`、`backup-index.json`和收据；ZIP保留旧受管文件及执行器字节，索引校验成员、长度和SHA256。回滚直接读取经核验的成员写回原位置，不执行/导入备份代码，不解压为独立安装。旧快照原样保留。

维护器`scripts/host_maintenance.py`由AI离线操作，默认只检查，`--retire-idle`才申请条件式退出。调度器枚举是只读的；可操作范围严格限于所选正式安装`upgrade-backups/<快照ID>`下的精确任务，必须核对名称散列、marker、单一action、当前用户SID和路径。运行实例还须核对PID创建身份、同一桌面会话、launch及原始源码指纹证明，通过已有认证IPC查询`status`、确认无活动任务/未完成现场后申请`shutdown_idle`。旧owner再次检查空闲；确认原进程和调度包装器退出后才注销并查询确认。不调用Task.Stop，不强杀、不启动旧宿主/执行器，不批量删除`ClashMate-*`，不触碰正常安装或其他安装任务。维护请求持久记录，结果未知时读取原响应，不重复排队退出。

完整安装模式升级在受管文件写入前执行上述维护，无法核实或存在活动任务则返回`UPGRADE_BACKUP_HOSTS_REQUIRE_REVIEW`，保留原文件与证据。提交后再次核对；此时收尾不确定单独记为`host_cleanup_status=review_required`，不能伪称源码回滚。`retired_host_tasks`、`backup_host_review`记录实际范围。DryRun仅检验任务契约并列出待核对宿主，不请求退出；DryRun通过不保证运行中宿主可以安全退役。源码校验专用的`install=False`模式不检查本机宿主，不能冒充完整升级。宿主存在并不证明执行器或全局互斥锁被占用；须分别读取原归属和租约证据。

开发者由AI执行`unittest discover`、`tests/run_offline_policies.py`、干净包`verify_release.py`、升级预演/真实升级及自己的真实CAD样本。CI运行离线和无CAD宿主契约；Session0不能启动交互宿主时显式跳过，不能称为通过。真实CAD、离线夹具、跨机与真人WorkBuddy结论分别记录。普通用户无需配置专门测试MCP、输入命令或收集散落日志。
