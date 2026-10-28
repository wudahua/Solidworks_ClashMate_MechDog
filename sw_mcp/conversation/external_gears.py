"""Evidence-based two-axis recommendations; never equate a hole diameter to pitch."""
import itertools,math,re
from . import core,geometry_audit as g,component_constraints
from .. import assembly_constraints

SCOPE='two_parallel_axis_external_gear_pair_prescribed_ratio_not_contact'

def number(value):
    try:
        x=float(str(value).strip())
        return x if math.isfinite(x) and x>0 else None
    except (TypeError,ValueError):return None

def design_teeth(design):
    """Explicit, unambiguous document parameters outrank pattern suggestions."""
    names={'齿数','齒數','teeth','toothcount','numberofteeth','numberofgear teeth','z','clashmatetrialteeth'}
    found=[]
    for p in design.get('properties',[]):
        if re.sub(r'[ _-]','',p['name'].casefold()) not in {re.sub(r'[ _-]','',n) for n in names}:continue
        n=number(p.get('resolved') if p.get('was_resolved') else p.get('raw'))
        if n and n.is_integer() and 6<=n<=1000:found.append({'teeth':int(n),'source':'declared_trial_ratio_weight' if p['name'].casefold()=='clashmatetrialteeth' else 'explicit_design_property','property':p['name'],'scope':p['scope']})
    # Configuration property overrides the same document-level parameter, but
    # two contradictory names in that effective scope cannot be silently ranked.
    active=[p for p in found if p['scope']] or found
    if len({p['teeth'] for p in active})>1:return {'status':'conflicting','evidence':active}
    if active:return {'status':'explicit_trial' if any(p['source']=='declared_trial_ratio_weight' for p in active) else 'explicit','teeth':active[0]['teeth'],'evidence':active}
    patterns=[p for p in design.get('patterns',[]) if p.get('equal_spacing') and 6<=p.get('total_instances',0)<=1000
              and abs(p.get('spacing_rad',0)-2*math.pi)<1e-6]
    counts={p['total_instances'] for p in patterns}
    if len(counts)==1:return {'status':'suggested_pattern_count_not_proven_teeth','teeth':next(iter(counts)),'evidence':patterns}
    return {'status':'not_available','evidence':patterns}

def axis_groups(component):
    rows=[]
    for face in component.get('cylinders',[]):
        axis=g.unit(face['axis_global']);point=face['reference_point_global_m']
        group=next((r for r in rows if abs(g.dot(r['axis'],axis))>1-1e-8 and radial(point,r['point'],axis)<1e-5),None)
        if group is None:
            group={'axis':axis,'point':point,'faces':[],'area':0};rows.append(group)
        group['faces'].append(face);group['area']+=face['area_m2']
    return sorted(rows,key=lambda r:r['area'],reverse=True)

def radial(point,anchor,axis):
    d=g.sub(point,anchor);return g.norm(g.sub(d,[g.dot(d,axis)*v for v in axis]))

def center(c):return [(c['box'][i]+c['box'][i+3])/2 for i in range(3)]

def extent(c,axis):return sum(abs(v)*(c['box'][i+3]-c['box'][i]) for i,v in enumerate(axis))

def matches_axis(c,axis,point):
    found=[r for r in axis_groups(c) if abs(g.dot(r['axis'],axis))>1-1e-8 and radial(r['point'],point,axis)<=1e-5]
    return found[0] if found else None

