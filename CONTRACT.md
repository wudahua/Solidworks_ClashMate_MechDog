# AI 客户端与开发者契约

本文件随源码包交付。正式入口为 `motion_server.py`，协议握手名称为 `SolidWorks ClashMate MechDog`，推荐配置键为 `solidworks-clashmate-mechdog`，共30项工具。实际字段、枚举和默认值以当前连接的 `tools/list` 为准；不要用历史发布说明替代当前 schema。

## 输入与单位

所有工具输入均为封闭 JSON 对象（`additionalProperties=false`）；未知键拒绝，不改名、不丢弃。原始 JSON 按 schema 校验，布尔值不能代替数字，字符串不能代替数值，枚举非法值及非有限数值拒绝，返回 `INVALID_ARGUMENT` 或相应专用参数码。只有 schema 明确允许时才可传 null；空字符串与 null 不等价。

alpha.12起，`prepare_mechanism_task`在核对宿主源码身份后、获取安装租约前，先执行共享的只读输入校验（任务类型、固定圆边测试卡、运动范围/网格、绝对路径、文件存在及SLDASM扩展名）。输入错误不因另一服务持锁而变成停服提示，也不创建任务、访问COM或运行原生启动门禁。输入有效后仍须通过旧会话收尾、租约、未完成任务和启动门禁；不能将校验通过当成可执行证明。任务引擎自身再次使用同一校验器，防止绕过正式入口时规则不同。

alpha.12的直线候选保留全部原生轴线，利用已读取的健康同轴配合实体给出`axis_evidence`；只有唯一候选与一致的配合轴线平行时才给出`suggested_candidate_id`。该线索指向局部关节，相邻件仍可能共同运动，`degrees_of_freedom_status=unknown`，不能据此宣称整机只剩一自由度，也不覆盖用户明确指定的方向。等价平面方向分组优先选择真实存在且符号稳定的原生面，不能凭坐标字母或零件名猜纵向，不修改原生面法向。每次方案仍须确认并核对实际有符号行程。

运动验证返回原生失败码时，任务层保留原码、run_id、report_path及完整运动验证文件路径；失败任务不再读取未生成的姿态CSV或导出成功曲线。原生判据不通过与系统调用成功分别报告；原生声称成功但缺少姿态文件返回`MOTION_POSE_EVIDENCE_UNAVAILABLE`，仍不宣告运动通过。完整诊断读取和安全恢复先于任何新方案，不自动换轴重算。`finish_motion_session`正常释放旧执行器后保留新建Bridge对象；临时恢复/回放桥接在操作完成后还原，旧请求或恢复状态不明时不替换连接或启动下一轮。

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

alpha.14的圆边任务默认`alignment_mode=strict`，严格卡不重定位及原容差不变。初始径向偏差超限但适合受限横移时，任务进入`alignment_choice_required`，保留具体拒绝码与实测值；AI可调用`plan_mechanism_task(alignment_mode="small_translation")`只读规划，说明预计世界位移、0.01mm上限、仅选中件横移及不纠正倾斜。须另取得用户对初态调整的明确同意，才可在execute传`alignment_confirmed=true`；一般confirmed/scope_confirmed不能代替，不确认不消费令牌。此模式仅一个浮动件、其余固定，执行后审核初态调整和对齐后两次独立12rpm/1秒/30fps旋转。`pre_alignment_motion_preservation_certified=false`、`full_trajectory_equivalent=null`不能补记为对齐前轨迹等价。默认finish恢复原导入检查点；未知结果仍保护。普通motion任务不接受小幅对齐参数，严格模式不接受多余的对齐授权。

alpha.13将输入完整性、运动验证和原生收尾分别报告。源文件校验绑定原生导入的冻结依赖，不将工作区CSV/日志/说明当作CAD输入；`finish.source_integrity`及`源文件核对.json`保留变化、缺失、不可读和额外文件。真实源CAD变化仍是`SOURCE_CHANGED`，`closed_source_changed`表示资源已结束而输入完整性失败，不能将`closed=true`当作整体通过，也不能忽略`next_round_allowed=false`；AI先说明变化原因和收尾结论。

`finish`收据按阶段保存，不因之后文件核验错误抹掉。旧失败记录若已有完整的恢复、正常退出、身份和空闲日志证据，可在明确授权后用`close_unrestored=true`只读核对归档；完整既有恢复收据标记其来源，不冒称进行了新的恢复，`previous_task_passed=false`仍保留。若证据不全，恢复继续按未验证报告，不能仅凭PID不存在解除保护。`get`发现已结束收据时不再探测死连接；受管恢复查询拒绝带阻塞任务及阶段。仍存活的旧代码宿主不能热替换，不能编辑任务JSON或强杀来绕过门禁。

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
| `task_owner_recovery_review_required` | AI读取旧任务、原资源身份和恢复记录；不能从JSON重建COM、重放令牌或自动关闭失败记录。仅明确授权且完整准入证据通过时归档；无完成收据时恢复未验证，已有完整收据则标记其来源，不能补记原任务通过。 |
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

