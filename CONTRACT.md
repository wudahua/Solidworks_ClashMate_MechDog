# AI 客户端与开发者契约

## 启动缓存与导入前失败收尾

`startup_process_review_required_no_write_retry` 区分本机子进程创建问题与已派发的CAD请求。错误码包括 EXECUTOR_MISSING、EXECUTOR_SPAWN_DENIED、EXECUTOR_SPAWN_FAILED，及对应 SOLIDWORKS 前缀；原始 Win32 错误和每次创建结果落盘。仅 CreateProcess 明确失败时最多退避重试3次（1/2/4秒）；已经创建的进程、COM调用、超时或配合写入不走此重试。

每个隔离运行目录保持独立日志和模型；只复用经源码、控制辅助源码、编译器、框架支持文件、Interop及编译选项哈希绑定的二进制缓存。缓存和复制后的产物逐字节校验；失效或损坏保留旧产物并重新编译。启动CAD前的 --startup-self-test 不访问COM、互斥体或模型。

自检子进程等待超时仍受未知状态保护；不能仅凭尚未启动CAD就声称全部资源已结束。该异常分支不重试进程或自动结束任务。

只在当前活会话记录了明确的进程创建失败、尚未派发导入、没有模型/Bridge/配合成果时，finish_mechanism_task允许专门收尾。未启动CAD时仅关闭记录；已启动时只使用保留的本次进程句柄与明确PID，控制器要求实例完全无文档才正常退出，不关闭任何已打开文档。控制失败、等待超时或出现文档即保留未知状态并禁用再次尝试。收尾保留原失败，restoration_status=not_required仅表示不存在已导入模型；不是恢复成功或运动通过。历史null字段、PID消失、TTL、崩溃锁均不能代替该证据，不增加无条件门禁复位工具。

## alpha.43 普通局部组的完整阵列种子链

assembly_constraints普通rigid_groups新增有界准入，不增工具或参数。局部组仍最多32成员，展开最多8连接目标，机械归属须明确；AI可从group_seeds返回的已观察种子归属假设组合完整局部组，不能由几何接近或固定标志推断用途。

新局部路径只支持原生LocalLPattern/LocalCirPattern。结构特征扫描完整、issues为空、组件身份/布尔阵列标志齐全且唯一；每个派生件的父特征与阵列子特征双向一致，原生种子非空、无陌生成员、同组且无循环。递归种子须完整，同一共享链只检查一次；GetParents取到64、GetChildren取到256上限时保守拒绝，不冒充完整。未知/被压缩类型、种子跨组、缺失与截断返回CONNECTION_SCOPE_UNSUPPORTED及pattern_group_requires_seed_scope_review，诊断给出scope_reason和可识别种子名称；AI先核对同用途范围，不让用户抄实体ID、不重试写派生件。原整装配路径和覆盖要求不变。

pattern_scope_reviews记录种子和特征身份，不是刚性证明。派生件不生成单独配合动作，只保留group_bindings；每项真实有界试验核对全部绑定、旧连接、固定状态与全组件恢复。verification.declared_pattern_bindings_checked_per_trial明确数量。已有刚性种子的零新增方案须包含明确验证目标才执行试验；纯只读“无需新增”答复不能记作运动认证。默认finish恢复导入状态，仅明确要求才保留已验证副本。

整件轴承的静止归属来自此前明确机械目标，本例4件不是内外圈分别建模，不认证滚动接触、摩擦或受力；其他模型不能按bearing名称自动归静止。没有放宽原生全约束冲突、旧配合保护、姿态预算或未知状态恢复门禁。

## alpha.42 通用命名运动组的只读推荐

`plan_mechanism_task(group_seeds={组名:[代表件名称,...],...})`仅用于assembly_constraints的只读归属查询。AI应自行从已明确机械用途选择代表件，可参考assembly_assessment.group_seed_suggestions；疑义才集中问用户，不要求用户逐件选零件或抄ID。支持1–128个命名组，每组1–128个不重叠代表件，当前只限平层装配或已选内部层的平层清单；普通具体rigid_groups仍为最多8组。多个独立运动件可各为单件组，不强行锁成刚性组。片段超过8个非单件组时明确plan_fragment_blockers，不截断输出部分计划。

此查询不能混用connection_intent、rigid_groups、固定释放、completion_scope、层选择、序列或auto_plan。不访问CAD，不创建令牌；待确认方案不被撤销或改写。返回group_recommendation及持久证据路径，完整结果亦保存在任务记录；观察来自prepare快照，不是当前原生预检。名称歧义给可理解的实例选择；真正规划仍重新核对当前原生引用、参数、健康和姿态。

传播只使用健康、已识别的原生参考拓扑和已有内部刚性观察，固定标志或名称本身不产生附件归属。原方程不能支持时仍保留其拓扑及不确定性，不能删除该边后虚构唯一组路径；无完整参考、健康故障或多组路径继续待定。已连到代表件的内部刚性观察可先保留；它不是有限运动或设计用途证明。名称仅用于对疑似整件轴承增加否定性歧义提示，不能据此正向归静止/轴组。跳过的未定轴承或参考边界仍保留阻断，不能把它另一侧的零件误判为唯一归属。全部轴承和定距环的具体用途可复用当前对话此前的明确确认。

原生阵列的同组种子只传播归属假设，不证明阵列运动。不支持种子或冲突不自动消除。group_membership_reviews逐组列出建议和可能被消除的现有相对运动；mechanical_questions集中列出待定归属，支持分别保留独立运动。all_memberships_proposed只表示每件都有草案；membership_confirmed、motion_verified仍false，不是配合完善或用户已确认。

plan_input_fragment只给普通rigid_groups的待审核片段，不自动推断组间运动、宣称whole_assembly、释放固定或派发补齐。AI结合已明确用途补全普通connection_intent，获得具体原生方案和精确范围确认后再execute。80件分组完整不代表应在一次事务中全部写入；本轮真实减速器仅验证单盖板局部补齐和两轴运动保留，整机附件补齐未认证。原安全门禁、原始配合保留、位姿预算、失败恢复和未知状态不重试规则不变。

