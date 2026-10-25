"""One owner for the existing public tools and managed dialogue sessions."""
import asyncio
import sys
from .task_engine import core,release_executor
from .motion_tasks import MotionTaskEngine,validate_prepare_arguments


class FormalEngine:
    def __init__(self,project,work,runtime):
        import motion_server as product
        self.product=product
        from .owner_transport import fingerprint
        self.source_fingerprint=fingerprint()
        self.tasks=MotionTaskEngine(project,work,runtime)
        product._task_engine=self.tasks
        product._formal_engine=self
        self.server_instance_id=self.tasks.server_instance_id
        self.managed_upgrade_guard=False
        if self.tasks.prior_unfinished:
            product.bridge._acquire_lease();self.managed_upgrade_guard=True

    @property
    def active(self):
        if self.managed_upgrade_guard and not self.tasks.active and not self.tasks.prior_unfinished:
            self.product.bridge.close()
            self.managed_upgrade_guard=False
        busy=any(j['status'] in {'queued','running'} for j in self.product.jobs._jobs.values())
        process=self.product.bridge._process
        return self.tasks.active or ('legacy_session' if busy or (process and process.poll() is None) else None)

    @property
    def prior_unfinished(self):return self.tasks.prior_unfinished

    def tool(self,name,arguments):
        managed={'prepare_mechanism_task','get_mechanism_task','plan_mechanism_task','execute_mechanism_task','finish_mechanism_task'}
        offline={'get_job','get_motion_summary','get_run_artifacts','read_run_poses','export_motion_curve'}
        from .owner_transport import fingerprint
        managed_recovery=name=='restore_model_checkpoint' and bool(self.tasks.active)
        if name not in offline|{'get_mechanism_task','finish_mechanism_task','finish_motion_session','get_recovery_state'} and not managed_recovery and fingerprint()!=self.source_fingerprint:
            raise core.StopBatch('HOST_SOURCE_CHANGED','源码已变化；先读取和收尾原任务，空闲后重连接入新宿主，不在旧任务中混用新源码。')
        if name=='prepare_mechanism_task':
            # Input errors are independent of service occupancy. Keep source
            # identity admission above, and every lease/native gate below.
            validate_prepare_arguments(arguments)
        recovery_session=self.tasks.sessions.get(self.tasks.active) if self.tasks.active and name in {'get_recovery_state','restore_model_checkpoint'} else None
        if self.tasks.prior_unfinished and name in {'get_recovery_state','restore_model_checkpoint'}:
            raise core.StopBatch('ORPHAN_NATIVE_SESSION_UNAVAILABLE','原活会话丢失；get_mechanism_task读取旧归属记录，不能用主安装日志冒充该任务状态。',
                {'tasks':self.tasks.get(),'native_calls':False})
        binding=self.artifact_binding(arguments) if name in offline|{'replay_motion_frame'} else None
        if name=='prepare_mechanism_task' and (self.product.bridge._process or any(j['status'] in {'queued','running'} for j in self.product.jobs._jobs.values())):
            raise core.StopBatch('LEGACY_SESSION_REQUIRES_FINISH','AI先调用finish_motion_session结束旧工具会话，再创建受管任务。')
        if name=='prepare_mechanism_task':
            # Reuse the upgrade/install lease while a managed CAD task owns its native copy.
            self.product.bridge._acquire_lease();self.managed_upgrade_guard=True
        if name not in managed|offline and not (name=='replay_motion_frame' and binding) and not recovery_session and self.tasks.active:
            raise core.StopBatch('MANAGED_TASK_ACTIVE','已有受管任务；使用get_mechanism_task读取，不向另一实例派发。',{'task_id':self.tasks.active})
        original_artifacts=self.product.artifacts;original_bridge=self.product.bridge
        bridge_override=False
        try:
            if recovery_session:
                if not recovery_session.bridge:raise core.StopBatch('MANAGED_RUNTIME_NOT_READY','任务没有可用的原生连接；读取该任务收尾记录，不改查主安装日志。',
                    {'task_id':self.tasks.active,'phase':self.tasks.tasks.get(self.tasks.active,{}).get('phase'),
                     'next_tool':'get_mechanism_task','arguments':{'task_id':self.tasks.active},'native_calls':False})
                if name=='restore_model_checkpoint':
                    if self.tasks.tasks[self.tasks.active].get('busy'):raise core.StopBatch('TASK_BUSY')
                    recovery_session.admit_owned_recovery(arguments.get('model_id'),arguments.get('checkpoint_id'),arguments.get('allow_replacement_session',False))
                self.product.bridge=recovery_session.bridge;bridge_override=True
            if binding:
                from sw_mcp.artifacts import Artifacts
                runtime,task,session=binding
                self.product.artifacts=Artifacts(runtime)
                if name=='replay_motion_frame' and not arguments.get('saved_image_only',False):
                    if not session or task.get('closed') or task.get('busy') or arguments.get('wait_for_completion',True) is not True or arguments.get('use_input_snapshot'):
                        raise core.StopBatch('MANAGED_REPLAY_REQUIRES_LIVE_IDLE_TASK','受管任务原生回放须为本次未关闭空闲任务，使用同步回放；已关闭任务只能读已有截图。')
                    session.require_live_idle();self.product.bridge=session.bridge;bridge_override=True
            result=asyncio.run(self.product.mcp.call_tool(name,arguments))
            if recovery_session and name=='restore_model_checkpoint' and (result.structured_content or {}).get('ok') is True:
                recovery_session.accept_owned_recovery(result.structured_content['result'])
                self.tasks.mark_recovered(self.tasks.active,result.structured_content['result'])
        finally:
            self.product.artifacts=original_artifacts
            # Restore only temporary managed-session bindings. finish_legacy
            # intentionally replaces the default bridge after verified EOF.
            if bridge_override:self.product.bridge=original_bridge
        _=self.active  # Release only after every managed task has closed, never on MCP EOF.
        # The owner records outcomes independently of the short-lived MCP frontend.
        try:
            import time,uuid
            core.write(self.tasks.work/'mcp-calls'/(uuid.uuid4().hex+'.json'),{'tool':name,'arguments':arguments,
                'structured_result':result.structured_content,'at':time.time(),
                'scope':'owner_tool_handler_result_not_complete_JSONRPC_wire'})
        except (OSError,ValueError,TypeError) as error:
            print('Diagnostic recording failed: '+type(error).__name__,file=sys.stderr,flush=True)
        return result.model_dump(mode='json',by_alias=True)

    def artifact_binding(self,arguments):
        run=arguments.get('run_id');model=arguments.get('model_id')
        for tid,t in self.tasks.tasks.items():
            proof=t.get('verification',{})
            known={proof.get(k) for k in ('run_id','baseline_run_id','after_run_id')}-{None,''}
            if not ((run and run in known) or (model and model==t.get('model_id'))):continue
            session=self.tasks.sessions.get(tid)
            runtime=getattr(session,'runtime',None)
            if runtime is None:
                path=core.no_links(__import__('pathlib').Path(t['directory'])/'session/活会话归属.json')
                if not path.is_file():raise core.StopBatch('TASK_ARTIFACT_BINDING_MISSING')
                runtime=__import__('pathlib').Path(core.read(path)['runtime'])
            return core.no_links(runtime),t,session
        return None

    def finish_legacy(self):
        if self.tasks.active:raise core.StopBatch('MANAGED_TASK_ACTIVE')
        if any(j['status'] in {'queued','running'} for j in self.product.jobs._jobs.values()):
            raise core.StopBatch('LEGACY_JOBS_ACTIVE','旧任务仍在执行，不释放执行器。')
        bridge=self.product.bridge
        if bridge.recovery_state().get('recovery_required'):raise core.StopBatch('NATIVE_STATE_UNKNOWN')
        receipt=release_executor(bridge,self.tasks.work/'legacy-finish')
        from sw_mcp.bridge import Bridge
        self.product.bridge=Bridge(self.product.ROOT)
        self.product.jobs.bridge=self.product.bridge
        return {**receipt,'CAD_exit_requested':False,'model_restoration':'not_requested_legacy_copies_retained',
            'next_round_allowed':True}

    def shutdown(self):
        self.tasks.shutdown()
        self.product.bridge.close()
