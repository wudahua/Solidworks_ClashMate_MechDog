"""One conversation MCP owner; tasks are serialized and copies are restored before release."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid

HERE=Path(__file__).resolve().parent

from . import core,mate_worker,mate_motion,startup_gate
from .runtime_location import choose_runtime

SCOPE='one_concentric_mate_keep_rotation_declared_scope_12rpm_1s_30fps'

def short_name(instance):return re.sub(r'^(?:\d{4}_[a-f0-9]{8}_)+','',instance)

def matching_components(components,text,fixed):
    possible=[c for c in components if fixed is None or c['fixed_component'] is fixed]
    exact=[c for c in possible if text.casefold() in (c['instance'].casefold(),short_name(c['instance']).casefold())]
    return exact or [c for c in possible if text.casefold() in c['instance'].casefold()]

def mechanical_choices(components,text,fixed):
    matches=matching_components(components,text,fixed)
    return [{'name':re.sub(r'^(?:\d{4}_[a-f0-9]{8}_)+','',c['instance']),
             'instance':c['instance'],'role':('固定参考件' if c['fixed_component'] else '未固定参考件') if fixed is None else '固定参考件' if fixed else '浮动运动件',
             'fixed':c['fixed_component'],'component_origin_world_m':c.get('transform',[None]*12)[9:12]}
            for c in matches]

def release_executor(bridge,folder,timeout=8):
    """Only EOF to this retained Bridge child; wait for exit before dropping its journal lease."""
    process=bridge._process
    receipt={'executor_pid':process.pid if process else None,'ownership':'retained_Bridge_Popen',
             'force_kill':False,'CAD_exit_requested':False,'timeout_s':timeout}
    if process:
        try:
            if process.stdin and not process.stdin.closed:process.stdin.close()
            process.wait(timeout=timeout)
        except (OSError,subprocess.TimeoutExpired) as error:
            receipt.update(confirmed=False,error=type(error).__name__,executor_exit_code=process.poll())
            core.write(folder/'执行器收尾.json',receipt)
            raise core.StopBatch('EXECUTOR_EXIT_UNCONFIRMED','执行器尚未确认结束，保留租约和现场，不启动下一轮。',receipt)
        receipt.update(confirmed=True,executor_exit_code=process.returncode)
    else:receipt.update(confirmed=True,executor_exit_code=None,executor_started=False)
    bridge.close()
    core.write(folder/'执行器收尾.json',receipt)
    return receipt

class ConversationSession(mate_worker.Session):
    def __init__(self,project,folder,runtime_base,moving='',reference='',on_stage=None):
        self.moving_hint=moving;self.reference_hint=reference;self.on_stage=on_stage;self.initial_inspection=None
        super().__init__(project,folder,runtime_base)
    def state(self,status,message,**kw):
        super().state(status,message,**kw)
        self.persist_ownership()
        if self.on_stage:self.on_stage(status,message)
    def persist_ownership(self,in_flight=None):
        from .process_identity import observe
        proc=getattr(self,'proc',None);bridge=getattr(self,'bridge',None)
        executor=getattr(bridge,'_process',None)
        path=self.folder/'活会话归属.json'
        prior=core.read(path) if path.exists() else {}
        value={'owner':observe(os.getpid()),'CAD':observe(proc.pid) if proc else prior.get('CAD'),
            'executor':observe(executor.pid) if executor else prior.get('executor'),
            'runtime':str(self.runtime),'model_id':getattr(self,'model',None),
            'checkpoint_id':getattr(self,'checkpoint',None),'native_unknown':getattr(self,'unknown',False),
            'in_flight':in_flight if in_flight is not None else prior.get('in_flight'),
            'committed':getattr(self,'committed',False),'ended':getattr(self,'ended',False),'observed_at':time.time()}
        core.write(path,value)
    def call(self,operation,**kw):
        self.persist_ownership({'operation':operation,'started':time.time()})
        try:return super().call(operation,**kw)
        finally:
            self.persist_ownership({})
    def require_live_idle(self):
        if self.unknown:raise core.StopBatch('NATIVE_STATE_UNKNOWN','原生状态未知，未重新派发。')
        if not self.proc or self.proc.poll() is not None or not self.bridge or not self.bridge._process or self.bridge._process.poll() is not None:
            self.unknown=True;self.persist_ownership()
            raise core.StopBatch('TASK_NATIVE_CONNECTION_LOST','保留的CAD或执行器已退出，不重新附着或重建写入。')
        recovery=self.bridge.recovery_state()
        if recovery.get('recovery_required') is not False:
            self.unknown=True;self.persist_ownership()
            raise core.StopBatch('NATIVE_STATE_UNKNOWN','执行器日志要求恢复，未继续旧确认。',recovery)
        return {'CAD_pid':self.proc.pid,'executor_pid':self.bridge._process.pid,'journal_idle':True,
                'ownership':'retained_Popen_and_Bridge_not_recreated_COM','COM_called':False}
    def rescan(self,hint=''):
        from sw_mcp.circular_recommendations import recommend,require_same_state
        start=self.call('_circular_reference_state',model_id=self.model)
        inspection=self.call('inspect_model',model_id=self.model,detail_level='full')
        if self.initial_inspection is None:self.initial_inspection=inspection
        if not self.moving_hint and not self.reference_hint:
            return super().rescan(hint)
        if not (self.moving_hint and self.reference_hint):raise core.StopBatch('INCOMPLETE_MECHANICAL_SCOPE','缩小范围时须明确运动件和参考件名称；也可以两者均留空自动推荐。')
        components=inspection['components'];selected=[]
        for text,fixed in [(self.moving_hint,False),(self.reference_hint,True)]:
            matches=matching_components(components,text,fixed)
            if len(matches)!=1:
                choices=mechanical_choices(components,text,fixed)
                if not choices:
                    choices=mechanical_choices(components,'',fixed)
                raise core.StopBatch('COMPONENT_NAME_AMBIGUOUS','名称或固定状态不能唯一匹配，请通过零件名称或实例后缀澄清。',
                    {'hint':text,'role':'固定参考件' if fixed else '浮动运动件','choices':choices,
                     'question':'您指的是'+('固定参考件' if fixed else '浮动运动件')+'中的哪一个？请用名称、实例后缀或机械用途说明，无需实体ID。',
                     'field':'reference_component_hint' if fixed else 'moving_component_hint'})
            selected.extend(matches)
        rows=[]
        for c in selected:rows.extend(mate_motion.component_geometry(self,c['component_id'],'circular_edge'))
        end=self.call('_circular_reference_state',model_id=self.model)
        require_same_state(start,end,'conversation_scoped_recommendation',self.bridge)
        mates=inspection.get('mates',[])
        context=all(len(m.get('entities',[]))==2 and all(r.get('component_id') and r.get('geometry') for r in m['entities']) for m in mates)
        value=recommend(rows,mates,True,self.model,5,context_complete=context)
        value.update(reference_state_signature=end['signature'],geometry_complete=False,scope_geometry_complete=True,
                     ranking_scope='explicitly_named_component_pair_only_not_whole_assembly',selected_instances=[c['instance'] for c in selected])
        self.recommendation=value;self.plan=None
        core.write(self.folder/'推荐.json',value)
        self.state('recommended','圆边组合已自动推荐；在对话中确认机械用途及试验范围。')
        return value
    def restore(self):
        return self.audit_restore(super().restore())
    def audit_restore(self,value):
        if self.initial_inspection:
            current=self.call('inspect_model',model_id=self.model,detail_level='full')
            old={c['instance']:c for c in self.initial_inspection['components']};new={c['instance']:c for c in current['components']}
            same=old.keys()==new.keys()
            delta=max((abs(x-y) for n in old for x,y in zip(old[n]['transform'],new[n]['transform'])),default=0) if same else None
            fixed=same and all(old[n]['fixed_component']==new[n]['fixed_component'] for n in old)
            mates_equal=len(current.get('mates',[]))==len(self.initial_inspection.get('mates',[]))
            audit={'components':len(new),'maximum_transform_delta':delta,'fixed_states_equal':fixed,'mate_count_equal':mates_equal,
                   'native_checkpoint_restore':value,'passed':same and fixed and mates_equal and delta<=1e-7}
            core.write(self.folder/'恢复独立核对.json',audit)
            if not audit['passed']:self.import_restored=False;self.unknown=True;raise core.StopBatch('RESTORE_AUDIT_FAILED',diagnostics=audit)
        return value
    def admit_owned_recovery(self,model,checkpoint,replacement=False):
        if replacement or model!=self.model or checkpoint!=self.checkpoint or not self.model or not self.checkpoint:
            raise core.StopBatch('MANAGED_RECOVERY_SCOPE_MISMATCH','本任务仅允许原活连接恢复导入检查点；不更换实例或借用其他检查点。')
        if not self.proc or self.proc.poll() is not None or not self.bridge or not self.bridge._process or self.bridge._process.poll() is not None:
            raise core.StopBatch('MANAGED_RECOVERY_CONNECTION_LOST','缺少保留的原生活连接，不从JSON重建COM。')
        b=self.bridge
        with b._state_lock:pending=bool(b._pending) or b._quarantined_request is not None
        if pending or b.cad_operation_state=='unknown_after_timeout' or not b._reader_thread or not b._reader_thread.is_alive():
            raise core.StopBatch('RECOVERY_WAIT_FOR_NATIVE_OUTCOME','旧请求或通信链路尚未确认结束；只能读取原响应，未派发恢复。')
        state=b.recovery_state()
        if state.get('status') not in {'idle','unknown'}:raise core.StopBatch('RECOVERY_WAIT_FOR_NATIVE_OUTCOME')
        if state.get('executor_pid')!=b._process.pid or state.get('solidworks_pid')!=self.proc.pid:
            raise core.StopBatch('MANAGED_RECOVERY_IDENTITY_MISMATCH')
        core.write(self.folder/'明确恢复准入.json',{'journal_before_restore':state,'same_retained_native_handles':True,
            'replacement_session':False,'allowed_checkpoint':checkpoint,'original_write_replayed':False})
    def accept_owned_recovery(self,value):
        if not core.restored_ok(value):self.unknown=True;raise core.StopBatch('RESTORE_NOT_VERIFIED')
        self.audit_restore(value)
        self.unknown=False;self.import_restored=True;self.committed=False;self.plan=None;self.recommendation=None
        core.write(self.folder/'恢复.json',value)
        self.state('restored','已显式恢复并核对原导入检查点；未重放失败写入，可继续安全收尾。')
    def capture_applied_result(self):
        cp=self.call('create_model_checkpoint',model_id=self.model)
        self.result_checkpoint=cp['checkpoint_id']
        self.result_inspection=self.call('inspect_model',model_id=self.model,detail_level='full')
        core.write(self.folder/'成果检查点.json',{'checkpoint':cp,'inspection':self.result_inspection,
            'reason':'preserve_applied_mate_before_verification_restores_pre_mate_checkpoint'})
        return cp
    def close(self):
        if self.unknown:raise core.StopBatch('NATIVE_STATE_UNKNOWN','状态未确认，停止后续操作；AI读取已有证据，不重复写入。')
        if self.bridge:
            try:release_executor(self.bridge,self.folder)
            except Exception:self.unknown=True;raise
            self.bridge=None
        if self.proc and self.proc.poll() is not None:
            # Retained process handle, never a new PID lookup or a replacement COM connection.
            core.write(self.folder/'exit.json',{'owned_pid':self.proc.pid,'native_process_exited':True,
                'exit_code':self.proc.returncode,'normal_zero_exit':self.proc.returncode==0,'force_kill':False,
                'native_exit_observed_by':'retained_Popen','helper_exit_code':None})
            self.proc=None
        return super().close()

class TaskEngine:
    def __init__(self,project,work,runtime_base,session_factory=ConversationSession):
        self.project=Path(project);self.work=Path(work);self.runtime_base=Path(runtime_base)
        core.no_links(self.work);self.work.mkdir(parents=True,exist_ok=True)
        self.runtime_base=choose_runtime(self.runtime_base,self.work)
        self.session_factory=session_factory;self.tasks={};self.sessions={};self.active=None;self.server_instance_id=uuid.uuid4().hex
        self.lock=threading.RLock();self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.prior_unfinished=[]
        for p in self.work.glob('task-*/任务状态.json'):
            core.no_links(p);v=core.read(p)
            if v.get('task_id')!=p.parent.name.removeprefix('task-') or Path(v['directory']).resolve()!=p.parent.resolve():
                raise core.StopBatch('INVALID_PERSISTED_TASK_IDENTITY','任务记录归属不匹配，未接管。')
            self.tasks[v['task_id']]=v
            if not v.get('closed'):self.prior_unfinished.append(str(p))
    def save(self,t):
        t['updated_at']=time.time()
        core.write(Path(t['directory'])/'任务状态.json',t)
    def get(self,task_id=''):
        if not task_id:
            with self.lock:
                return {'server_pid':os.getpid(),'server_instance_id':self.server_instance_id,'active_task':self.active,
                        'prior_unfinished':self.prior_unfinished,'tasks':[{'task_id':t['task_id'],'phase':t['phase'],
                            'closed':t['closed'],'session_attached':t['task_id'] in self.sessions,
                            'source':t['source']} for t in self.tasks.values()],
                        'next_action':{'tool':'get_mechanism_task','instruction':'AI从已有任务读取进度和待确认方案，不重复prepare或execute。'}}
        if not re.fullmatch('[a-f0-9]{32}',task_id):raise core.StopBatch('INVALID_TASK_ID')
        with self.lock:
            if task_id not in self.tasks:raise core.StopBatch('TASK_NOT_IN_CURRENT_SERVER','没有该任务记录；可不传task_id查询已有任务。')
            t=self.tasks[task_id]
            value=json.loads(json.dumps(t,ensure_ascii=False))
            if not t.get('closed') and t.get('server_instance_id')!=self.server_instance_id:
                value.update(busy=False,connection_status='owner_lost_read_only',persisted_phase=t['phase'],
                    task_owner_available=False,next_action={'tool':'finish_mechanism_task','arguments':{'task_id':task_id,'close_unrestored':False},
                    'instruction':'原活会话丢失，不能接续旧写入。说明恢复未验证；用户明确同意关闭失败记录后，使用close_unrestored=true核对旧资源已退出并保留副本归档。未知状态仍阻断，不从JSON重建COM。'})
            else:value.update(task_owner_available=True,connection_status='closed_record' if t.get('closed') else 'attached')
            s=self.sessions.get(task_id)
            if s and not t.get('busy') and not t.get('closed') and getattr(s,'model',None) and hasattr(s,'require_live_idle'):
                try:value['connection_check']=s.require_live_idle()
                except core.StopBatch as error:
                    value.update(connection_status='native_unavailable',connection_error={'code':error.code,'message':str(error)},
                        next_action={'tool':'get_mechanism_task','arguments':{'task_id':task_id},
                                     'instruction':'AI读取已保存归属及原生日志；连接不可用时不execute、不重新prepare。'})
                    if getattr(s,'checkpoint',None):
                        value['recovery_action']={'first':{'tool':'get_recovery_state','arguments':{}},
                            'then_if_same_live_handles_and_original_request_ended':{'tool':'restore_model_checkpoint',
                                'arguments':{'model_id':s.model,'checkpoint_id':s.checkpoint}},
                            'instruction':'用户授权恢复原状态后，仅在原活连接和旧请求结束均核对通过时恢复导入检查点；不换实例、不重放写入。'}
            return value
    def mark_recovered(self,task_id,value):
        with self.lock:
            t=self.tasks[task_id]
            if t.get('error'):t['original_failure']=t.pop('error')
            t.pop('plan_token',None)
            t.update(phase='recovered',plan_token_revoked=True,explicit_recovery=value,
                next_action={'tool':'finish_mechanism_task','arguments':{'task_id':task_id},
                             'instruction':'导入检查点已恢复；结束原任务后再准备新任务，旧确认不再有效。'})
            self.save(t)
    def _require_session(self,task_id):
        if self.tasks[task_id].get('busy'):raise core.StopBatch('TASK_BUSY','任务仍在处理，不重复排队。')
        if task_id not in self.sessions:
            raise core.StopBatch('TASK_OWNER_UNAVAILABLE','原活会话已丢失，保留待确认方案和证据，只读查询，不重新派发写入。',
                                {'task_id':task_id,'next_tool':'get_mechanism_task','retry_write_allowed':False})
        session=self.sessions[task_id]
        if getattr(session,'model',None) and hasattr(session,'require_live_idle'):session.require_live_idle()
    def _submit(self,t,phase,operation):
        with self.lock:
            if t.get('busy'):raise core.StopBatch('TASK_BUSY','正在执行，AI应读取任务状态，不重复提交。')
            t.update(busy=True,phase=phase);self.save(t)
        def work():
            try:operation()
            except Exception as error:
                with self.lock:
                    s=self.sessions.get(t['task_id'])
                    if getattr(error,'code','')=='COMPONENT_NAME_AMBIGUOUS' and s and not s.unknown and not s.committed:
                        t.update(phase='awaiting_component_selection',model_id=s.model,component_selection=error.diagnostics,
                                 next_action={'tool':'plan_mechanism_task','arguments':{'task_id':t['task_id']},
                                    'instruction':'AI用候选名称、固定/浮动角色和位置解释歧义；用户以自然语言选择后传入对应名称线索，复用本次副本，不重复导入。'})
                        core.write(Path(t['directory'])/'名称澄清.json',error.diagnostics)
                        return
                    t.update(phase='failed',error={'code':getattr(error,'code',type(error).__name__),'message':str(error),
                        'diagnostics':getattr(error,'diagnostics',None),'native_unknown':bool(s and s.unknown),'retry_write_allowed':False},
                        next_action={'tool':'get_mechanism_task','arguments':{'task_id':t['task_id']},'instruction':'AI读取已有错误及证据；未知状态不重试写入。'})
                    core.write(Path(t['directory'])/'失败诊断.json',{'error':t['error'],'traceback':traceback.format_exc()})
            finally:
                with self.lock:t['busy']=False;self.save(t)
        self.pool.submit(work)
        return {'task_id':t['task_id'],'accepted':True,'next_tool':'get_mechanism_task'}
    def prepare(self,path,moving='',reference=''):
        assembly=core.no_links(Path(path))
        if not assembly.is_absolute() or not assembly.is_file() or assembly.suffix.lower()!='.sldasm':raise core.StopBatch('INVALID_ASSEMBLY_PATH')
        with self.lock:
            if self.prior_unfinished:raise core.StopBatch('PRIOR_TASK_UNCONFIRMED','保留上次任务证据，不自动重建会话。',{'records':self.prior_unfinished})
            if self.active:raise core.StopBatch('TASK_SESSION_ACTIVE','先完成当前任务收尾，不启动第二个执行器。',{'task_id':self.active})
            task_id=uuid.uuid4().hex;folder=self.work/('task-'+task_id);folder.mkdir()
            t={'task_id':task_id,'directory':str(folder),'source':str(assembly),'phase':'created','busy':False,'closed':False,
               'moving_component_hint':moving,'reference_component_hint':reference,'source_hashes':core.fixture_hashes(assembly),
               'scope':SCOPE,'confirmation_required':True,'automatic_write_retry':False,'server_pid':os.getpid(),
               'server_instance_id':self.server_instance_id}
            self.tasks[task_id]=t;self.active=task_id
        def operation():
            def stage(status,message):
                with self.lock:t.update(native_stage=status,message=message);self.save(t)
            s=self.session_factory(self.project,folder/'session',self.runtime_base,moving=moving,reference=reference,on_stage=stage)
            self.sessions[task_id]=s
            recommendations=s.discover(assembly)
            self._proposals(t,recommendations)
        return self._submit(t,'preparing',operation)
    def _proposals(self,t,recommendations):
        t['proposals']=[{'candidate_id':'candidate-'+str(i+1),'instances':r['instances'],'geometry':r['geometry'],
            'reason':r['reason'],'warnings':r.get('warnings',[]),'rank_cost':r['rank_cost']} for i,r in enumerate(recommendations['recommendations'])]
        t.update(phase='proposal_ready',model_id=self.sessions[t['task_id']].model,
            requires_selection=recommendations.get('requires_geometric_selection',True),
            ranking_scope=recommendations.get('ranking_scope','queried_native_geometry'),geometry_complete=recommendations['geometry_complete'],
            selection_question=recommendations['selection_question'],next_action={'tool':'plan_mechanism_task','arguments':{'task_id':t['task_id']},
                'instruction':'AI解释推荐；有机械歧义只问名称或用途，不把几何排序当作设计意图。'})
        t.pop('component_selection',None)
    def plan(self,task_id,candidate_id='',moving_component_hint='',reference_component_hint=''):
        t=self.tasks[task_id]
        self._require_session(task_id)
        if t['phase']=='awaiting_component_selection':
            if not moving_component_hint and not reference_component_hint:
                return {'task_id':task_id,'needs_component_selection':True,**t['component_selection']}
            def clarify():
                s=self.sessions[task_id]
                s.moving_hint=moving_component_hint or s.moving_hint
                s.reference_hint=reference_component_hint or s.reference_hint
                t.update(moving_component_hint=s.moving_hint,reference_component_hint=s.reference_hint)
                self._proposals(t,s.rescan())
            return self._submit(t,'clarifying_components',clarify)
        if moving_component_hint or reference_component_hint:raise core.StopBatch('COMPONENT_SELECTION_NOT_REQUESTED')
        if t['phase']!='proposal_ready':raise core.StopBatch('TASK_NOT_READY_FOR_PLAN')
        if not candidate_id:
            if t['requires_selection'] or len(t['proposals'])!=1:
                return {'task_id':task_id,'needs_selection':True,'question':t['selection_question'],'proposals':t['proposals']}
            candidate_id=t['proposals'][0]['candidate_id']
        match=[i for i,r in enumerate(t['proposals']) if r['candidate_id']==candidate_id]
        if len(match)!=1:raise core.StopBatch('INVALID_TASK_CANDIDATE')
        index=match[0]
        def operation():
            s=self.sessions[task_id];native=s.preview(index)
            components=s.call('inspect_model',model_id=s.model,detail_level='components')['components']
            from . import concentric_card
            # Eligibility and initial alignment are checked before authorizing a trial solve.
            card=concentric_card.create(native,components,s.recommendation['reference_state_signature'],False,False)
            core.write(s.folder/'对话待确认测试卡.json',card)
            token=uuid.uuid4().hex
            t.update(phase='awaiting_confirmation',selected_index=index,selected_candidate=candidate_id,plan_token=token,
                selected_edges=[native['reference_a']['entity_id'],native['reference_b']['entity_id']],
                proposal={'instances':t['proposals'][index]['instances'],'mate_type':'concentric','lock_rotation':False,
                    'test_speed_rpm':12,'duration_s':1,'output_fps':30,'expected_twist_deg':72,
                    'scope':SCOPE,'restore_import_checkpoint_at_finish':True,'original_files_modified':False,
                    'retained':['signed_rotation','axial_displacement','other_components','initial_poses'],
                    'allowed_constraint_effect':['transverse_axis_offset','axis_tilt'],
                    'whole_pump_transmission_certified':False},
                next_action={'tool':'execute_mechanism_task','arguments':{'task_id':task_id,'plan_token':token},
                    'instruction':'向用户说明零件对、试验参数、同轴约束允许影响和恢复方式；获得明确授权后一次提交。开发验收使用事先批准的测试卡，不能伪称真人确认。'})
        return self._submit(t,'planning',operation)
    def execute(self,task_id,plan_token,confirmed=False,scope_confirmed=False):
        t=self.tasks[task_id]
        self._require_session(task_id)
        if t.get('busy'):raise core.StopBatch('TASK_BUSY','正在处理，不消耗确认或重复排队。')
        if confirmed is not True or scope_confirmed is not True:raise core.StopBatch('CONFIRMATION_REQUIRED','需要对话中明确同意该方案及同轴约束验证范围。')
        if t.get('plan_token')!=plan_token:raise core.StopBatch('PLAN_TOKEN_MISMATCH')
        if t.get('execution_consumed'):raise core.StopBatch('TASK_ALREADY_EXECUTED','已提交过本方案；AI读取现有结果，不重试写入。')
        if t['phase']!='awaiting_confirmation':raise core.StopBatch('TASK_NOT_READY_FOR_EXECUTION')
        t['execution_consumed']=True;t['confirmation']={'confirmed':True,'scope_confirmed':True,'plan_token':plan_token,'time':time.time()};self.save(t)
        def operation():
            s=self.sessions[task_id]
            mate_motion.baseline(s,t['selected_index'],True,True)
            if [s.plan['reference_a']['entity_id'],s.plan['reference_b']['entity_id']]!=t['selected_edges']:
                raise core.StopBatch('CONFIRMED_PAIR_CHANGED','保留已采集基线，未创建配合。')
            s.apply(True)
            if hasattr(s,'capture_applied_result'):t['result_checkpoint_id']=s.capture_applied_result()['checkpoint_id']
            result=mate_motion.verify(s,True)
            passed=result.get('scope_verification',{}).get('scope_acceptance_passed') is True
            t.update(phase='verified' if passed else 'verification_failed',verification={'declared_scope_passed':passed,
                'full_trajectory_equivalent':result.get('passed') is True,'scope':SCOPE,
                'baseline_run_id':result['baseline']['run_id'],'after_run_id':result.get('after',{}).get('run_id'),
                'whole_mechanism_or_DOF_certified':False,'test_card_id':(result.get('mechanical_card') or {}).get('card_id')},
                next_action={'tool':'finish_mechanism_task','arguments':{'task_id':task_id},'instruction':'AI恢复导入检查点，核对执行器和CAD退出；不靠重启MCP开始下一轮。'})
        return self._submit(t,'running',operation)
    def close_orphan(self,t,confirmed):
        """Retire a pre-execution failed record, never restore/rebind native resources from JSON."""
        if confirmed is not True:raise core.StopBatch('ORPHAN_CLOSE_CONFIRMATION_REQUIRED','原会话已丢失，恢复未验证；须明确同意保留副本并关闭失败记录。')
        if t.get('execution_consumed') or t['phase'] not in {'awaiting_confirmation','proposal_ready','awaiting_component_selection','failed'}:
            raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','已执行或阶段不明确的旧任务继续保留，未解除写入保护。')
        from .process_identity import same_process
        folder=core.no_links(Path(t['directory'])/'session')
        ownership_path=core.no_links(folder/'活会话归属.json')
        if not ownership_path.is_file():raise core.StopBatch('ORPHAN_RESOURCE_IDENTITY_MISSING','缺少旧资源归属证据，保留记录。')
        ownership=core.read(ownership_path)
        if ownership.get('owner',{}).get('pid')!=t['server_pid'] or ownership.get('native_unknown') is not False or ownership.get('in_flight')!={} or ownership.get('committed') is not False:
            raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','归属、原生请求或提交状态未确认。')
        proof={}
        for role in ['owner','CAD','executor']:
            identity=ownership.get(role)
            if identity:
                if not identity.get('created'):raise core.StopBatch('ORPHAN_RESOURCE_IDENTITY_MISSING')
                observed=same_process(identity);proof[role]={'recorded':identity,'now':observed}
                if observed['status'] not in {'exited','pid_reused'}:
                    raise core.StopBatch('ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED','旧资源仍在运行或无法确认，不关闭记录。',proof)
            elif role=='owner' or t.get('model_id'):
                raise core.StopBatch('ORPHAN_RESOURCE_IDENTITY_MISSING','已登记模型缺少原生进程身份。')
        if ownership.get('executor'):
            journal_path=core.no_links(Path(ownership['runtime'])/'runs/executor-state.json')
            if not journal_path.is_file():raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','旧请求日志缺失，保留记录。')
            journal=core.read(journal_path)
            if journal.get('status')!='idle' or journal.get('recovery_required') is not False or journal.get('executor_pid')!=ownership['executor']['pid'] or journal.get('solidworks_pid')!=ownership['CAD']['pid']:
                raise core.StopBatch('ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','原生日志未证明旧请求空闲。')
            proof['native_journal']={'sha256':core.digest(journal_path),'status':'idle','current_owner_attached':False}
        gate=startup_gate.observe();proof['executor_gate']=gate
        if gate.get('status')!='available':raise core.StopBatch('ORPHAN_EXECUTOR_GATE_NOT_IDLE','执行器门禁不空闲，不允许下一任务。',gate)
        if core.fixture_hashes(Path(t['source']))!=t['source_hashes']:raise core.StopBatch('SOURCE_CHANGED')
        proof.update(restoration_verified=False,source_files_unchanged=True,CAD_calls=0,processes_terminated=False)
        backup=Path(t['directory'])/'关闭前原任务状态.json'
        if not backup.exists():
            with backup.open('x',encoding='utf8') as f:json.dump(t,f,ensure_ascii=False,indent=2)
        core.write(Path(t['directory'])/'异常收尾核对.json',proof)
        t.update(closed=True,phase='closed_unverified',busy=False,plan_token_revoked=True,task_outcome='failed_owner_lost',
            finish={'restoration':None,'restoration_status':'not_verified','session':{'ended':True,'import_checkpoint_restored':False,
                'finish_mode':'failed_record_closed_copy_preserved_without_restore'},
                'native_exit':{'native_process_exited':True,'exit_code':None,'normal_zero_exit':False},
                'executor_exit':{'confirmed':True,'executor_exit_code':None,'normal_zero_exit':False},
                'source_files_unchanged':True,'next_round_allowed':True,'previous_task_passed':False},
            next_action={'tool':'prepare_mechanism_task','arguments':{'assembly_path':t['source']},
                'instruction':'旧任务按失败保留，恢复未验证；可创建新的独立副本，不能复用旧方案、基线或令牌。'})
        self.save(t)
        self.prior_unfinished=[p for p in self.prior_unfinished if Path(p)!=Path(t['directory'])/'任务状态.json']
        return {'task_id':t['task_id'],'closed':True,'result':t['finish'],'replayed':False}
    def finish(self,task_id,close_unrestored=False):
        t=self.tasks[task_id]
        if t.get('closed'):return {'task_id':task_id,'closed':True,'result':t['finish'],'replayed':False}
        if task_id not in self.sessions and t.get('server_instance_id')!=self.server_instance_id:
            return self.close_orphan(t,close_unrestored)
        self._require_session(task_id)
        def operation():
            s=self.sessions.get(task_id)
            if not s:raise core.StopBatch('TASK_SESSION_NOT_CREATED')
            if s.unknown:raise core.StopBatch('NATIVE_STATE_UNKNOWN','AI保留现场和现有证据，不重试写入或关闭。')
            restored=(s.audit_restore(core.read(s.folder/'恢复.json')) if getattr(s,'import_restored',False) else s.restore()) if s.model else None
            receipt=s.close()
            source_unchanged=core.fixture_hashes(Path(t['source']))==t['source_hashes']
            native=core.read(s.folder/'exit.json') if (s.folder/'exit.json').exists() else None
            executor=core.read(s.folder/'执行器收尾.json') if (s.folder/'执行器收尾.json').exists() else {'confirmed':s.bridge is None}
            if not source_unchanged:raise core.StopBatch('SOURCE_CHANGED')
            if not receipt['ended'] or executor.get('confirmed') is not True:raise core.StopBatch('TASK_FINISH_UNCONFIRMED')
            t.update(closed=True,phase='closed',finish={'restoration':restored,'session':receipt,'native_exit':native,'executor_exit':executor,
                'cleanup_status':'warning_nonzero_native_exit' if native and native.get('normal_zero_exit') is not True else 'pass' if native else 'not_started',
                'source_files_unchanged':True,'next_round_allowed':True},next_action={'tool':'prepare_mechanism_task','arguments':{'assembly_path':t['source']},
                    'instruction':'同一个MCP服务可开始下一轮；不重用上轮基线、实体或方案。'})
            if native and native.get('normal_zero_exit') is not True:t.update(phase='closed_with_cleanup_warning',task_outcome='completed_with_cleanup_warning')
            with self.lock:self.active=None
        return self._submit(t,'finishing',operation)
    def shutdown(self):
        # MCP EOF does not authorize discarding an unfinished native task.
        self.pool.shutdown(wait=True)