## alpha.41 首轮分类、自动预演及退出后异常归档

`prepare_mechanism_task(task_kind="assembly_constraints")`返回`assembly_assessment`：组件逐项状态、category_counts、完整记账、剩余候选游标、未决连接对、集中用途问题和受限已有耦合路线。它是确认前观察，不认证机械意图、运动、缺项或全局自由度。组件有其他目标仍可能存在未决连接对；候选缺席不证明不需约束。只读参考身份失败继续报告全部结构，但保持写入禁止。

`plan_mechanism_task(auto_plan=true)`是新增布尔参数，不是新增工具。仅用于尚未有待确认方案的普通assembly_constraints整装配任务；可用connection_intent补充局部机械用途并复用其他建议目标，不能混用组、固定释放名单、层选择或序列动作。最多8页候选、16个自动目标，超预算给出技术原因，不让用户猜参数；原普通整装配规划上限不变。不满足完整搜索、支持组合、全部组件及待定连接处理条件时返回分类和澄清/范围原因，不派发CAD、不创建令牌。满足条件时仍走原普通规划、当前原生状态核对和whole_assembly原生预演；确认机械用途、精确补项和试验范围后方可execute。零新增并不证明运动通过。`assembly_assessment.observation_stage`及native_verified/confirmed字段表达快照阶段，不能将预演前分类冒充执行结论；执行结果读verification和finish。

丝杆已有耦合仍只能以声明范围独立检查，整装配自动组合不混入它。固定标志不直接构成刚性组；直接支持秩不足的瞬时投影不充当机械用途。大型、未知参考、复杂耦合、健康故障等仍可能仅报告或需要澄清，不自动批量锁死、删除或修复原配合。

原生螺旋/限位距离的对齐签名统一读取一次`IMate2.Alignment`，仅接受swMateAlign_e的0/1/2，同时作为该配合外层与参数层的对齐值；不再依赖本机限位定义`MateAlignment`返回的越界整数。上下界、比例、方向等仍逐项读取保护；不是忽略对齐或放宽签名。依据为原生实际配合Alignment接口及本机前后读回，不据此推断所有COM异常根因。

`get_mechanism_task`可提供`dead_native_retirement`。仅同一保留CAD Popen已观察退出、当前owner/创建身份/模型/运行目录绑定、原请求已结束、无pending/quarantine且完整响应哈希匹配时eligible；不采用裸PID存活或心跳替代证据。默认finish要求ORPHAN_CLOSE_CONFIRMATION_REQUIRED；明确`close_unrestored=true`后再次核对，只stdin EOF并等待本执行器退出，保持未知日志和副本，不调用CAD、不恢复或强杀。结束为closed_unverified、failed_native_exited_resources_released、previous_task_passed=false、restoration_status=not_verified；原失败保留。执行器退出不确认则继续持有任务和租约。CAD仍活、请求未结束或身份不明仍拒绝。

真实CAD的已退出资源归档采用“空闲执行器先EOF，再正常ExitApp”的受控中断安排；不是实际崩溃复现，也未原生覆盖“CAD先退出而执行器仍活”的顺序，后者仅离线夹具覆盖。历史崩溃根因未消除。本机通过、失败保留和未验证范围须分别报告。

alpha.31整装配间接约束：`connection_review.assembly_constraint_graph`在完整清单内构造受支持瞬时约束模型，列出内部刚性组、地面约束观察、配合连接分区、阵列依赖和未知项。分区只包含已观察的配合边，不是整机断连证明；阵列依赖不是刚性运动证明。未知方程不加入受支持矩阵，但必须保留其存在与不确定性，不能据此认定额外自由度或缺配合。`global_DOF_certified`和`motion_verified`仍为false。

草案保留`supported_direct_rank`和`supported_whole_inventory_effective_rank`，逐个选项的`supported_whole_inventory_missing_coordinates_if_goal_chosen`只在该目标成立时表示所需独立增补数。它与规划器共用秩判据，并在独立副本矩阵中计算，不修改共享快照；全部候选的`missing_connection_proven`仍为false。间接约束已充分时不添加冗余配合，与间接链冲突时在原生预演前返回`CONNECTION_GOAL_CONFLICT`及`existing_indirect_constraints_conflict_with_declared_motion`。这些线性关系不能取代原生预演、小位移验证和恢复。

装配根参考仅在原生`IComponent2.IsRoot`确认且真实几何已读出时标记`reference_owner_scope=assembly_root, root_reference_verified=true`，不按名称或库存外ID猜地面，也不据此注册创建参考。`nonlinear_constraints`保留限位距离的SI长度及螺旋配合的原生RevolutionType、RevolutionVal、Reverse、Alignment；螺旋原始数值未经单位／类型解释，不直接冒充已求出的导程或耦合运动。未知或无法读取保持unavailable，观察成功不等于运动通过。

目标冲突诊断附`component_state_observations`、`nonlinear_constraints_observed`及`constraint_graph_path`。非线性列表是完整清单观察，不是被证明的根因；AI不得把列表中无关配合直接当作应删除项。alpha.31阶段导轨保留全约束冲突门禁，不以增加约束、解除固定或重复plan解决未认证的原生运动路径；完整Motion任务的历史成绩不替代本次通用模式验证。

alpha.30只读恢复核对：完整检查点关闭重开结束后，使用重新取得的组件对象，在一个`NativeCommandBatch`内读取全组件位姿、旧配合健康与参数、配合数量和固定状态。检查点恢复本身在批处理之外，不缓存跨重开的COM对象，不删除检查项。探针工件的`native_timings`记录顺序阶段及尚未归属的耗时，计时在最后一个已结束阶段冻结；工件写入、冻结后阶段、外层序列化、运输和整个任务准备不在总计内。`post_restore_native_batch`仅证明该批处理进入及恢复标志，不能单独证明机械检查通过。客户端仍读取任务结论和原始工件。

alpha.30候选保留现有转动／滑动为首选，同时列出`source=alternative_only_if_rigid_mechanical_goal_confirmed`的刚性备选。它仅方便AI表达已确认的机械用途，仍为`requires_goal_confirmation=true, executable=false`；不把现有自由度当成缺配合证据。不得默认选刚性、删除旧配合或用“轴承”等名称替代机械目标确认；已有刚性连接不据此推荐释放自由度。