def ratio_recommendation(a,b,design,mates,groups=None):
    ids=[a['component_id'],b['component_id']]
    existing=[]
    for m in mates:
        if m.get('suppressed') or m.get('type')!=10 or not m.get('gear_ratio'):continue
        members=[r.get('component_id') for r in m.get('entities',[])]
        direct=len(members)==2 and set(members)==set(ids)
        forward=len(members)==2 and groups and members[0] in groups['input'] and members[1] in groups['output']
        backward=len(members)==2 and groups and members[1] in groups['input'] and members[0] in groups['output']
        if not (direct or forward or backward):continue
        n=number(m['gear_ratio'].get('numerator'));d=number(m['gear_ratio'].get('denominator'))
        if n and d:
            normal=members==ids or bool(forward)
            existing.append({'numerator':n if normal else d,'denominator':d if normal else n,
                             'source':'existing_native_gear_mate','native_feature_id':m['native_feature_id']})
    if existing:
        if max(p['numerator']/p['denominator'] for p in existing)-min(p['numerator']/p['denominator'] for p in existing)>1e-9:
            raise core.StopBatch('EXTERNAL_GEAR_RATIO_AMBIGUOUS','既有齿轮配合的比例不一致。',{'evidence':existing})
        return {**existing[0],'confidence':'existing_native_definition','recommendation_requires_confirmation':True}
    first,second=(design_teeth(design[c['design_key']]) for c in (a,b))
    if 'conflicting' in {first['status'],second['status']}:
        raise core.StopBatch('EXTERNAL_GEAR_RATIO_AMBIGUOUS','齿数设计属性相互矛盾，AI不能静默选取。',{'input':first,'output':second})
    if 'teeth' in first and 'teeth' in second:
        trial=first['status'] in {'explicit','explicit_trial'} and second['status'] in {'explicit','explicit_trial'} and 'explicit_trial' in {first['status'],second['status']}
        return {'numerator':first['teeth'],'denominator':second['teeth'],
                'source':'design_tooth_counts' if first['status']==second['status']=='explicit' else 'declared_trial_ratio_weights_not_tooth_measurement' if trial else 'circular_pattern_trial_suggestion_not_proven_tooth_counts',
                'confidence':'explicit_design_parameters' if first['status']==second['status']=='explicit' else 'declared_trial_parameters' if trial else 'mechanical_review_required',
                'evidence':{'input':first,'output':second},'recommendation_requires_confirmation':True}
    if a['design_key']==b['design_key']:
        return {'numerator':1,'denominator':1,'source':'same_part_and_configuration','confidence':'identical_gear_part_hypothesis',
                'recommendation_requires_confirmation':True}
    return {'numerator':None,'denominator':None,'source':'insufficient_design_evidence','confidence':'unknown',
            'recommendation_requires_confirmation':True,
            'question':'模型未提供可区分的齿数或比例依据。两个齿轮的齿数或希望采用的运动试算传动比是多少？',
            'hole_and_outside_diameters_used_as_pitch_diameters':False}