`get_mechanism_task(task_id=...)`对`source_workspace_files`仅展示前20项，`source_workspace_files_summary`给出总数、实际返回数、truncated及完整任务记录路径/JSON指针；不能将展示清单当作完整输入集合。完整清单仍保存在任务记录并随证据ZIP提供，源文件核验和新增文件判定不使用裁剪后的视图。

## 安装、升级与开发验收

`prepare_mechanism_task(task_kind="gear_transmission")`为独立的两轴泵模板，使用既有五项受管工具。首版要求18个解析的顶层零件、0既有配合，名称/空间角色为长轴、短轴、泵体及各两件齿轮和键。名称线索仅可留空或长轴/泵体，不忽略其他选择。限rotary、60rpm、2秒、30或60fps，minimum_travel保持0；比例为方案中明确的外齿轮1∶1反向，不从圆柱面直径推断齿数。plan只读，列出解除固定范围、四刚性连接、两同轴、两轴向、一齿轮及0.01mm/1e-6rad装配位姿预算。execute须取得整套装配写入与比例试算的明确授权；不借用small_translation确认，不改变原严格卡。

内部原生方案不作为额外公开工具，绑定模型签名、一次性原生plan及可恢复检查点。只驱动长轴；两次独立求解验证六件同步、刚性组相对姿态、固定件、材料轴线及反向比例，导出带符号转角。成功结论不认证齿形、接触、摩擦、受力、整机DOF或装配前运动保留。默认finish恢复导入状态；keep_result只限已验证结果副本，退出非零如实单列。未知请求不重放。

AI核验官方ZIP与SHA256并解压到独立目录，使用**新包内**`upgrade.ps1`，`TargetDir`指向原安装。包装脚本按`$PSScriptRoot/scripts/upgrade.py`定位自己的Python入口，**不按TargetDir定位入口**。回执的`upgrade_entry`和`path_policy_source=running_upgrade_entry`证明实际升级器。不能从“备份脚本预演通过”推断旧校验器变得前向兼容；应核对实际文件与入口。

升级前AI先读取已有任务并正常收尾；`get_environment`会连接CAD并启动本服务执行器，不能用它充当无副作用的空闲探针。WinError 5保持`UPGRADE_LEASE_ACCESS_FAILED`和原生码，不单凭错误号认定权限不足或占用；先核对同安装已有服务、宿主和恢复记录，仅在无活动受管任务/运行中旧任务、恢复确认空闲时才调用`finish_motion_session`，安全收尾后停用相关客户端并显式预检。仍失败才继续检查属性、ACL或过滤器，不改名/删除锁、不改权限、不强杀或自动重试。`ORPHAN_EXECUTOR_GATE_NOT_IDLE`的条件式收尾提示仅适用于本服务的已知空闲旧执行器，不能据此结束其他客户端或未知进程。

`upgrade-backups`是升级器管理的恢复快照，不是完整独立的安装或降级工具。不要从任意备份目录启动旧包装脚本或先覆盖校验器。不同入口、缺失先决条件或租约占用可能先报不同门禁，只有真实入口回执能证明走了哪条路径。

alpha.11起，宿主登记/启动、OwnerClient及owner入口在创建会话前核对路径：精确的`upgrade-backups`路径段或祖先`.clashmate-recovery-snapshot.json`标记返回`HOST_BACKUP_TREE_REFUSED`，属于宿主基础设施问题。AI应回到正式安装，不删除标记绕过保护。查询/注销仍可由可信维护器对旧契约执行。新恢复快照包含`managed-files.zip`、`backup-index.json`和收据；ZIP保留旧受管文件及执行器字节，索引校验成员、长度和SHA256。回滚直接读取经核验的成员写回原位置，不执行/导入备份代码，不解压为独立安装。旧快照原样保留。