alpha.29基础连接工件：`request_target_sha256`必须匹配解析前实际接收的`target_json` UTF-8字节；继续核对探针、模型、组件及工件哈希。数值目标允许最多4个binary64 ULP且受位置1e−12米、其他系数1e−14绝对封顶的表示往返误差，缺失哈希不自动兼容为已验证请求。该规则只用于请求身份核对，机械位姿、允许行程、固定件及恢复判据不变。失败后的原工件与收尾记录保留，不把原失败补记成功。

迟到退出：`get_mechanism_task`返回`native_close_pending=true`时，原退出请求已经发出，AI应继续查询原任务，不再次恢复、退出或prepare。仅原宿主仍保留同一个进程句柄、执行器结束且既有恢复/成果核对充分时，实际退出后补齐`finish.late_exit_observation`及退出码，释放任务；非零退出和源文件变化仍分别报告。该等待标志不表示另一次写入正在排队，也不代表会强制取消原生操作。宿主重启后的孤儿归档仍按原确认与证据规则执行。

本文件随源码包交付。正式入口为 `motion_server.py`，协议握手名称为 `SolidWorks ClashMate MechDog`，推荐配置键为 `solidworks-clashmate-mechdog`，共30项工具。实际字段、枚举和默认值以当前连接的 `tools/list` 为准；不要用历史发布说明替代当前 schema。

alpha.28通用草案：`prepare_mechanism_task(task_kind="assembly_constraints")`返回`connection_draft`；`plan_mechanism_task`不传`connection_intent`只读返回同类候选，不创建或撤销已有令牌。候选按已知约束及当前几何列出名称式输入、依据、歧义及只读阻断。明显长轴且横向包围盒相交只能支持导向假设，不能断言设计用途；同轴的转动/滑动/刚性等备选须与用户目标核对，不能把所有浮动件改刚性。每页扫描最多64对、返回最多8组；`next_cursor`原样传`get_mechanism_task(task_id=...,draft_cursor=...)`，不得与`collect_evidence`混用。游标绑定任务目录及完整调查快照，续查不访问COM，可读持久快照；按`pair_range_start/end_exclusive`累计前页，`complete_for_remaining_suffix`只表示该后缀结束。几何截断、未知约束和轴线选项截断分别保留，候选缺席不证明无需配合。草案来自prepare时刻，实际plan必须传具体`connection_intent`或alpha.32的明确`rigid_groups`，展开后合计1至8项目标并重新核对原生引用、状态与机械目标；仍经具体方案确认才执行。

升级维护：`upgrade.ps1`继承宿主Python环境，不为完成升级清除`PYTHONPATH`、禁用`sitecustomize`、替换文件API或调用另一种删除入口。alpha.27在包与目标校验后、预检和租约前，以及正式租约内观察`Path.unlink`实现来源；外部包装或无法确认时，仅用宿主原API检查自建32字节文件及实际移除结果，允许且通过才继续，不一概拒绝包装器。拒绝、退出或静默不执行时返回`UPGRADE_FILE_API_CHECK_FAILED`、`python_runtime`、`file_api_checks`和`target_mutation_started=false`；托管源码及备份未写，自建`runs/upgrade-api-checks`预检记录和被拒绝的文件保留。这是单文件能力检查，不是对所有运行时钩子或未来批量操作的认证。AI应核对宿主支持的授权维护渠道，不能据此自动关闭其保护。事务中`SystemExit`及键盘中断进入逐文件回滚：先恢复所有可恢复旧文件，再清理新增托管文件，保留每项拒绝的类型/路径；任何残留仍是`UPGRADE_FAILED_ROLLBACK_INCOMPLETE`。回执写入失败单列`UPGRADE_RECOVERY_RECEIPT_FAILED`，旧回执与真实字节结论分别保留，不自动重试或宣称可启动MCP。历史执行器PID只作线索，租约和原生互斥体才用于当前占用核对，不删除陈旧恢复日志。

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

`confirmed`和`scope_confirmed`默认false。不得因工具返回了查询提示、存在候选、或已有旧授权，就自行把它们改为true。`keep_result`仅适用于已验证成果；与`close_unrestored`互斥。关闭失败记录需另行明确同意；旧资源身份、退出与日志绑定未证明时继续阻断。旧日志的空闲状态只用于完整恢复收尾证明，不作为全部资源已结束后的异常归档门槛。归档失败不等于恢复成功。

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

`prepare_mechanism_task(task_kind="external_gear_pair")`复用正式30工具入口。初始请求限旋转60rpm、2秒、整数5–120fps，minimum_travel=0，须帧对齐及至少10间隔；补齐方案可另行明确推荐精确原生子集采样率（本例50fps），必须在执行前确认。读取隔离副本的设计属性、原生圆柱材料轴线、固定支承及既有配合，生成角色、两侧刚性组与传动比建议，不从孔径/齿轮外径推断分度圆。明确齿数、相同零件配置、圆周阵列建议与开发试算权重分别标注来源；后两者不得冒充实测齿数。外齿轮假设、角色、比例和具体修改始终需要方案授权。

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


## alpha.21 孤儿记录的异常归档

`get_mechanism_task`在原owner丢失时只读返回`orphan_review`，保持持久失败原文，并用`error_context/historical_errors`说明当前查询成功、错误来自历史任务。时间字段仅标注原记录更新时间，不伪造错误产生时刻。缺失或损坏证据仍返回可读的阻断条件；不能据`native_stage=restored`自动迁移为通过。

完整恢复收尾仍走既有严格收据核对。没有完整收据时，须明确授权`close_unrestored=true, keep_result=false`；按PID及创建身份逐一确认原owner、CAD和执行器均已退出或PID已复用，并核对同模型归属、原日志PID绑定及当前门禁空闲。任何仍存活或身份未知的资源、启动中缺失身份、日志不匹配或门禁占用均拒绝。只有明确未启动原生资源且历史干净的任务才允许仅核对owner退出。

