"""Bounded rotary/linear dialogue workflow; geometry recommendations do not infer intent."""
import hashlib,json,math,time,uuid
from pathlib import Path
from .task_engine import TaskEngine,ConversationSession,core,matching_components,mechanical_choices
from . import mate_motion,startup_gate,source_integrity,task_execution,task_progress
from sw_mcp.native_grid import require_grid,MINIMUM_INTERVALS


def prepare_limits():
    """Public card limits, also consumed by gear admission. No CAD inspection."""
    grid={'minimum_intervals':MINIMUM_INTERVALS,'duration_times_fps_must_be_integer':True}
    return {
        'motion':{'maximum_duration_s':5,'minimum_output_fps':5,'maximum_output_fps':120,'maximum_frames':601,**grid},
        'concentric':{'motion':'rotary','speed_rpm':12,'duration_s':1,'allowed_output_fps':[30],'maximum_frames':31},
        'gear_transmission':{'motion':'rotary','maximum_speed_rpm':60,'maximum_duration_s':2,
            'allowed_output_fps':[30,60],'maximum_frames':121,'minimum_travel_must_be_zero':True,**grid},
        'external_gear_pair':{'motion':'rotary','maximum_speed_rpm':60,'maximum_duration_s':2,
            'minimum_output_fps':5,'maximum_output_fps':120,'maximum_frames':241,'minimum_travel_must_be_zero':True,
            'plan_native_grid_confirmation_required':True,'future_native_grid_guaranteed':False,**grid}}


def environment_prepare_limits(environment):
    """Explain the distinction between low-level ceilings and dialogue cards."""
    return {**environment,'budget_matrix':{**environment.get('budget_matrix',{}),'managed_tasks':prepare_limits()},
            'budget_matrix_scope':'new_solve_is_low_level_ceiling_managed_tasks_have_separate_card_limits',
            'sampling_fps_confirmation':'prepare_validates_request_plan_confirms_exact_native_grid_no_interpolation'}


def parameters(motion,speed,duration,fps,reverse,minimum):
    if motion not in {'rotary','linear'}:raise core.StopBatch('INVALID_MOTION_TYPE')
    for n in (speed,duration,minimum):
        if type(n) not in (int,float) or not math.isfinite(n):raise core.StopBatch('INVALID_MOTION_PARAMETERS')
    if not 0<speed<=(6000 if motion=='rotary' else 500) or not 0<duration<=5 or type(fps) is not int or not 5<=fps<=120 or duration*fps>600 or type(reverse) is not bool:
        raise core.StopBatch('INVALID_MOTION_PARAMETERS','对话验证限5秒、601帧；速度单位为rpm或mm/s。')
    require_grid(duration,fps)
    expected=speed*duration*(6 if motion=='rotary' else 1)
    if not 0<=minimum<=expected:raise core.StopBatch('INVALID_MINIMUM_TRAVEL')
    return dict(motion=motion,speed=speed,duration_s=duration,output_fps=fps,reverse_direction=reverse,
                minimum_travel=minimum or expected*.95,expected_travel=expected,
                speed_unit='rpm' if motion=='rotary' else 'mm/s',travel_unit='deg' if motion=='rotary' else 'mm')