维护器`scripts/host_maintenance.py`由AI离线操作，默认只检查，`--retire-idle`才申请条件式退出。调度器枚举是只读的；可操作范围严格限于所选正式安装`upgrade-backups/<快照ID>`下的精确任务，必须核对名称散列、marker、单一action、当前用户SID和路径。运行实例还须核对PID创建身份、同一桌面会话、launch及原始源码指纹证明，通过已有认证IPC查询`status`、确认无活动任务/未完成现场后申请`shutdown_idle`。旧owner再次检查空闲；确认原进程和调度包装器退出后才注销并查询确认。不调用Task.Stop，不强杀、不启动旧宿主/执行器，不批量删除`ClashMate-*`，不触碰正常安装或其他安装任务。维护请求持久记录，结果未知时读取原响应，不重复排队退出。

完整安装模式升级在受管文件写入前执行上述维护，无法核实或存在活动任务则返回`UPGRADE_BACKUP_HOSTS_REQUIRE_REVIEW`，保留原文件与证据。提交后再次核对；此时收尾不确定单独记为`host_cleanup_status=review_required`，不能伪称源码回滚。`retired_host_tasks`、`backup_host_review`记录实际范围。DryRun仅检验任务契约并列出待核对宿主，不请求退出；DryRun通过不保证运行中宿主可以安全退役。源码校验专用的`install=False`模式不检查本机宿主，不能冒充完整升级。宿主存在并不证明执行器或全局互斥锁被占用；须分别读取原归属和租约证据。

开发者由AI执行`unittest discover`、`tests/run_offline_policies.py`、干净包`verify_release.py`、升级预演/真实升级及自己的真实CAD样本。CI运行离线和无CAD宿主契约；Session0不能启动交互宿主时显式跳过，不能称为通过。真实CAD、离线夹具、跨机与真人WorkBuddy结论分别记录。普通用户无需配置专门测试MCP、输入命令或收集散落日志。

## alpha.16 旧工具与受管任务交接

prepare先完成参数与路径校验，再检查旧工具状态。仅本宿主保留的Popen、成功握手、无队列/待答/隔离请求、idle且派生字段一致的日志可自动交接；有已派发请求时还须核对日志owner及executor身份。向这个子进程发送EOF并确认退出后才替换Bridge，保留交接收据、历史日志和已有CAD副本，不调用CAD退出或恢复。未完成受管任务不走此交接；其他进程、未知日志和未确认退出仍阻断，不创建新任务。

get_recovery_state.session_admission是离线观察：idle只表示上次请求结束，不证明姿态，也不允许已使用的连接换PID。STARTUP_SELECTION_NOT_ALLOWED附连接使用、待答及隔离原因；读取原连接时省略solidworks_pid，不以auto重置活连接。仅历史idle日志不证明持有旧执行器，不自动标记为升级残留或删除。

齿轮任务motion_parameters.requested_minimum_travel保留请求值0；signed_target_travel_deg表达带方向目标。verification_criterion为完整带符号输入波形与外齿轮比例，input_waveform_tolerance_deg=0.1、external_ratio_tolerance_deg=0.0001，不以95%门槛验证。普通motion任务的minimum_travel语义不变。

get_job要求原样32位小写十六进制：格式错为INVALID_JOB_ID，格式有效但本安装记录不存在为JOB_NOT_FOUND，存在但不可核验为JOB_RECORD_INVALID。均不改写标识、不自动重放任务；缺少旧版本原始响应时不声称已定位job_前缀的生成来源。


## alpha.17 普通两轴外齿轮推荐与补配合

`prepare_mechanism_task(task_kind="external_gear_pair")`复用正式30工具入口。初始请求限旋转60rpm、2秒、30/60fps，minimum_travel=0；补齐方案可另行明确推荐精确原生子集采样率（本例50fps），必须在执行前确认。读取隔离副本的设计属性、原生圆柱材料轴线、固定支承及既有配合，生成角色、两侧刚性组与传动比建议，不从孔径/齿轮外径推断分度圆。明确齿数、相同零件配置、圆周阵列建议与开发试算权重分别标注来源；后两者不得冒充实测齿数。外齿轮假设、角色、比例和具体修改始终需要方案授权。

`plan_mechanism_task`可用四个`input/output_shaft/gear_hint`消除名称歧义，用户无需提供实体ID；比例参数`gear_ratio_numerator/denominator`同时留0采用推荐，同时正值为显式覆盖。缺少比例保留任务并返回机械澄清，不排队写入。高倍率为避免采样混叠需降低试算转速时，方案明确原请求、建议值与原因，确认后才使用建议值。额外角色/比例选项不得在其他任务中被静默忽略。