全部资源已结束后，日志即使保留active/unknown/recovery_required，也不要求死亡进程回写idle；日志不修改，失败、待处理请求和已执行标志均保留。只关闭元数据并撤销旧令牌，`phase=closed_unverified`、`restoration_status=not_verified`、`previous_task_passed=false`，不调用CAD、恢复、保存或结束进程。源文件变化单独记录为`closed_source_changed`，不能抹掉资源退出事实或宣告原任务通过。新任务必须使用新副本、方案和明确授权。

`get_mechanism_task(collect_evidence=true)`自动采集绑定原任务的外置运行日志和只读资源观测；不借用当前主安装日志，不把诊断采集当成原子原生审计。旧宿主不能热更新；更新前的活动或未知现场继续受保护。


## alpha.22 两轴保存初态与历史归零的分离

external_gear_pair的initial_state=saved表示采用导入保存姿态建立新的运动。普通stationary_component_hints分支与assembly_intent补齐分支共用已核验的保存态准备：只读预览列出initial_state_preparation.nonzero_copy_studies_to_remove；确认后先创建内部检查点、完整恢复重开核对组件姿态、固定标志、原配合参数和所有算例状态，再仅在副本移除列出的非零历史算例并进入核验的模型作用域。未确认不能删除算例、建配合或马达。移除前后的全部姿态与原配合核对失败即拒绝，不以清时钟当作姿态恢复。原文件、原导入检查点及历史证据保留，默认finish恢复原导入状态。

普通分支无非零历史且非补齐模式时，保留既有零时刻检查和检查点探测；任意配合工具的初时刻门禁未放宽。受管任务不转交公共create_model_checkpoint/reset_study_time，不跨模型命名空间或另一执行器。initial_state=study_zero在两轴任务仍拒绝，并提供保留角色、比例、分组后以saved重新只读规划的指引；保存姿态不等于历史算例的零时刻，拒绝不能被解释为已经获准自动改用saved执行。

普通分支也复用补齐分支的精确原生子集采样建议。已知2500fps历史输入在2秒卡上可推荐50fps；方案显示请求30fps与推荐50fps，需确认，不插值、不取最近时间点。未来原生结果网格仍需实际求解审计；推荐不等于兼容证明。低层reset_study_time重建分支的原生健康拒绝仍保留，本修订不声称已修复所有历史零时刻重建失败。

run_user_study主等待预算仍默认为600秒。仅当该预算到期时，当前请求的job映射、run_id及派发后进度时间戳全部匹配，且阶段已经是restore_solve_scope或finalize_solve_evidence，才记录审计并对同一个原请求额外等待最多60秒；不重派发、不重新求解、不替换连接、不改变原生结果与恢复判据。其他阶段、过期或不匹配的进度、不能写入等待审计时不延长。额外等待到期仍返回CAD_TIMEOUT并保留隔离、最终响应查询和禁止重复写入。已经失败的旧任务不会因迟到成功而自动改记通过。额外等待的记录保存在runs/request-waits，原生响应记录保持原样；成功结果可附transport_restoration_wait，明确区分传输等待观测与原生认证。

### 原生时间轴的载体与失败证据

已登记驱动的算例优先以该驱动件的原生面读取结果时间轴，记录native_read_timings.carrier_component/carrier_selection；登记引用无效、驱动件固定/压缩或没有可读面时拒绝，不静默换成附件。无登记驱动的旧算例保持首个活动未固定实体零件的兼容选择，不能因此声称已验证驱动身份。载体选择不改变实际驱动、配合、原生时间数组或严格网格校验，不生成或拼接时间轴。

求解后的引用刷新只重新获取同路径、同配置、同名活动算例，核对成功后才替换当前文档和算例引用；不激活另一个文档或算例来继续。Calculate成功、结果未过期、原生时间轴完整、采样、驱动与恢复校验仍须分别通过。

原生时间轴读取阶段单独报告verify_native_time_axis。读取失败时，若尚无真实time-axis.json则写入verified=false的部分诊断，包含失败时的父/子阶段、载体选择、读取完成状态及原生错误；native_time_s保持null，不用期望网格填充。若真实时间轴已经写入，不覆盖它。错误信封通过time_axis_read_failure保留工件指针，原COM异常类型及HRESULT不因诊断包装改变；工件写入失败也不覆盖首个错误。不自动重试读取、重新求解、改马达或换连接。

## alpha.23：原请求等待与跨层收尾

受管任务后台每次原生调用累计等待上限3600秒；底层CAD_TIMEOUT保留为等待证据，原请求仍活跃时不重派发，心跳持续而不宣称原生推进。严格绑定迟到原响应、原owner、参数及保留的进程句柄，恢复状态已核对才能返回原执行栈，继续原验证。两轮完成并审计后才verified。等待上限后任务不继续原执行栈；迟到结果仅可使原连接允许正常恢复收尾，任务标记incomplete_after_late_response，历史超时和不完整验证保留。低层工具默认预算不变，不自动加速、换连接或提升结果判据。
现役宿主的进度观察使用归属持久记录成功提交后的内存快照，避免Windows轮询读句柄与原子替换争用；当前无调用时不得把旧原请求等待标记作为仍在执行。该观察快照不授予写入或恢复权限，原连接、磁盘日志、请求身份和恢复核验仍为准入依据。
alpha.24：budget_matrix.new_solve仅表示底层创建/求解上限，managed_tasks列出各对话卡实际准入。external_gear_pair请求整数5–120fps（含50），最多60rpm/2秒，须满足现有最小网格及帧对齐；gear_transmission仍限30/60fps。prepare通过不证明原生网格可用；plan可建议精确原生子集，仍须具体方案确认，禁止插值或静默改请求。机械分组校验的missing/unexpected/ambiguous/overlaps由AI读取修正；遗漏不解释为静止，不自动选择重名候选。校验失败保留原任务，不派发后续CAD操作。


alpha.25：范围复核可返回assembly_group_recommendation，含assembly_intent_draft、mechanical_questions及当前证据绑定。支持的局部约束关系和阵列种子只用于推荐；不同组的可达证据冲突、无依据组件和整件轴承不自动归组。AI解释推荐并补齐已有明确意图，必要时集中询问，禁止默认把所有剩余件归静止。规划和执行仍分别需要完整互斥清单与具体方案授权，未知归属不部分派发。