def prepare_inputs(path,task_kind='motion',motion='rotary',speed=12,duration_s=1,
                   output_fps=30,reverse_direction=False,minimum_travel=0):
    """Read-only admission shared by owner dispatch and direct task preparation.

    Validate parameters before the path, as in the original task handler. No
    lease, task record, executor, COM call or startup-gate mutation belongs here.
    The task handler repeats this check so direct calls cannot bypass admission.
    """
    if task_kind not in {'motion','concentric','gear_transmission','external_gear_pair'}:raise core.StopBatch('INVALID_TASK_KIND')
    if task_kind=='concentric' and (motion!='rotary' or speed!=12 or duration_s!=1 or output_fps!=30 or reverse_direction is not False or minimum_travel!=0):
        raise core.StopBatch('CONCENTRIC_FIXED_CARD_PARAMETERS','圆边首版固定12rpm、1秒30fps；不静默忽略其他运动参数。')
    settings=parameters(motion,speed,duration_s,output_fps,reverse_direction,minimum_travel) if task_kind in {'motion','gear_transmission','external_gear_pair'} else None
    if task_kind in {'gear_transmission','external_gear_pair'}:
        limits=prepare_limits()[task_kind]
        fps_allowed=output_fps in limits['allowed_output_fps'] if 'allowed_output_fps' in limits else limits['minimum_output_fps']<=output_fps<=limits['maximum_output_fps']
        if motion!='rotary' or speed>limits['maximum_speed_rpm'] or duration_s>limits['maximum_duration_s'] or not fps_allowed or minimum_travel!=0:
            detail=('泵模板gear_transmission限旋转、60rpm、2秒、30/60fps。' if task_kind=='gear_transmission' else
                    '普通外齿轮external_gear_pair限旋转、60rpm、2秒、整数5–120fps；时长与输出帧须对齐，plan仍须核验并确认原生精确网格。')
            raise core.StopBatch('GEAR_PARAMETERS_INVALID',detail+'minimum_travel保留默认0，验证完整目标角度。',
                {'task_kind':task_kind,'limits':limits,'requested':{'motion':motion,'speed':speed,'duration_s':duration_s,'output_fps':output_fps,'minimum_travel':minimum_travel},'cad_dispatched':False,'job_created':False})
    if task_kind in {'gear_transmission','external_gear_pair'}:
        settings.pop('minimum_travel')
        settings.update(requested_minimum_travel=minimum_travel,
                        verification_criterion='full_signed_input_waveform_and_external_ratio_not_minimum_travel',
                        signed_target_travel_deg=settings['expected_travel']*(-1 if reverse_direction else 1),
                        input_waveform_tolerance_deg=.1,external_ratio_tolerance_deg=1e-4)
    if not Path(path).is_absolute():raise core.StopBatch('INVALID_ASSEMBLY_PATH','需要装配体绝对路径，由AI定位。')
    assembly=core.no_links(Path(path))
    if not assembly.is_file() or assembly.suffix.lower()!='.sldasm':raise core.StopBatch('INVALID_ASSEMBLY_PATH')
    return assembly,settings


def validate_prepare_arguments(arguments):
    """Map schema-checked public names to the shared admission defaults."""
    fields=('task_kind','motion','speed','duration_s','output_fps','reverse_direction','minimum_travel')
    validate_gear_hints(arguments.get('task_kind','motion'),arguments.get('moving_component_hint',''),arguments.get('reference_component_hint',''))
    return prepare_inputs(arguments.get('assembly_path',''),**{k:arguments[k] for k in fields if k in arguments})

def validate_gear_hints(kind,moving,reference):
    if kind=='gear_transmission' and (moving not in {'','长轴'} or reference not in {'','泵体'}):
        raise core.StopBatch('GEAR_ROLE_SELECTION_REQUIRED','首版泵模板自动推荐长轴输入及泵体参考；其他名称不被静默忽略。')


def direction_key(row,motion):
    axis=mate_motion.unit(row['axis_global'])
    # Parallel plane normals are equivalent motor directions. Cylinder axes must also share a line.
    sign=next((1 if x>0 else -1 for x in axis if abs(x)>1e-8),1)
    canonical=[x*sign for x in axis]
    point=row['reference_point_global_m'];along=sum(x*y for x,y in zip(point,canonical))
    line=[x-along*y for x,y in zip(point,canonical)] if motion=='rotary' else []
    return tuple(round(x,7) for x in canonical+line)


def group_directions(rows,motion):
    grouped={}
    for row in rows:grouped.setdefault(direction_key(row,motion),[]).append(row)
    out=[]
    for key,items in sorted(grouped.items()):
        # Entity IDs may change between copies. For linear directions prefer
        # an actually available native face with the canonical axis sign;
        # never synthesize/flip an entity normal or silently change the axis.
        def order(row):
            a=mate_motion.unit(row['axis_global'])
            positive=next((x>0 for x in a if abs(x)>1e-8),True)
            return ((0 if positive else 1) if motion=='linear' else 0,-row.get('area_m2',0),row['entity_id'])
        items.sort(key=order)
        out.append({**items[0],'equivalent_direction_face_count':len(items),
            'grouping_scope':'same_axis_line' if motion=='rotary' else 'parallel_plane_normal_only'})
    return out


def pose_snapshot(components):
    return {c['component_id']:c['transform'][:12] for c in components}