本轮要求不超过128个已解析、隔离的顶层零件，两侧组各最多6件，无未归属浮动件；支承必须固定并有同轴圆柱参考。可用齿轮自身轴线作为一体齿轮轴。plan逐项列出新增、复用、同轴旋转锁修改；支承复用可核验的健康同轴及轴向距离/重合；组内已有刚性锁定复用，若只有健康同轴/轴向关系，方案明确列出原特征名称和ID，确认后在当前配置保留压缩，新增一项刚性连接。不以LockRotation属性回读代替实际跟转证明；未知关系拒绝自动改写，不删除原配合。默认恢复会还原原压缩状态，保留成果则原特征以压缩状态一并保存。解除固定只限确认的两侧成员；装配前后0.01mm/1e-6rad预算、非目标固定状态与姿态必须通过。新齿轮关系只加一项，已有匹配比例关系复用；模型、引用或签名变动使旧方案失效。

execute要求confirmed与scope_confirmed，令牌仅消费一次。创建单输入马达，两次独立求解，核对每帧输入目标、输出反向比例、两侧刚性跟转、材料轴线的径向/倾斜/轴向稳定、固定件不动及重复性；输出带符号转角CSV。结果不证明齿形匹配、齿面无穿透、接触力或完整自由度正确。默认finish恢复导入检查点，keep_result仅保留本次验证的副本。原减速器若Toolbox将零件重定向到隔离目录外，仍按外部引用保护拒绝；开发对照不等于原装配已通过。

## 令牌输入纠正与长任务观察（alpha.18）

`task_plan_token_readback_required_no_write_retry`：PLAN_TOKEN_MISMATCH不等于方案失效。只有同步拒绝携带`current_plan_still_valid=true`、`execution_consumed=false`时，当前方案未消费；AI先get_mechanism_task读回当前令牌，核对同一任务、具体方案和已有明确授权后才可提交。不猜测令牌、不自动重试；方案/授权改变仍须重新确认。已消费优先返回TASK_ALREADY_EXECUTED，无有效方案返回TASK_NOT_READY_FOR_EXECUTION。未知归属/原生结果仍保留现场，不能借纠错路径重放。

`round_index/round_total`表示一项任务内部的独立求解轮次，并非正反方向两项任务。`progress`保留当前operation/run_id、stage_started_at、stage_elapsed_s、heartbeat_at、last_native_update_at与native_update_age_s；后台只读本次执行器进度文件，不新增COM调用。只有capture_solver_poses阶段可披露局部sampling_fraction；overall_fraction及estimated_remaining_s无可靠依据时为null。心跳不证明原生调用有进展，文件长时间无变化也不自动判定挂起、取消、结束进程或重试写入。整项verification只有全部独立求解、审计和重复性通过后才能标记verified；第一轮原生返回不是整个任务成功。

progress.stage_source区分task_owner_stage、task_verification、executor_progress_file及owner_wait_heartbeat_only。切换到审计或收尾时，不把上一阶段原生观察标成当前原生进展。verification_passed表示完整运动审计结论；native_completion_proven_by_observer固定为false，观察线程不能独立证明原生调用完成，两字段不可混用。

## 齿轮导入健康与静止侧声明（alpha.19）

仅受管external_gear_pair使用专用空实例保名导入；重复依赖文件名拒绝，不覆盖。Toolbox默认搜索设置在原生调用finally中恢复核验；只移除已核验副本的Toolbox标记，不更改原文件和全局库。全部实际加载文档须属于副本。普通重建失败时最多一次ForceRebuild3(false)，保存前核对全部姿态（最大变换系数差不超过1e-7）、固定标志、原生配合参数与组件绑定、算例设置以及源文件哈希。持久参考重建变化单列记录，不冒充同字节参考身份。无法证明时保留错误，不反复重建；成功不等于运动或接触通过。

原导入预检的重建、特征、解析错误优先MODEL_PREFLIGHT_FAILED；只有ALL_COMPONENTS_FIXED可作为后续显式解除固定的准备输入，不能借此忽略其他错误。完整分类工件区分fixed_component与IComponent2.GetConstrainedStatus，remaining_DOF未知保留null，不从同轴配合数量推断实际自由度。

静止侧范围阻断保留EXTERNAL_GEAR_SCOPE_UNSUPPORTED，唯一两轴组合的该码不被EXTERNAL_GEAR_SELECTION_REQUIRED覆盖。发现阶段进入scope_review_required并保存scope_review；plan可在该阶段接收stationary_component_hints，仅允许完整、唯一匹配的名称，不模糊补全，不与转子组交叉，不忽略未声明的轴系外浮动件。声明只形成待确认方案，execute仍需要当前令牌、confirmed及scope_confirmed，逐项固定动作列入原生actions，受同一回滚及全组件轨迹审核保护。

## 通用装配约束检查与配合补齐——减速器首例