def recommend(survey,moving_hint='',reference_hint='',role_hints=None,stationary_hints=None,intent_groups=None):
    if not survey.get('inventory_complete'):raise core.StopBatch('EXTERNAL_GEAR_SCOPE_UNSUPPORTED','顶层组件未完整解析。',{'skipped':survey.get('skipped')})
    role_hints=role_hints or {}
    stationary_hints=[] if stationary_hints is None else stationary_hints
    if not isinstance(stationary_hints,list) or len(stationary_hints)>128 or any(not isinstance(v,str) or not v.strip() or len(v)>256 for v in stationary_hints):raise core.StopBatch("EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE","静止侧声明须为明确组件名称列表。")
    components=survey['components'];design=survey['design_evidence'];gears=[]
    for c in components:
        if not c.get('source_configuration_matches') or not c.get('box'):continue
        name=c['instance'].casefold();teeth=design_teeth(design[c['design_key']]);axes=axis_groups(c)
        if any(w in name for w in ('内齿','internal','worm','蜗','bevel','锥齿')):continue
        hinted=any(text and text.casefold() in name for key,text in role_hints.items() if key.endswith('gear'))
        if axes and (hinted or teeth['status'] in {'explicit','explicit_trial','conflicting'} or any(w in name for w in ('gear','齿轮','齒輪'))):gears.append((c,axes[0],teeth))
    proposals=[];issues=[]
    for left,right in itertools.combinations(gears,2):
        a,aa,at=left;b,ba,bt=right
        if abs(g.dot(aa['axis'],ba['axis']))<1-1e-8 or radial(aa['point'],ba['point'],aa['axis'])<1e-4:continue
        # A conventional reduction input is a recommendation, never design intent.
        if (at.get('teeth',float('inf')),not ('长轴' in a['instance']))>(bt.get('teeth',float('inf')),not ('长轴' in b['instance'])):a,b,aa,ba=b,a,ba,aa
        if moving_hint:
            left_match=moving_hint.casefold() in a['instance'].casefold();right_match=moving_hint.casefold() in b['instance'].casefold()
            if right_match and not left_match:a,b,aa,ba=b,a,ba,aa
        if role_hints.get('input_gear') and role_hints['input_gear'].casefold() in b['instance'].casefold():a,b,aa,ba=b,a,ba,aa
        if any(text and text.casefold() not in component['instance'].casefold() for key,component in [('input_gear',a),('output_gear',b)] if (text:=role_hints.get(key))):continue
        if intent_groups and b['component_id'] in intent_groups['input'] and a['component_id'] in intent_groups['output']:a,b,aa,ba=b,a,ba,aa
        try:proposal=pair_recommendation(survey,a,b,aa,ba,reference_hint,moving_hint,role_hints,stationary_hints,intent_groups)
        except core.StopBatch as error:
            issues.append({'input':a['instance'],'output':b['instance'],'code':error.code,'message':str(error),'diagnostics':error.diagnostics});continue
        proposal.update(candidate_id='candidate-'+str(len(proposals)+1),input_selection_reason='建议较小齿数侧或已有长轴作为输入；这是推荐，具体方案确认后执行')
        proposals.append(proposal)
    if not proposals:
        if len(issues)==1 and issues[0]['code']=='EXTERNAL_GEAR_SCOPE_UNSUPPORTED':
            issue=issues[0]
            raise core.StopBatch(issue['code'],'两轴组合已识别，但静止侧约束尚未满足；重复更换名称不能解决此范围阻断。',
                {'gear_candidates':[c['instance'] for c,a,t in gears],'pair_issues':issues,
                 **issue['diagnostics'],'name_clarification_can_resolve':False,'write_dispatched':False})
        raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','未找到唯一可用的两轴齿轮方案；AI应依据已有诊断澄清机械用途，不让用户填写实体ID。',
                             {'gear_candidates':[c['instance'] for c,a,t in gears],'pair_issues':issues})
    return {'proposals':proposals,'requires_selection':len(proposals)!=1,'issues':issues,
            'scope':SCOPE,'automatic_selection':'unique_evidence_supported_pair_only','write_dispatched':False}