def require_same_poses(expected,actual,stage):
    if expected.keys()!=actual.keys():raise core.StopBatch('INITIAL_POSE_COMPONENT_SCOPE_CHANGED',stage)
    translation=rotation=0
    for key,a in expected.items():
        b=actual[key]
        if len(a)!=12 or len(b)!=12 or any(not math.isfinite(x) for x in a+b):raise core.StopBatch('INVALID_INITIAL_POSE')
        translation=max(translation,math.sqrt(sum((a[i]-b[i])**2 for i in range(9,12))))
        rotation=max(rotation,math.acos(max(-1,min(1,(sum(a[i]*b[i] for i in range(9))-1)/2))))
    proof={'stage':stage,'components':len(expected),'maximum_translation_m':translation,'maximum_rotation_rad':rotation,
        'translation_tolerance_m':1e-7,'rotation_tolerance_rad':1e-6,'passed':translation<=1e-7 and rotation<=1e-6}
    if not proof['passed']:raise core.StopBatch('INITIAL_POSE_MISMATCH','机械起点发生变化；已保留诊断，不从漂移初态继续。',proof)
    return proof


def frame_zero(path):
    import csv
    result={}
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            if int(row['frame'])!=0:continue
            if abs(float(row['time_s']))>1e-7 or row['component_id'] in result:raise core.StopBatch('INITIAL_FRAME_INVALID')
            result[row['component_id']]=[float(row['r'+str(i)+str(j)]) for i in range(3) for j in range(3)]+[float(row[k]) for k in ('x_m','y_m','z_m')]
    return result


class MotionSession(ConversationSession):
    task_kind='concentric'
    def rescan(self,hint=''):
        if self.task_kind=='external_gear_pair':
            from .external_gear_task import discover
            return discover(self)
        if self.task_kind=='gear_transmission':
            from .gear_transmission import discover
            return discover(self)
        if self.task_kind!='motion':return super().rescan(hint)
        inspection=self.call('inspect_model',model_id=self.model,detail_level='full')
        if self.initial_inspection is None:self.initial_inspection=inspection
        self.motion_inspection=inspection
        components=inspection['components']
        moving=matching_components(components,self.moving_hint,False)
        reference_filter=None if self.reference_hint else True
        references=matching_components(components,self.reference_hint,reference_filter)
        for values,text,fixed in [(moving,self.moving_hint,False),(references,self.reference_hint,reference_filter)]:
            if text and len(values)!=1:
                raise core.StopBatch('COMPONENT_NAME_AMBIGUOUS','请用名称、用途或实例后缀澄清。',
                    {'choices':mechanical_choices(components,text,fixed) or mechanical_choices(components,'',fixed),
                     'field':'reference_component_hint' if fixed else 'moving_component_hint'})
        if not references:raise core.StopBatch('REFERENCE_COMPONENT_SELECTION_REQUIRED','未找到唯一参考件，请按机械用途说明；不自动固定零件。',
            {'choices':mechanical_choices(components,'',None)})
        if len(moving)>20:raise core.StopBatch('MOVING_SCOPE_TOO_BROAD','浮动件超过20个，请以名称或用途缩小目标。')
        if len(references)>1:
            raise core.StopBatch('COMPONENT_NAME_AMBIGUOUS','存在多个固定参考件，请按机械用途说明参考件。',
                {'choices':mechanical_choices(components,'',True),'field':'reference_component_hint'})
        rows=[];kind='cylindrical_axis' if self.motion_parameters['motion']=='rotary' else 'planar_normal'
        for component in moving:
            if component['component_id']==references[0]['component_id']:continue
            faces=mate_motion.component_geometry(self,component['component_id'],kind)
            for face in group_directions(faces,self.motion_parameters['motion']):
                rows.append({'drive':face,'reference':references[0],
                    'component_name':component['instance'],'reference_name':references[0]['instance'],
                    'axis_global':face['axis_global'],'axis_point_global_m':face['reference_point_global_m'],
                    'reason':'已核对浮动目标、参考件及原生几何；参考件未固定不代表不能相对测量，方向分组不证明机构运动相容。'})
        if not rows:raise core.StopBatch('NO_MOTION_DRIVE_CANDIDATE','未找到受支持的原生驱动面；不自动解除固定或补配合。')
        if self.motion_parameters['motion']=='linear':
            from .axis_guidance import annotate_linear_axes
            annotate_linear_axes(rows,inspection.get('mates',[]))
        self.motion_candidates=rows
        self.motion_signature=self.call('_circular_reference_state',model_id=self.model)['signature']
        return {'motion_candidates':rows,'geometry_complete':True,
            'scope':'floating_targets_with_explicit_reference_or_unique_fixed_reference',
            'studies':self.call('list_motion_studies',model_id=self.model)}