目标是检查、复用并补齐必要配合，不能以批量固定附件代替配合补齐。通用分析、分组意图和约束补足规划与齿轮机构适配分离；通用层允许任意命名运动组，不写死减速器组件名称、数量或齿轮拓扑。首个执行适配仍限已声明范围的两轴外齿轮。

inspect_model(full)的assembly_constraint_review来自本次原生检查响应的离线计算，并在持久化终态响应之前绑定完整证据工件与哈希；components模式不扫描配合。分析或工件写入失败保留原生检查结果，不把它变成COM故障，不自动重查CAD。未加载、压缩、SpeedPak或子装配不宣告完整。

局部线性化分析只处理已观察健康且未压缩的受支持配合。相同配合数量不代表独立约束数，线性相关也不证明某项原生配合可删除。IsFixed、GetConstrainedStatus、设计意图、分析中的局部秩和真实运动结论分别记录。原生阵列依赖不等同于刚性关系；阵列实例不因缺少直接配合就单独加约束。锥面轴线和基准轴仅增加只读证据，不暗中注册或改绑为可创建的普通面参考。

plan_mechanism_task的assembly_intent仅用于external_gear_pair，包含完整、精确、不交叉的stationary/input/output名称分组，由AI根据用户机械意图填入；不得与stationary_component_hints的固定简化语义混用。组归属不是已有刚性证明，也不是写入授权。规划按受支持约束模型选择独立补充，不声称已求得全局最少配合数。无法补齐时整项不写入。

补齐模式保留原配合与压缩状态，保留静止侧原固定标志。已有旋转副先补必要的方向约束；完全没有配合且非阵列实例的种子件可用单项刚性配合连接声明组，不固定到世界坐标。基准面采用组件上下文持久引用，AddMate5前核对原生选择数量、类型及组件归属；不直接把失去组件归属的IRefPlane传入CreateMate。

若采用当前保存姿态建立新运动初态，完整方案须明确说明在试验副本舍弃非零历史算例，并明确切到已核验的模型标签创建模型级补充配合，原文件及原检查点保留；这不是旧算例归零或缓存重建通过。仅在完整文件检查点的原生恢复、重开、全部姿态、固定标志、旧配合参数和算例状态均验证后进入事务。新增配合逐项核对健康和全部姿态，旧配合参数/绑定/压缩状态不得改变。RPC等未知原生异常停止再次派发恢复写入，保留现场；已知失败才按检查点恢复。

执行仍需一次性令牌和具体方案确认；补齐完成不等于运动通过。整机运动须另由两次独立求解、全组件轨迹、传动比、组内相对运动及静止组审核认证，并验证收尾与再次执行。该节是alpha.20的受限执行契约，实际交付结论以冻结验收记录为准；不得回写为alpha.19已有能力或扩大为任意装配已通过。

新建Motion算例前后必须保留当前配合ID、启用/压缩状态及全部初始姿态；算例局部配合不能通过盲目解除压缩移植到另一算例。发现差异返回STUDY_CONSTRAINT_STATE_UNVERIFIED，不开始求解；仅已知失败执行检查点回退，原生COM异常返回STUDY_CREATION_NATIVE_UNKNOWN并保留现场。正式齿轮任务在求解前另将完整配合状态与补齐成果逐项比较。完整inspect_model查询采用原生批处理并报告分段计时，计时边界明确排除作用域退出及传输序列化。

补齐方案可携带native_grid_recommendation：依据已读取的高帧率历史，显式推荐其整数约数作为采样帧率，并在一次性确认前解释请求/推荐采样率与原生输出率的区别。仅受管补齐任务按明确列出该规则的已确认方案启用exact_grid_or_exact_native_subset；普通低层调用默认exact_grid_only。可接受的密集原生网格必须完整、均匀、有限、严格递增，原生帧率为请求采样率整数倍，全部采样时间在原生数组中以原1e-7秒门限匹配；不插值、不近邻取整。time-axis.json保留完整native_time_s、selected_native_indices、selected_time_s和诊断。output_fps在该显式模式下表示实际采集的姿态帧率，原生求解帧率另见solver_settings_after_calculate。冻结回放仅沿用原成功记录绑定的规则；任何缺点、错点、姿态或恢复失败仍拒绝。

补齐模式的支承测量可使用IsFixed=false且由约束保持静止的参考件：须以完整当前采样轨迹逐帧核验1e-7m/1e-6rad静止容差，并记录reference_stationarity_evidence；声明或名称本身不构成证据，不改写固定标志。参考件实际移动、归入转动组或缺采样均拒绝。旧圆边测试卡默认准入保持固定参考要求。