def pair_recommendation(survey,a,b,aa,ba,reference_hint,moving_hint,role_hints=None,stationary_hints=None,intent_groups=None):
    role_hints=role_hints or {}
    stationary=[]
    for hint in stationary_hints or []:
        matches=[c for c in survey['components'] if c['instance'].casefold()==hint.casefold()]
        if len(matches)!=1:raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','静止侧名称无法唯一匹配，未模糊替换。',{'hint':hint})
        if matches[0]['component_id'] not in stationary:stationary.append(matches[0]['component_id'])
    components=survey['components'];gears={a['component_id'],b['component_id']};groups={};axes={};supports={};reasons={};shaft_ids={}
    for side,gear,axis in [('input',a,aa),('output',b,ba)]:
        candidates=[]
        for c in components:
            shape=matches_axis(c,axis['axis'],axis['point'])
            if not shape or not c.get('box'):continue
            name=c['instance'].casefold()
            if role_hints.get(side+'_shaft') and role_hints[side+'_shaft'].casefold() not in name:continue
            # A fixed housing can contain both axes; it is never a shaft.
            if c['component_id'] not in gears and (matches_axis(c,aa['axis'],aa['point']) and matches_axis(c,ba['axis'],ba['point'])):continue
            if any(w in name for w in ('轴承','bearing','壳','body','座','泵体','cover','盖')):continue
            if c['component_id'] in gears and c['component_id']!=gear['component_id']:continue
            radius=max(f['cylinder_radius_m'] for f in shape['faces']);length=extent(c,axis['axis'])
            named=any(w in name for w in ('轴','shaft'));slender=length>4*radius
            if not named and not slender:continue
            score=100*named+min(20,length/max(2*radius,1e-9))
            if moving_hint and moving_hint.casefold() in name:score+=200
            candidates.append((score,c,shape))
        candidates.sort(key=lambda row:row[0],reverse=True)
        if not candidates and role_hints.get(side+'_shaft'):
            raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','指定轴名称未匹配到本侧同轴候选，未改用其他零件。',{'side':side,'hint':role_hints[side+'_shaft']})
        if not candidates:candidates=[(0,gear,axis)]
        if not candidates or (len(candidates)>1 and abs(candidates[0][0]-candidates[1][0])<1):
            raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','同轴零件不能唯一推荐为轴，请按用途澄清。',{'side':side,'choices':[c['instance'] for score,c,shape in candidates]})
        _,shaft,shape=candidates[0];axes[side]=shape['faces'][0];shaft_ids[side]=shaft['component_id'];groups[side]=list(dict.fromkeys([shaft['component_id'],gear['component_id']]))
        reasons[side]={'shaft_name':shaft['instance'],'gear_name':gear['instance'],'shaft_evidence':'gear_own_axis_no_separate_shaft_found' if shaft['component_id']==gear['component_id'] else 'coaxial_native_cylinders_and_name_or_slender_shape'}
        fixed=[]
        for c in components:
            if not c['fixed_component'] and c['component_id'] not in stationary or c['component_id'] in gears or c['component_id']==shaft['component_id']:continue
            aligned=matches_axis(c,axis['axis'],axis['point'])
            if not aligned:continue
            face=min(aligned['faces'],key=lambda f:abs(f['cylinder_radius_m']-axes[side]['cylinder_radius_m']))
            score=abs(face['cylinder_radius_m']-axes[side]['cylinder_radius_m'])
            if reference_hint and reference_hint.casefold() not in c['instance'].casefold():continue
            fixed.append((score,c,face))
        fixed.sort(key=lambda row:(row[0],row[1]['instance']))
        if not fixed:
            possible=[c for c in components if not c['fixed_component'] and c['component_id'] not in gears|{shaft['component_id']}
                      and matches_axis(c,axis['axis'],axis['point']) and (not reference_hint or reference_hint.casefold() in c['instance'].casefold())]
            if possible:
                raise core.StopBatch('EXTERNAL_GEAR_SCOPE_UNSUPPORTED','存在同轴支承几何候选，但其静止归属尚未声明；未把它当作名称缺失或自动固定。',
                    {'side':side,'support_geometry_candidates':[c['instance'] for c in possible],
                     'constraint_inventory':component_constraints.inventory(components,survey['mates'],groups),
                     'stationary_preparation':{'status':'requires_explicit_mechanical_scope_declaration_then_plan_confirmation',
                        'candidates':[{'instance':c['instance'],'constraint_state':c.get('constraint_state')} for c in possible],'automatic_fix':False}})
            raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','缺少可核验的同轴支承几何参考。',{'side':side})
        _,support,face=fixed[0];supports[side]={'component_id':support['component_id'],'instance':support['instance'],'axis':face,
            'reason':'fixed_native_coaxial_reference_not_contact_validation'}
        # Keys are recommended by name + proximity. Unknown small components are
        # not silently locked into a rotor merely because they are nearby.
        for c in components:
            if c['component_id'] in gears or c['component_id']==shaft['component_id'] or not c.get('box'):continue
            if not any(word in c['instance'].casefold() for word in ('key','键','鍵')):continue
            p=center(c);own=radial(p,axis['point'],axis['axis']);other=radial(p,ba['point'] if side=='input' else aa['point'],axis['axis'])
            if own<other-1e-4 and own<max(axes[side]['cylinder_radius_m']*2,.01):groups[side].append(c['component_id'])
    if intent_groups:
        for side in ('input','output'):
            if not set(groups[side]).issubset(intent_groups[side]):raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','已声明运动组与推荐轴、齿轮或键不符。',{'side':side})
        groups={side:list(intent_groups[side]) for side in ('input','output')}
    if set(groups['input'])&set(groups['output']):raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','两个刚性组存在重叠组件。')
    moving=set(groups['input']+groups['output'])
    if moving.intersection(stationary):raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','静止侧声明与推荐转子组重叠，未固定运动件。')
    outside=[c['instance'] for c in components if not c['fixed_component'] and c['component_id'] not in moving and c['component_id'] not in stationary]
    if outside:raise core.StopBatch('EXTERNAL_GEAR_SCOPE_UNSUPPORTED','推荐轴系外存在未固定组件；浮动标志不等于存在剩余自由度，未自动固定这些零件。',
        {'unassigned_floating_components':outside,'constraint_inventory':component_constraints.inventory(components,survey['mates'],groups),
         'proposed_motion_groups':groups,
         'assembly_constraint_review':assembly_constraints.summary(assembly_constraints.analyze(components,survey['mates'],groups,inventory_complete=survey.get('inventory_complete',False),structural_relations=survey.get('structural_relations'))),
         'stationary_preparation':{'status':'requires_explicit_mechanical_scope_declaration_then_plan_confirmation','candidates':[{'instance':c['instance'],'constraint_state':c.get('constraint_state')} for c in components if c['instance'] in outside],'automatic_fix':False},
         'fixed_flag_alone_proves_free_DOF':False,'blanket_fix_recommended':False,'write_dispatched':False})
    by_id={c['component_id']:c for c in components}
    chosen=[any(moving_hint.casefold() in by_id[c]['instance'].casefold() for c in groups[side]) for side in ('input','output')] if moving_hint else None
    if chosen==[False,False]:raise core.StopBatch('EXTERNAL_GEAR_SELECTION_REQUIRED','输入名称线索未匹配到任一推荐轴系。',{'hint':moving_hint})
    proposed_ratio=ratio_recommendation(a,b,survey['design_evidence'],survey['mates'],groups)
    equal=bool(proposed_ratio.get('numerator')) and proposed_ratio.get('numerator')==proposed_ratio.get('denominator')
    swap=chosen==[False,True] if chosen is not None else (not any(role_hints.values()) and equal and by_id[shaft_ids['input']]['fixed_component'] and not by_id[shaft_ids['output']]['fixed_component'])
    if swap:
        a,b=b,a
        for data in (groups,axes,supports,reasons,shaft_ids):data['input'],data['output']=data['output'],data['input']
    reference=supports['input']['component_id']
    ratio=ratio_recommendation(a,b,survey['design_evidence'],survey['mates'],groups)
    if ratio['numerator']:ratio['expected_output_over_input']=-ratio['numerator']/ratio['denominator']
    return {'scope':SCOPE,'model_id':survey['model_id'],'reference_state_signature':survey['reference_state_signature'],
            'stationary_components':stationary,'stationary_scope':[{'component_id':c['component_id'],'instance':c['instance'],'currently_fixed':c['fixed_component']} for c in components if c['component_id'] in stationary],
            'roles':{'input_shaft':shaft_ids['input'],'input_gear':a['component_id'],'output_shaft':shaft_ids['output'],
                     'output_gear':b['component_id'],'body':reference},'groups':groups,'shaft_axes':axes,'supports':supports,
            'gear_ratio':ratio,'recommendation_evidence':reasons,'moving_components':[
                {'component_id':c['component_id'],'instance':c['instance'],'currently_fixed':c['fixed_component']} for c in components if c['component_id'] in moving],
            'external_gear_hypothesis_requires_confirmation':True,'write_dispatched':False}


def public_card(value):
    """Keep native persistent references in owner evidence, not in every AI turn."""
    card={**{k:v for k,v in value.items() if k not in {'shaft_axes','supports','reference_state_signature','constraint_completion'}},
            'shaft_axes':{side:{k:row[k] for k in ('component_id','axis_global','reference_point_global_m','cylinder_radius_m')} for side,row in value['shaft_axes'].items()},
            'supports':{side:{k:v for k,v in row.items() if k!='axis'} for side,row in value['supports'].items()},
            'native_references':'retained_by_owner_not_required_from_user'}
    if value.get('constraint_completion'):
        p=value['constraint_completion']
        card['constraint_completion']={k:v for k,v in p.items() if k!='actions'}
        card['constraint_completion']['actions']=[{k:v for k,v in a.items() if k not in {'reference_a','reference_b','reference_kind_a','reference_kind_b'}} for a in p['actions']]
    return card