class MotionTaskEngine(TaskEngine):
    def __init__(self,project,work,runtime_base,session_factory=MotionSession):
        super().__init__(project,work,runtime_base,session_factory)

    def prepare(self,path,moving='',reference='',task_kind='motion',motion='rotary',speed=12,
                duration_s=1,output_fps=30,reverse_direction=False,minimum_travel=0):
        assembly,settings=prepare_inputs(path,task_kind,motion,speed,duration_s,output_fps,reverse_direction,minimum_travel)
        validate_gear_hints(task_kind,moving,reference)
        with self.lock:
            if self.prior_unfinished:raise core.StopBatch('PRIOR_TASK_UNCONFIRMED',diagnostics=self.prior_task_diagnostics())
            if self.active:raise core.StopBatch('TASK_SESSION_ACTIVE',diagnostics={'task_id':self.active})
            # Refuse contention before creating an active task that cannot own a CAD session.
            startup_gate.require_idle(self.work/'startup-check')
            tid=uuid.uuid4().hex;folder=self.work/('task-'+tid);folder.mkdir()
            t=dict(task_id=tid,directory=str(folder),source=str(assembly),**source_integrity.snapshot_record(assembly),
                task_kind=task_kind,motion_parameters=settings,moving_component_hint=moving,reference_component_hint=reference,
                phase='created',busy=False,closed=False,confirmation_required=True,automatic_write_retry=False,
                server_pid=__import__('os').getpid(),server_instance_id=self.server_instance_id)
            self.tasks[tid]=t;self.active=tid
        def operation():
            def stage(status,message):
                task_progress.observe_stage(self,t,status,message)
            s=self.session_factory(self.project,folder/'session',self.runtime_base,moving=moving,reference=reference,on_stage=stage,
                on_progress=lambda value:task_progress.observe_call(self,t,value))
            s.task_kind=task_kind;s.motion_parameters=settings;self.sessions[tid]=s
            self._proposals(t,s.discover(assembly))
        return self._submit(t,'preparing',operation)

    def _proposals(self,t,value):
        if t.get('task_kind')=='external_gear_pair':
            from .external_gears import public_card
            source_integrity.bind(t,self.sessions[t['task_id']]);suggestion=value['external_gear_pair']
            t.update(model_id=self.sessions[t['task_id']].model,phase='scope_review_required' if suggestion.get('requires_stationary_scope_review') else 'proposal_ready',**{**suggestion,'proposals':[public_card(p) for p in suggestion['proposals']]},
                next_action={'tool':'plan_mechanism_task','arguments':{'task_id':t['task_id']},
                    'instruction':'AI解释两轴、齿轮、键和固定支承推荐及比例依据；唯一方案自动采用推荐。只在角色或比例无法确定时用自然语言澄清，不让用户填写实体ID。'})
            if suggestion.get('requires_stationary_scope_review'):
                t['next_action']['instruction']='优先复用assembly_group_recommendation.assembly_intent_draft，向用户集中解释并澄清mechanical_questions；不要让用户逐个填组件名称或ID。草稿和局部约束路径不是机械意图或刚性证明，只有当前对话已明确的目标可直接用于填清单；未知归属须澄清，不能把剩余件全归静止。AI依据完整stationary/input/output三组互斥清单填写plan_mechanism_task的assembly_intent，只读生成最小补配合方案，取得当前具体方案确认后执行。initial_state=saved在确认后仅在副本移除非零历史算例并采用保存姿态建立新运动，不调用公共checkpoint/reset，也不证明历史零时刻。stationary_component_hints仅用于明确授权的固定简化，不等同于补配合。'
            if len(suggestion['proposals'])==1:t['next_action']['arguments']['candidate_id']=suggestion['proposals'][0]['candidate_id']
            return
        if t.get('task_kind')=='gear_transmission':
            source_integrity.bind(t,self.sessions[t['task_id']]);proposal=value['gear_transmission']
            t.update(model_id=self.sessions[t['task_id']].model,phase='proposal_ready',proposals=[{'candidate_id':'candidate-1',**proposal}],
                requires_selection=False,next_action={'tool':'plan_mechanism_task','arguments':{'task_id':t['task_id'],'candidate_id':'candidate-1'},
                    'instruction':'解释完整泵两侧推荐角色和反向1∶1比例；准备明确的解除固定、刚性连接、轴定位及齿轮方案，用户确认前不改写。'})
            return
        if t.get('task_kind')!='motion':return super()._proposals(t,value)
        source_integrity.bind(t,self.sessions[t['task_id']])
        rows=value['motion_candidates'];s=self.sessions[t['task_id']]
        t.update(model_id=s.model,phase='proposal_ready',proposals=[{'candidate_id':'candidate-'+str(i+1),
            **{k:r[k] for k in ['component_name','reference_name','axis_global','axis_point_global_m','reason']},
            **{k:r[k] for k in ('axis_evidence','recommended_from_native_mate_axis') if k in r}}
            for i,r in enumerate(rows)],requires_selection=len(rows)!=1,scope_geometry_complete=True,
            geometry_scope=value['scope'],studies=value['studies'],
            next_action={'tool':'plan_mechanism_task','arguments':{'task_id':t['task_id']},
                'instruction':'解释推荐的组件、参考及方向；存在不同轴线时按机械用途澄清。'})
        preferred=[p for p in t['proposals'] if p.get('recommended_from_native_mate_axis')]
        t['suggested_candidate_id']=preferred[0]['candidate_id'] if len(preferred)==1 else None
        t['recommendation_scope']='native_joint_axis_hint_not_proven_allowed_motion_or_design_intent'
        if t['suggested_candidate_id']:
            t['next_action']['arguments']['candidate_id']=t['suggested_candidate_id']
            t['next_action']['instruction']='AI优先解释与原生同轴配合轴线一致的候选及其证据；该线索不等于自由度证明，不覆盖用户明确指定方向。确认具体试算方案后才execute。'
        t.pop('component_selection',None)

    def plan(self,task_id,candidate_id='',moving_component_hint='',reference_component_hint='',initial_state='saved',alignment_mode='strict',
             gear_ratio_numerator=0,gear_ratio_denominator=0,input_shaft_hint='',output_shaft_hint='',input_gear_hint='',output_gear_hint='',stationary_component_hints=None,assembly_intent=None):
        t=self.tasks[task_id]
        if t.get('task_kind')=='external_gear_pair':
            from .external_gear_task import propose
            return propose(self,t,candidate_id,initial_state,alignment_mode,moving_component_hint,reference_component_hint,
                           gear_ratio_numerator,gear_ratio_denominator,{'input_shaft':input_shaft_hint,'output_shaft':output_shaft_hint,'input_gear':input_gear_hint,'output_gear':output_gear_hint},stationary_component_hints,assembly_intent)
        if assembly_intent is not None or stationary_component_hints or gear_ratio_numerator or gear_ratio_denominator or input_shaft_hint or output_shaft_hint or input_gear_hint or output_gear_hint:
            raise core.StopBatch('EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE','两轴比例或角色补充参数只用于external_gear_pair，不静默忽略。')
        if t.get('task_kind')=='gear_transmission':
            from .gear_transmission import propose
            return propose(self,t,candidate_id,initial_state,alignment_mode,moving_component_hint,reference_component_hint)
        if t.get('task_kind')!='motion' or t['phase']=='awaiting_component_selection':
            if initial_state!='saved':raise core.StopBatch('INITIAL_STATE_SELECTION_NOT_READY')
            return super().plan(task_id,candidate_id,moving_component_hint,reference_component_hint,alignment_mode)
        if alignment_mode!='strict':raise core.StopBatch('INVALID_ALIGNMENT_MODE')
        self._require_session(task_id)
        if t['phase']!='proposal_ready':raise core.StopBatch('TASK_NOT_READY_FOR_PLAN')
        if moving_component_hint or reference_component_hint:raise core.StopBatch('COMPONENT_SELECTION_NOT_REQUESTED')
        if not candidate_id:
            if len(t['proposals'])!=1:return {'task_id':task_id,'needs_selection':True,'proposals':t['proposals'],
                'question':'希望沿哪条轴线运动？AI可按轴线方向和零件用途解释候选。'}
            candidate_id=t['proposals'][0]['candidate_id']
        found=[i for i,r in enumerate(t['proposals']) if r['candidate_id']==candidate_id]
        if len(found)!=1:raise core.StopBatch('INVALID_TASK_CANDIDATE')
        if initial_state not in {'saved','study_zero'}:raise core.StopBatch('INVALID_INITIAL_STATE')
        studies=t['studies']
        if isinstance(studies,dict):studies=studies.get('studies',[])
        nonzero=[r for r in studies if abs(r.get('time_s',r.get('current_time_s',0)))>1e-8 and (initial_state=='study_zero' or r.get('active') is True)]
        if nonzero and initial_state=='saved':
            return {'task_id':task_id,'needs_initial_state_selection':True,'nonzero_studies':nonzero,
                'question':'保存的算例停在非零时间。是否允许仅在副本重算并回到算例零时刻，再从该机械初态试算？结束仍恢复导入时状态。',
                'next_action':{'tool':'plan_mechanism_task','arguments':{'task_id':task_id,'candidate_id':candidate_id,'initial_state':'study_zero'}}}
        def operation():
            s=self.sessions[task_id]
            if s.call('_circular_reference_state',model_id=s.model)['signature']!=s.motion_signature:
                raise core.StopBatch('MOTION_PROPOSAL_STALE')
            t.update(phase='awaiting_confirmation',selected_index=found[0],plan_token=uuid.uuid4().hex,
                proposal={**t['proposals'][found[0]],**t['motion_parameters'],
                    'initial_state':initial_state,'reset_studies_before_drive':[r['name'] for r in nonzero] if initial_state=='study_zero' else [],
                    'scope':'selected_motion_only_not_all_DOF','finish_policy':'restore_import_checkpoint_then_close_owned_CAD',
                    'original_files_modified':False},
                next_action={'tool':'execute_mechanism_task','arguments':{'task_id':task_id},
                    'instruction':'解释组件、参考、带符号轴线、反向开关、速度和行程；用户授权后只执行一次。'})
        return self._submit(t,'planning',operation)

    def execute(self,task_id,plan_token,confirmed=False,scope_confirmed=False,alignment_confirmed=False):
        t=self.tasks[task_id]
        if t.get('task_kind')=='external_gear_pair':
            from .external_gear_task import execute
            return execute(self,t,plan_token,confirmed,scope_confirmed,alignment_confirmed)
        if t.get('task_kind')=='gear_transmission':
            from .gear_transmission import execute
            return execute(self,t,plan_token,confirmed,scope_confirmed,alignment_confirmed)
        if t.get('task_kind')!='motion':return super().execute(task_id,plan_token,confirmed,scope_confirmed,alignment_confirmed)
        if alignment_confirmed is not False:raise core.StopBatch('INVALID_ALIGNMENT_MODE')
        self._require_session(task_id)
        if confirmed is not True or scope_confirmed is not True:raise core.StopBatch('CONFIRMATION_REQUIRED')
        task_execution.require_plan_token(t,plan_token)
        t['execution_consumed']=True;t['confirmation']={'confirmed':True,'scope_confirmed':True,'at':time.time()};self.save(t)
        def operation():
            s=self.sessions[task_id];p=t['motion_parameters'];r=s.motion_candidates[t['selected_index']]
            if s.call('_circular_reference_state',model_id=s.model)['signature']!=s.motion_signature:
                raise core.StopBatch('MOTION_PROPOSAL_STALE')
            study='Dialogue_'+uuid.uuid4().hex[:10];drive=r['drive'];ref=r['reference']
            for name in t['proposal']['reset_studies_before_drive']:
                reset=s.call('reset_study_time',model_id=s.model,study=name,allow_recalculate=True)
                core.write(s.folder/('归零-'+hashlib.sha256(name.encode()).hexdigest()[:10]+'.json'),reset)
            if t['proposal']['reset_studies_before_drive']:
                refreshed=mate_motion.component_geometry(s,drive['component_id'],drive['kind'])
                matches=[f for f in refreshed if f['entity_id']==drive['entity_id']]
                if len(matches)!=1 or direction_key(matches[0],p['motion'])!=direction_key(drive,p['motion']):
                    raise core.StopBatch('MOTION_AXIS_CHANGED_AFTER_RESET','归零后原轴线改变，未创建驱动；先恢复并按正确初态重新规划。')
                drive=matches[0]
            initial=pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components'])
            gates=[]
            if t['proposal']['initial_state']=='saved':
                gates.append(require_same_poses(pose_snapshot(s.initial_inspection['components']),initial,'before_create_saved_import_pose'))
            core.write(s.folder/'机械起点门禁.json',gates)
            s.state('creating_drive','正在副本创建已确认的驱动，并核对创建前后机械起点…')
            created=s.call('create_motion_study',model_id=s.model,study=study,component_id=drive['component_id'],
                entity_id=drive['entity_id'],motor_type=p['motion'],speed=p['speed'],reverse_direction=p['reverse_direction'],
                reference_component_id=ref['component_id'],duration_s=p['duration_s'],output_fps=p['output_fps'])
            core.write(s.folder/'驱动创建.json',created)
            gates.append(require_same_poses(initial,pose_snapshot(s.call('inspect_model',model_id=s.model,detail_level='components')['components']),'after_create'))
            core.write(s.folder/'机械起点门禁.json',gates)
            s.state('solving','正在求解并核对实际时间轴、运动方向和全组件首帧…')
            run=s.call('verify_motion_preservation',model_id=s.model,study=study,component_id=drive['component_id'],
                entity_id=drive['entity_id'],expected_motion=p['motion'],minimum_travel=p['minimum_travel'],
                duration_s=p['duration_s'],output_fps=p['output_fps'],reference_component_id=ref['component_id'],run_id=uuid.uuid4().hex,plan_id='')
            core.write(s.folder/'运动验证.json',run)
            native_ok=run.get('assertion')=='pass' and run.get('restoration_status')=='restored' and run.get('source_files_unchanged') is True and not run.get('error_code')
            t['verification']={'declared_scope_passed':False,'run_id':run.get('run_id'),'native_assertion':run.get('assertion'),
                'native_error_code':run.get('error_code'),'native_restoration_status':run.get('restoration_status'),
                'report_path':run.get('report_path'),'scope':'selected_motion_only_not_all_DOF',
                'curve_status':'not_exported_native_verification_not_passed','whole_mechanism_or_DOF_certified':False}
            if not native_ok:
                if run.get('error_code'):
                    raise core.StopBatch(run['error_code'],run.get('failure') or '原生运动验证未完成；读取已保存诊断并恢复收尾，不重复求解。',
                        {'run_id':run.get('run_id'),'report_path':run.get('report_path'),
                         'native_verification':run,'task_verification_path':str(s.folder/'运动验证.json')})
                t.update(phase='verification_failed',next_action={'tool':'finish_mechanism_task','arguments':{'task_id':task_id},
                    'instruction':'原生判据、恢复或源文件核对未全部通过；读取运动验证记录后安全收尾，不导出为成功曲线，不自动重算。'})
                return
            poses=s.runtime/'runs'/run['run_id']/'component-poses.csv'
            if not poses.is_file():
                raise core.StopBatch('MOTION_POSE_EVIDENCE_UNAVAILABLE','原生返回成功，但没有可核对的姿态文件；未导出曲线或宣告运动通过。',
                    {'run_id':run['run_id'],'pose_path':str(poses),'report_path':run.get('report_path')})
            gates.append(require_same_poses(initial,frame_zero(poses),'actual_solved_frame_zero'))
            core.write(s.folder/'机械起点门禁.json',gates)
            from sw_mcp.artifacts import Artifacts
            artifacts=Artifacts(s.runtime)
            quantity='angular_velocity' if p['motion']=='rotary' else 'displacement'
            curve=artifacts.export_history_curve(run['run_id'],drive['component_id'],quantity,'magnitude',True)
            core.write(s.folder/'运动曲线.json',curve)
            signed=run.get('signed_net_travel')
            expected_sign=-1 if p['reverse_direction'] else 1
            direction_pass=type(signed) in (int,float) and math.isfinite(signed) and signed*expected_sign>0
            passed=run.get('assertion')=='pass' and run.get('restoration_status')=='restored' and run.get('source_files_unchanged') is True and direction_pass
            t.update(phase='verified' if passed else 'verification_failed',verification={'declared_scope_passed':passed,
                'run_id':run['run_id'],'native_assertion':run.get('assertion'),'scope':'selected_motion_only_not_all_DOF',
                'signed_net_travel':signed,'direction_verified_about_selected_native_axis':direction_pass,
                'direction_scope':'native_axis_and_reverse_switch_not_unstated_designer_intent',
                'curve':curve,'curve_scope':'global_component_origin_magnitude_not_signed_relative_travel',
                'curve_status':'exported_validated_native_run',
                'screenshot_status':'not_requested_no_extra_solve','whole_mechanism_or_DOF_certified':False},
                next_action={'tool':'finish_mechanism_task','arguments':{'task_id':task_id},
                    'instruction':'报告原生验证与曲线；恢复初始检查点并核对退出后再开始下一轮。'})
        return self._submit(t,'running',operation)

    def finish(self,task_id,close_unrestored=False,keep_result=False):
        if keep_result and close_unrestored:raise core.StopBatch('INCOMPATIBLE_FINISH_CHOICES')
        if not keep_result:return super().finish(task_id,close_unrestored)
        t=self.tasks[task_id]
        if t.get('closed'):return {'task_id':task_id,'closed':True,'result':t['finish'],'replayed':False}
        self._require_session(task_id)
        if t['phase']!='verified' or t.get('verification',{}).get('declared_scope_passed') is not True:
            raise core.StopBatch('KEEP_REQUIRES_VERIFIED_RESULT','只允许明确保留本次已验证成果；失败或未知状态不能保留为成功。')
        def operation():
            s=self.sessions[task_id]
            restored_result=None
            if t.get('task_kind') in {'concentric','gear_transmission','external_gear_pair'}:
                if not getattr(s,'result_checkpoint',None):raise core.StopBatch('RESULT_CHECKPOINT_UNAVAILABLE')
                restored_result=s.call('restore_model_checkpoint',model_id=s.model,checkpoint_id=s.result_checkpoint)
                if not core.restored_ok(restored_result):s.unknown=True;raise core.StopBatch('RESULT_RESTORE_NOT_VERIFIED')
                current=s.call('inspect_model',model_id=s.model,detail_level='full')
                proof=require_same_poses(pose_snapshot(s.result_inspection['components']),pose_snapshot(current['components']),'kept_applied_result')
                if len(current.get('mates',[]))!=len(s.result_inspection.get('mates',[])):
                    raise core.StopBatch('KEPT_MATE_STATE_MISMATCH')
                core.write(s.folder/'保留成果核对.json',proof)
            imported=core.read(s.folder/'导入.json')
            result_path=core.no_links(Path(imported['path']))
            result_path.relative_to(s.runtime.resolve())
            s.committed=True;s.import_restored=False
            t['finish']={'restoration':None,'restoration_status':'not_requested_result_preserved',
                'result_checkpoint_restore':restored_result,'cleanup_status':'pending','next_round_allowed':False};self.save(t)
            receipt=s.close()
            t['finish']['session']=receipt;self.save(t)
            native=core.read(s.folder/'exit.json');executor=core.read(s.folder/'执行器收尾.json')
            t['finish'].update(native_exit=native,executor_exit=executor);self.save(t)
            if executor.get('confirmed') is not True or not native.get('native_process_exited'):raise core.StopBatch('TASK_FINISH_UNCONFIRMED')
            integrity=self._source_review(t,s)
            self._settle_closed(t,{'restoration':None,'restoration_status':'not_requested_result_preserved',
                'result_checkpoint_restore':restored_result,'session':receipt,'native_exit':native,'executor_exit':executor,
                'cleanup_status':'pass' if native.get('normal_zero_exit') is True else 'warning_nonzero_native_exit',
                'result_assembly_path':str(result_path),
                'result_assembly_sha256':core.digest(result_path),'includes_test_motion_study':True,
                'result_scope':'verified_declared_motion_or_concentric_scope_not_whole_mechanism_or_DOF'},integrity)
        return self._submit(t,'keeping_result',operation)