外齿轮推荐复用完整原生survey的组件/配合/姿态作为恢复对照，跳过重复full inspect；预检失败或survey不完整仍保留原独立检查。求解后从采样到名称身份核验、总览和驱动读取共用局部CommandInProgress批处理；嵌套读取保留true，在finally恢复调用前原值，范围不跨Calculate、配合创建、原生保存或快照恢复。所有组件、逐帧姿态、持久身份解析及恢复检查继续执行，不跨请求缓存。总耗时包含进入和退出批处理，不以阶段耗时转移声称提速。
# 通用基础连接任务

`prepare_mechanism_task(task_kind="assembly_constraints")` 创建隔离副本并体检。`plan_mechanism_task.connection_intent` 是严格对象列表，默认声明范围1至8项；alpha.33整装配范围见下文：`component_a`、`component_b` 为实例名称线索，`kind` 为 `rigid/revolute/prismatic`，可选 `axis_hint` 装配全局坐标系中的三维非零方向及 `candidate_id`。AI优先采用已有轴线证据；方向本身不能生成材料转轴。不能混用齿轮分组、圆边对齐或马达参数。

原生全约束观察与运动目标冲突时返回 `CONNECTION_GOAL_CONFLICT`，不是要求操作者改工具参数。只读不完整、未知几何、已有锁定配合的移动后端边界均保持可见，不等于无配合。新方案撤销旧令牌；确认仍不授权执行未列出的补充。

补齐后验证小幅允许运动与禁止方向、固定件及原有受支持连接，并逐次核对全部恢复。临时距离试验约束以成果检查点恢复移除，原配合不变，固定标志仅允许具体方案中的解除名单。`verification.declared_scope_passed` 限本次声明的小位移范围；`native_motion_study_solved=false`，不声称全局DOF或完整Motion求解。默认finish恢复导入检查点；明确保留已验证副本才keep_result。


alpha.29旋转允许方向可使用自动选择的临时角度约束：两组件基准面须对已确认转轴具有足够灵敏度，避开0／π分支，参考仍由原生组件选择身份核验。直线允许方向仍可使用临时距离约束；每项之后恢复成果检查点移除临时特征。禁止方向使用原装配移动求解，不添加驱动去制造拒绝。所有转动试验逐项重新载入成果检查点，校验全组件位姿、原配合参数、数量和固定标志；不以反向移动位姿相同推断求解器状态已恢复。没有合适参考时不生成虚构基准，不在遇错后自动切换后端或降低行程要求。大装配恢复成本可很高，调用方查询原任务；前端等待到期不授权重放execute，收尾和成果保存仍须原任务验证完成。


## alpha.32 整组目标与受控解除固定

在已prepare为`assembly_constraints`的任务中，`plan_mechanism_task`可传`rigid_groups`：1至8组严格对象，每组`name`、2至32项完整组件实例名`members`，可选组内`anchor`。不新增MCP工具。可不传`connection_intent`仅规划刚性组；也可与刚性／转动／滑动目标组合，展开后总共最多8项目标、64项新增配合。不能在一个刚性组内声明相对转动或滑动。分组不证明机械意图，AI从用户目标和证据提出建议，必要歧义才集中澄清；未分配组件仍列为unassigned，不推断静止归属。

自动锚点优先已声明运动端，再选保留的原固定件，否则为稳定坐标参考。锚点选择不授权固定它；已受间接关系充分约束的成员不重复加配合，其刚性绑定仍进入每项试验核对。组合后的约束若锁住其他已声明移动目标，预演前拒绝，不能以各局部方案分别可行作为组合可行证明。

`release_fixed_components`为1至16项完整实例名，仅允许解除调查时明确固定、且绑定本次目标或组成员的零件。最后一个原固定参考不得释放，阵列成员和子装配范围不支持。没有传名单而固定状态妨碍已声明运动时，只读返回`fixed_release_review_required`及建议名单，不自动写入、不生成执行令牌。展开超8项返回`group_goal_budget_review_required`，保留完整展开清单，不截断或部分执行。

固定状态变更以`fixed_state_changes`逐项before=true/after=false列入具体方案。plan使用假设解除后的受支持模型做检查，但原生preview仍绑定原调查签名，尚未改变固定状态。execute先建立并验证原检查点，再仅解除名单、重建并独立核对全部固定标志、全组件初态、旧配合、健康和原生状态；移动目标仍全约束则回退，不自动删除、压缩旧配合或关闭锁转。只支持解除固定这一种受控修复。

每项试验恢复成果检查点时保持已确认的结果固定状态；默认finish恢复导入检查点时恢复原始固定状态。`verification.fixed_state_changes_verified`表示成果状态的独立读回核对，`declared_group_bindings_checked_per_trial`为每项试验检查的声明组绑定数；它们都不等于全行程或整机构运动认证。当前泵样本仅验证两组刚性关系，轴仍固定，不据此宣称完整齿轮传动通过。

## alpha.33 整装配组件核对与冻结批次

prepare及只读plan的`assembly_overview`逐项登记完整组件、内部刚性与已观察关节、阵列依赖和未知约束。`accounting_complete`只表示没有遗漏已调查组件，不表示用途已理解、配合已补齐或运动已通过。相同地面固定标志不把互不相关零件合并为一个转子。AI先复用用户已确认的机械目标，必要时集中澄清未知用途。

`completion_scope`仅供`assembly_constraints`，枚举`declared`（默认）和`whole_assembly`。默认保留alpha.32的展开上限。整装配模式每个刚性组可至128名成员、展开合计最多128项目标、512项新增配合；每个组件必须能追溯到具体目标或组绑定，否则在首次原生预演前拒绝，不静默视为静止。参数schema上限不代表默认范围也扩大。观察到的阵列成员仅在完整种子依赖位于同一明确组内时保留并验证，不单独解除固定或加约束。

