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
        handoff=self.handoff_legacy() if name=='prepare_mechanism_task' else None
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
            if handoff:
                from sw_mcp.validation import packed
                result=packed({**result.structured_content,'legacy_session_handoff':handoff},result.is_error)
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

    def handoff_legacy(self):
        """Retire only this owner's provably idle retained executor, before task creation.

        The owner serializes tool handlers; the Bridge lock additionally excludes
        a retained background job. A completed journal alone proves no process
        ownership. No historic journal is deleted or rewritten by this handoff.
        """
        if self.tasks.active or self.tasks.prior_unfinished:return None
        bridge=self.product.bridge
        busy=[j['job_id'] for j in self.product.jobs._jobs.values() if j['status'] in {'queued','running'}]
        state=bridge.recovery_state();facts=bridge.session_admission(state)
        facts.update(running_job_ids=busy,request_status=state.get('status'),recovery_required=state.get('recovery_required'),
                     journal_derived_fields_consistent=state.get('journal_derived_fields_consistent',True),
                     journal_lease_retained=bridge._lease is not None)
        if busy:
            raise core.StopBatch('LEGACY_SESSION_REQUIRES_FINISH','旧工具任务仍在执行；先读取原job_id等待结果，不关闭执行器或创建新任务。',facts)
        if state.get('status')!='idle' or state.get('recovery_required') or facts['journal_derived_fields_consistent'] is not True or facts['pending_requests'] or facts['quarantined_request']:
            raise core.StopBatch('NATIVE_STATE_UNKNOWN','旧工具请求未确认空闲或日志不一致；保留现场，不自动交接。',facts)
        if bridge._process is None:return None
        if not bridge._lock.acquire(blocking=False):
            raise core.StopBatch('LEGACY_SESSION_REQUIRES_FINISH','旧连接仍在处理请求，未释放执行器；先读取原请求结果。',facts)
        try:
            # A successful handshake plus the exact retained Popen are required.
            # If requests were dispatched, the final journal must belong to both.
            try:hello=bridge._startup.result() if bridge._startup.done() and not bridge._startup.cancelled() else None
            except Exception:hello=None
            ready=isinstance(hello,dict) and hello.get('protocol_version')==1 and hello.get('ready') is True and type(hello.get('process_id')) is int and hello['process_id']>0
            facts['journal_solidworks_matches']=ready and state.get('solidworks_pid')==hello['process_id']
            if not ready or not facts['journal_lease_retained'] or (bridge._ever_dispatched and (facts['journal_owner_matches'] is not True or facts['journal_executor_matches'] is not True or facts['journal_solidworks_matches'] is not True)):
                raise core.StopBatch('NATIVE_STATE_UNKNOWN','无法核实旧连接握手及本宿主归属，不依据空闲日志清理执行器。',facts)
            import uuid
            folder=self.tasks.work/'legacy-handoffs'/uuid.uuid4().hex
            core.write(folder/'交接核对.json',facts)
            receipt=release_executor(bridge,folder)
            from sw_mcp.bridge import Bridge
            self.product.bridge=Bridge(self.product.ROOT);self.product.jobs.bridge=self.product.bridge
            receipt={**receipt,'admission':facts,'receipt_directory':str(folder),
                     'automatic_idle_handoff':True,'journal_deleted':False,'model_restoration':'not_requested_legacy_copies_retained'}
            core.write(folder/'交接结果.json',receipt)
            return receipt
        finally:bridge._lock.release()

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
        state=bridge.recovery_state()
        if state.get('recovery_required') or state.get('journal_derived_fields_consistent') is False or bridge._pending or bridge._quarantined_request:
            raise core.StopBatch('NATIVE_STATE_UNKNOWN')
        receipt=release_executor(bridge,self.tasks.work/'legacy-finish')
        from sw_mcp.bridge import Bridge
        self.product.bridge=Bridge(self.product.ROOT)
        self.product.jobs.bridge=self.product.bridge
        return {**receipt,'CAD_exit_requested':False,'model_restoration':'not_requested_legacy_copies_retained',
            'next_round_allowed':True}

    def shutdown(self):
        self.tasks.shutdown()
        self.product.bridge.close()