一次确认绑定全部批次的精确UTF-8载荷哈希及事务ID。每批至多8项目标、64项新增配合，后批签名通过专用原配合签名读取，不使用几何查询游标签名。后批启动前核对前批完整姿态、固定标志及配合参数；跳批、换事务或载荷变更均拒绝。最后一批结束前不运行有界验证。`batch_progress`显示进度，单批写入成功不代表整项任务成功。

所有批次完成后才建立成果检查点并验证全部声明目标、组绑定、已有受支持连接及每次恢复。只有完整通过才能置`verification.whole_assembly_declared_targets_passed=true`。已知写入或验证失败恢复原始导入检查点，包含先前已提交批次；失败原码及整体恢复结论保留。原生状态未知时不重放写入或强行恢复。旧执行令牌不能复用。正常收尾、源文件未变和保留成果分别以实际回执为准，不能从验证通过推断退出或保存成功。

整装配模式下，已明确要求刚性的成员若原生已全约束而受支持数学模型仍有缺口，可保留旧配合、不追加动作，并显式返回`preserved_native_full_constraint_observation=true`、`supported_target_fulfilment_certified=false`；仍须真实有界验证，不能借此放行要求转动或滑动的全约束组件。组内几何参考不足时，只能选同一确认组内已有原生连接邻居，不创建虚构几何，也不凭名称选择机械关系。

首批仍限完整解析的顶层外部零件、单位尺度，普通刚性子装配是独立后续开发范围。未知配合、全局自由度、全行程、传动比波形、接触及力学结果均不由本功能认证。最终验收及发布状态以版本说明为准。

## alpha.34 普通刚性子装配的外部连接

沿用30工具和`assembly_constraints`，新增范围为完整解析的外部刚性子装配。总计最多128个组件节点，包含所有子装配和子件，深度最多8；依赖保名隔离要求同一导入中的文件基名唯一。只对顶层零件或顶层刚性子装配整体规划和写入，内部子件、内部配合及刚性／柔性模式保持原状；不把内部浮动标志自动解释成需要补配合。

`fixed_component`保留顶层上下文的原生`IsFixed`读数；`fixed_flag_observation_scope`为`assembly_root`或`root_context_only`。内部真实固定状态独立放在`parent_document_fixed_component`，从所属子装配文档的顶层组件、匹配的引用配置读取。顶层节点该字段为null，内部节点必须为原生bool；缺失、错配置或无法按完整实例路径／文档／配置对应时拒绝，不把false猜成内部浮动。依据：[官方IsFixed说明](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IComponent2~IsFixed.html?format=P&value=)。

约束图不使用后代的顶层上下文标志推断地面固定。所属文档的固定标志只形成子件—父级相对关系；已观察的刚性求解模式形成全部子件随父级的绑定。推荐以顶层刚性体为对象，几何来自真实刚性后代材料，分别记录逻辑目标和实际引用所有者，并核对祖先链及原生选择身份。子件单独配合或解除固定不在本范围，不自动改为柔性来满足新目标。

完整目标覆盖可由明确的顶层刚性体目标向已核验的刚性后代继承。此继承不代表内部配合已补齐，也不证明子装配单独打开或改为柔性后仍具有正确自由度。内部问题需在相应装配文档作用域另行规划，不能将外部连接通过标记为递归内部修复完成。

每批、每项有界试验及恢复核对层级、引用配置、内部固定状态、配合参数及材料引用身份、父子相对姿态。`verification.native_rigid_subassembly_binding_checks`给出额外父子绑定数；每份位姿工件的`fixed_reference_parents`必须匹配原生父级映射，`internal_subassembly_state_unchanged`为执行器内部守卫结论。独立审计另核对保存检查点和收尾后的内部装配／子件文件字节；不要将其误写成逐项独立重算了原生内部配合参数。

首批拒绝柔性、虚拟、压缩、SpeedPak、未解析或不完整层级，以及活动配置与引用配置不一致的内部文档。内部参数先支持重合、同轴、垂直、平行、距离、角度、齿轮和锁定；其他内部配合明确拒绝，不静默丢弃。原有默认8目标／64新增、整装配128目标／512新增、受控解除名单及最少一个原固定根参考等门禁保持。

本机四节点夹具三任务21项已通过，包含同宿主恢复／保留成果两轮及已有一项内部锁定配合的对照。夹具生成实例退出非0另保留为告警；正式MCP三任务CAD／执行器退出0分别记录。完整平面结构五任务424项及跨批失败整体回滚另已通过；发布须通过精确源码资产升级及CI，不据此宣称大部分装配、全局自由度、全行程或接触力学已认证。


## alpha.35 分层范围与内部基础连接

`assembly_constraints`在prepare返回`assembly_layers`。每层的组件数、内部固定数、配合数、配置及刚性状态仅为原生观察，父级刚性随动不证明内部配合充分。AI依据已有机械目标推荐；唯一可选层可直接推荐，名称歧义集中澄清。

`assembly_scope_hint`仅用于plan。首次选择范围时须单独传该参数，不混用外层连接目标；异步进入`selecting_assembly_layer`，返回`constraint_review_ready`后再用内部名称、rigid_groups或connection_intent规划。选择不授权写配合，旧外层确认令牌在范围选择前撤销；内部具体方案仍需确认。一个事务只能绑定一个唯一外部刚性文档及当前匹配配置；不能在活方案中切换范围，也不自动改变刚性／柔性、共享文档其他实例或配置。首批要求完整解析的刚性树及健康原配合，未知冲突不自行删除或压缩。

内部的方向、坐标、`axis_hint`及`axis_global`均以所选装配文档为参考；AI优先解释零件中心线、导向等机械方向，不能把内部XYZ直接当作总装XYZ。明确要求总装方向且坐标关系未核定时先澄清，不猜方向。

登记内层组件、创建全文件检查点并读取对应内层快照后，一并提交检查点与比较帧；随后几何调查即使失败，恢复也不能混用总装快照。`selected_assembly_layer.scope_import_checkpoint_id`明确给出本任务恢复点，`scope_checkpoint_includes_all_import_files`必须为true。非目标层参数／固定、总装全组件姿态和零件文件持续守卫，内部临时试验恢复后另核对总装，最终重建再核对并保存。输入签名变化仍拒绝，附具体变化字段；不重试写入，不以缓存变化为由放松门禁。

默认恢复整棵导入树；保留成果只允许已验证任务，返回原导入总装路径，不能仅把内部文档当作完整交付。下一层可由AI从已保存总装启动新任务继续，不代表跨所有层的一次原子事务。声明目标、小幅验证、未分配层和数学模型缺口分别报告。

收尾遵循现有产品契约：实际资源结束、输入未变与原生退出0分别记录。非0退出保留warning，不称正常0；只有已验证保存成果、源文件未变、执行器退出0、原生关闭及文档清空证据完整、原进程句柄确认结束，才可作为后续只读重开输入。未知、待退出、强制结束、缺少关闭证据或源变化均不能复用为成功成果。


## 分层连续任务（alpha.36）

plan_mechanism_task 增加 assembly_sequence=start/continue/stop，不能混用单层目标参数。start从新总装体检启动，按子文档先于父文档、根文档最后的顺序安排最多32个内部文档。仅处理原有支持范围；不以浮动数判断缺项。每层仍有具体方案和一次性令牌，必须确认后执行；已确认的用途可复用，但新写入授权不由旧令牌继承。finish keep_result=True 核对并保存后，AI通过已关闭任务continue准备绑定成果的下一层，不重放先前写入。原生、执行器和源文件收据未通过时停止。get无CAD调用读取持久序列；客户端重连复用活owner，不从JSON重建COM。前层成果保留、当前层恢复和全局完成分开报告；只有所有受支持层完成才登记该范围，存在拒绝层或目标未覆盖全部组件时不登记all_layers_completed。原输入不改，不实现所有层一次原子回滚。


## alpha.37 只读结构与配合写入分离

`connection_review.mode=readonly_structure`、`write_scope_allowed=false`且`all_mates_sufficient=null`。空候选表示没有开展候选搜索，不表示没有缺配合；`complete=false`保留总体未认证结论。`constraint_structure`给出已冻结组件／层级、当前根文档配合健康、写入阻断及续查入口。原生完整检查可能读取现有配合引用；未进行候选面遍历，不声称完全没有几何读取。

组件和层级每页16行，游标绑定任务和快照。跨任务、错集合、非法页边界、丢失或篡改快照明确拒绝，不访问COM重新生成。`all_structure_pages_completed`不通过单页置真。前端断开再连接保持同一正式宿主及冻结快照；AI累计两类清单的前页，并在检查完成后恢复收尾。不把分页结果用作完整恢复基线；恢复使用保存的全组件位姿、全部原配合及原文件检查点。

同一只读任务的scope选择、几何目标、顺序启动和执行明确拒绝，未派发CAD写入。需要内部补齐时，先finish并单独准备受支持子文档；不自动修改柔性、共享实例、配置或固定状态。已有普通刚性小装配流程保持。没有新增工具、测试服务或用户配置。

`COPY_REFERENCE_REDIRECT_FAILED`保持原错误码，details.reason区分`direct_dependency_outside_traversed_input_set`与`native_replace_returned_false`，并附引用双方路径。前一情况的`source_documents_opened=false`及`native_replace_dispatched=false`描述该失败边，不表示此前没有对其他已关闭副本成功重定向。外部建模引用不是被证明丢失的组件；不以删引用、猜路径或忽略隔离来放行。

只读上限500节点、每页16行；触发条件为预检节点数超过128或原生柔性阻断。保持完整inspect_model结果作为恢复基线，不能用分页压缩字段替代。报告仅认证已捕获的组件／层级清单及当前根文档原生健康观察；子文档递归健康、几何缺项、全局自由度、完整运动均未认证。已有写入仍限128节点及原受支持范围。


## alpha.38 未认证原生配合参考的只读转接

`diagnostics.details.reason=native_mate_reference_identity_unavailable`说明本次写入身份不完整。details指向首次不可读的参考；完整只读检查另保留全部已观察的根文档未解析配合。`reference_object_available`区分参考对象不可读与对象可读但持久字节不可用；不把原生错误计数0解释为引用齐全或可安全写入。

prepare返回`connection_review.mode=readonly_structure`、`write_scope_allowed=false`和`all_mates_sufficient=null`。原始参考诊断在`constraint_structure.native_reference_identity_issue`，同时进入写入阻断清单。组件／层级仍是冻结分页快照，结构完整不代表几何缺项、全局自由度、递归子文档健康或完整运动已认证。只读上限500、写入原128节点及唯一刚性文档边界保持。预演、范围选择、序列启动、执行和保留未经验证成果均拒绝；AI解释已有结果后finish恢复收尾。

低层配合预演、检查点和其他调用仍要求完整身份，返回明确错误后由AI核对证据；没有普遍吞掉异常或自动改引用。相同错误码但其他reason、缺少明确未写入声明、未知原生状态和COM故障继续原失败流程，不进入只读转接。不可读取不是“已证明引用丢失”，没有自动删除、压缩、猜测替换或补冗余配合。


## alpha.39 单次同步快照与读取契约

`ImportMateParameters`和`ProbeWorkingState.MateIdentity`共用字段读取实现；只在单次同步调用内部复用原生配合对象、类型以及按原生组件对象索引的名称。每个新快照独立建立清单和名称表，不按文件路径合并不同实例，不跨请求、写入、配置或重开复用。未知配合类型、对齐、锁旋转、距离、角度、组件绑定、抑制、齿轮比例与方向保持原字段；身份模式仍核验每项持久参考。显式要求计算参考但不返回参考的参数模式也保持原校验。

原生getter失败仍使整个快照失败。持久参考对象或字节为空仍为`CONNECTION_REFERENCE_INVALID`和`native_mate_reference_identity_unavailable`，保留原诊断；只读转接条件不变，不把未观察字段当成已通过。每次扰动前后及恢复后全部原配合、固定状态、数量和姿态检查不删减；检查点恢复路径未改。

冻结的alpha.38读取器仅供已有、显式故障测试开关保护的内部对照入口，不增加公开MCP工具；正常任务调用新读取器。同文档交替读取比较完整JSON字节而非少量字段，另验证一次原生状态变化和恢复后输出。读取器计时和整项任务耗时分开，不能将局部加速比乘到整条链路，也不能把受控缺项开发变体计为独立真实新机构。


## alpha.40 既有耦合的零新增受限验证

原生全约束观察原样保留。仅在完整、健康的当前约束清单中，受支持的滑动目标秩5、参考接地秩6、螺母刚性随动、轴相对接地为转动、恰一条已认证丝杆关系、全部其他非等式仅为已认证安全限位时，允许`coupled_verification_only=true`。丝杆仅解释`RevolutionType=1`的正有限SI每转距离；0.1mm试验对应轴转角不得超过既有1度预算。未知、混合增补、整组／整装配写入、近限位或缺失参数仍拒绝；不将螺旋方程插入受支持线性矩阵，也不自动新建螺旋配合。圆边只作为已存在丝杆参考观察，须已认证整圆和原生持久参考回读；不放开任意边缘／草图写入。

草案可自动区分已有联动，推荐零新增检查；实际plan仍冻结当前原生状态、驱动面、轴线、参考及具体试验。正反允许方向各用0.1mm/s、1秒、30fps临时线性马达；31帧全部组件按材料参考核对方向、位移、丝杆比例、限位、接地和其他受支持连接，位姿仍受5mm／1度封顶。原生返回成功或位移绝对值均不足以判定通过。丝杆带符号关系依据实际观测一致性，不冒充未知设计意图或Reverse枚举语义。禁止方向仍用原生装配移动求解。每个允许方向之后核验原配合参数、数量、固定状态、全部姿态和历史算例状态恢复，再开始下一项。

`linear_allowed_trial_strategy`在此模式明确为临时Motion；`native_motion_study_solved`仅在真实Motion分支通过时为true。`global_DOF_certified`、`whole_travel_certified`继续为false。失败不改换驱动重算，已知状态可恢复；原生未知不得恢复或重试写入。恢复时发生原生崩溃仍是失败，不将早先成功的局部求解升级为整任务通过。

螺旋原生模式、数值、Reverse和Alignment，以及限位最小／最大距离、Flip和Alignment在身份与参数快照中保护。参数模式仅排除限位的可变当前距离；身份模式继续记录当前距离，实际全部位姿门禁保留。非线性参数不可读取返回`CONNECTION_REFERENCE_INVALID`与`native_nonlinear_parameters_unavailable`，不以空值认证签名。完整普通参数、持久参考和健康校验不删减，旧读取对照器保持冻结。额外配合参数／数量／固定／算例状态证据只在内部`verification_details=true`时采集，不增加公开工具或日常批次的重复读取。

局部用途澄清：`plan_mechanism_task(auto_plan=true, connection_intent=[...])` 允许 AI 只补充少量明确的连接用途，复用当前首轮体检的其他建议目标。同一零件对只能出现一次；未澄清连接、未覆盖组件、候选搜索未完成、原生不支持项仍会阻断，不生成执行令牌。不可同时传分组、解除固定、范围或替换已有待确认方案。合并方案仍须原普通规划及原生预演，并确认全部机械目标及精确补项后执行。该能力不依据被删配合 ID，也不证明任意设计意图可自动推断。


alpha.45发布状态：局部用途合并及三类缺项补齐/保存重开通过；完整运动对照7/8，第三套成果反向原生时间轴结果获取断连，失败恢复及资源退出已核对。按用户要求先行预发布，不解除原完整Motion验收要求，不认证任意装配或另机启动问题已修复。


## alpha.47 整机摘要、解析几何快照与方案复核

原30工具保持。assembly_constraints任务可用get_mechanism_task(task_id=..., summary_only=true)读取保存阶段、assembly_brief及assembly_plan_review，summary_only是布尔值；其他任务仍用原get。它不访问CAD，也不执行迟到请求/退出的重新协调；busy或失败时next_action指向完整get读取原请求。摘要不代替当前原生准入、恢复核对或具体方案确认。默认get保持兼容。

snapshot_cursor与draft_cursor、structure_cursor、summary_only、collect_evidence互斥。每个快照游标绑定任务目录、模型、原生调查签名、源文件SHA及集合；只读保存证据，不重建COM、重新调查或撤销令牌。每页最多16行且完整UTF8页不超过8000字节，动态页边界只能向前；末页只说明当前集合后缀，其他集合与此前页仍需累计。篡改/丢失或跨任务游标明确拒绝，不回退重扫CAD。

原生调查另外保存加载、受支持且已隔离组件的圆柱/平面解析几何观察：世界坐标点、方向、半径和面积，最多20000行，截断和非法行明确记录。它不包含任意BRep/草图几何，不注册写入实体，不扩大原每件24圆柱/16平面规划参考预算。geometry_complete_for_captured_scope与planner_reference_geometry_complete独立；观察读全不等于可安全补齐。只读结构范围未增加几何读取。观察无持久参考字符串；完整原生写入参考保留服务端原调查文件。

AI优先读取摘要中的goals、questions和必要候选/组件；用户已说明的用途可复用，只集中澄清真实歧义。需要时再读geometry。归组仍用原group_seeds一次只读推荐与明确用途，不默认固定浮动件。原自动建议上限16目标、8页候选，以及普通整装配128目标/512新增、每原生批8目标/64新增均保持。调查内部仅在同一冻结快照内复用候选图和配对排序，签名/任务变化拒绝；不跨原生修改复用。

具体plan经过原生预演后生成令牌绑定的复核快照：全部目标、逐项动作及SI值/翻转/参考种类和哈希、全部组成员、固定变化。AI累计所有非空复核集合，解释完整机械目标与变更、原约束保留及有限试验范围，取得具体确认后一次execute，由原流程执行内部批次。快照阅读不授权执行，旧owner/关闭任务/消费令牌的复核页标记非当前。默认finish恢复，只有明确要保留已验证成果才keep_result=true。技术阻断、未覆盖组件、搜索或几何不完整继续保留，不能用摘要掩盖。

三个托管工具描述与总说明缩短，分阶段细节由当前任务next_action、具体方案和本契约提供。没有增加网页、测试服务或让用户手填引用ID。
