"""Joint goals and independent supplements, separate from gear transmission.

All ranks are conditional on the supported instantaneous constraint model.
Native health, actual motion trials and restoration remain mandatory.
"""
import math
from . import assembly_constraints as ac
from .assembly_completion import SparseBasis

KINDS = {'rigid', 'revolute', 'prismatic'}


def nullspace(rows):
    b = ac.basis(rows); result = []
    for i in range(6):
        v = [float(i == j) for j in range(6)]
        for _ in range(2):
            for r in b+result:
                d = ac.dot(v, r); v = [x-d*y for x, y in zip(v, r)]
        n = math.sqrt(ac.dot(v, v))
        if n > 1e-8: result.append([x/n for x in v])
    return result


def target_rows(kind, axis, point, origin, scale):
    if kind == 'rigid': return [[float(i == j) for j in range(6)] for i in range(6)]
    a = ac.unit(axis); p = [(point[i]-origin[i])/scale for i in range(3)]
    if kind == 'revolute':
        return [[0., 0., 0.]+list(v) for v in ac.perpendiculars(a)]+[
            list(n)+ac.cross(p, n) for n in ([1.,0,0],[0,1.,0],[0,0,1.])]
    if kind == 'prismatic':
        return [[0.,0.,0.]+list(n) for n in ([1.,0,0],[0,1.,0],[0,0,1.])]+[
            list(n)+ac.cross(p, n) for n in ac.perpendiculars(a)]
    raise ValueError('unsupported_connection_kind')


def observed_rows(survey):
    origin, scale = ac._frame(survey['components']); pairs = {}; omitted = []
    ids = {c['component_id'] for c in survey['components']}
    for m in survey['mates']:
        if m.get('suppressed') is True: continue
        es = m.get('entities') or []; cs = [e.get('component_id') for e in es]
        if (m.get('suppressed') is not False or type(m.get('error')) is not int or m['error'] != 0
                or m.get('warning') or len(es) != 2 or len(set(cs)) != 2 or any(c not in ids for c in cs)):
            omitted.append(m.get('native_feature_id')); continue
        try: rows = ac._rows(m, es, origin, scale)
        except (ValueError, KeyError, TypeError): omitted.append(m.get('native_feature_id')); continue
        key = tuple(sorted(cs)); pairs.setdefault(key, {'rows': [], 'native_feature_ids': []})
        pairs[key]['rows'].extend(rows); pairs[key]['native_feature_ids'].append(m['native_feature_id'])
    return pairs, omitted, origin, scale


def mobility(rows, origin, scale):
    free = nullspace(rows)
    r = {'supported_local_rank': 6-len(free), 'local_free_coordinates': len(free),
         'recommended_joint_type': None, 'global_DOF': None, 'motion_verified': False}
    if not free: return {**r, 'recommended_joint_type': 'rigid'}
    if len(free) != 1: return r
    v, w = free[0][:3], free[0][3:]; wn = math.sqrt(ac.dot(w,w)); vn = math.sqrt(ac.dot(v,v))
    if wn < 1e-8 and vn > 1e-8:
        return {**r, 'recommended_joint_type': 'prismatic', 'axis_global': ac.unit(v), 'axis_point_global_m': origin}
    if wn > 1e-8 and abs(ac.dot(v,w))/wn < 1e-8:
        p = [x/(wn*wn) for x in ac.cross(w,v)]
        return {**r, 'recommended_joint_type': 'revolute', 'axis_global': ac.unit(w),
                'axis_point_global_m': [origin[i]+scale*p[i] for i in range(3)]}
    return {**r, 'reason': 'single_screw_like_motion_not_supported_as_basic_joint'}


def review(survey):
    cs = survey['components']; ids = {c['component_id']: c for c in cs}
    if not survey.get('inventory_complete') or not 1 <= len(cs) <= 128 or len(ids) != len(cs):
        return {'status': 'incomplete_inventory', 'complete': False, 'write_dispatched': False}
    pairs, omitted, origin, scale = observed_rows(survey)
    analysis = ac.analyze(cs, survey['mates'], structural_relations=survey.get('structural_relations'))
    rows = []
    for (a,b), p in sorted(pairs.items()):
        rows.append({'component_a': a, 'component_b': b, 'instance_a': ids[a]['instance'], 'instance_b': ids[b]['instance'],
            **mobility(p['rows'], origin, scale), 'native_feature_ids': p['native_feature_ids'],
            'recommendation_source': 'supported_existing_constraint_rows_not_design_intent',
            'requires_goal_confirmation': True})
    return {'schema_version': 1, 'status': 'native_health_issues' if analysis['mate_health_issues'] else 'review_ready',
        'complete': True, 'component_count': len(cs), 'mate_count': len(survey['mates']),
        'connections': rows, 'mate_health_issues': analysis['mate_health_issues'],
        'suppressed_mates': [{'native_feature_id': m.get('native_feature_id'), 'name': m.get('name')}
                            for m in survey['mates'] if m.get('suppressed') is True],
        'omitted_native_feature_ids': omitted, 'constraint_review': ac.summary(analysis),
        'geometry_scope':{'complete':all(c.get('geometry_complete',True) for c in cs),
            'truncated_components':[c['instance'] for c in cs if c.get('geometry_complete') is False],
            'candidate_search':'bounded_native_snapshot_not_exhaustive_global_geometric_uniqueness'},
        'native_fully_constrained_components':[{'component_id':c['component_id'],'instance':c['instance'],
            'observation':c['constraint_state']} for c in cs if (c.get('constraint_state') or {}).get('status')=='observed' and (c.get('constraint_state') or {}).get('fully_constrained') is True],
        'native_constraint_state_is_not_numeric_global_DOF':True,
        'global_DOF': None, 'all_mates_sufficient': None, 'write_dispatched': False,
        'motion_verified': False, 'native_motion_study_solved': False,
        'guidance': 'AI解释原生故障与局部运动线索；压缩或自由度不自动解释为错误。根据用户目标规划刚性、转动或滑动连接；未知及冲突不自动删除旧约束。'}


def _line_matches(a, b):
    x, y = ac.unit(a['axis_global']), ac.unit(b['axis_global'])
    d = [a['reference_point_global_m'][i]-b['reference_point_global_m'][i] for i in range(3)]
    return math.sqrt(ac.dot(ac.cross(x,y),ac.cross(x,y)))<=5e-7 and math.sqrt(ac.dot(ac.cross(d,x),ac.cross(d,x)))<=5e-8


def _axes(survey, a, b, hint, pair, origin, scale,kind):
    found = []; inferred = mobility(pair.get('rows',[]),origin,scale)
    if inferred.get('axis_global') and inferred.get('recommended_joint_type')==kind:
        found.append({'axis_global': inferred['axis_global'], 'reference_point_global_m': inferred['axis_point_global_m'],
                      'source': 'existing_supported_local_motion'})
        if hint is None or abs(ac.dot(ac.unit(hint),ac.unit(inferred['axis_global'])))>1-1e-8:return found
    for m in survey['mates']:
        es=m.get('entities') or []
        if m.get('type')!=1 or m.get('suppressed') is not False or m.get('error')!=0 or m.get('warning') or len(es)!=2 or {e.get('component_id') for e in es}!={a['component_id'],b['component_id']}:continue
        try:
            ac._rows(m,es,origin,scale)
            geometry=es[0].get('geometry') or es[0].get('constraint_geometry') or {}
            axis=ac.unit(geometry['axis_global']);p=geometry['reference_point_global_m']
        except (KeyError,ValueError,TypeError):continue
        row={'axis_global':axis,'reference_point_global_m':p,'source':'existing_native_concentric_material_axis'}
        if not any(_line_matches(row,r) for r in found):found.append(row)
    if found and kind=='revolute':
        if hint is not None:found=[r for r in found if abs(ac.dot(ac.unit(hint),r['axis_global']))>1-1e-8]
        return found
    for fa in a.get('cylinders',[]):
        for fb in b.get('cylinders',[]):
            if _line_matches(fa,fb) and not any(_line_matches(fa,r) for r in found):
                found.append({'axis_global': fa['axis_global'], 'reference_point_global_m': fa['reference_point_global_m'],
                              'source': 'current_native_coaxial_geometry_not_motion_proof'})
    if hint is not None:
        h=ac.unit(hint); found=[r for r in found if abs(ac.dot(ac.unit(r['axis_global']),h))>1-1e-8]
        if not found and kind=='prismatic':found=[{'axis_global':h,'reference_point_global_m':a['transform'][9:12],
            'source':'explicit_slide_direction_point_does_not_define_a_rotation_axis'}]
        # Direction alone does not identify a material rotation axis. Never
        # manufacture a shaft through the component origin.
    return found


def _candidates(a,b,origin,scale):
    rows=[]
    for fa in a.get('cylinders',[]):
        for fb in b.get('cylinders',[]):
            if _line_matches(fa,fb):
                m={'type':1};es=[{'geometry':{**r,'kind':'cylindrical_axis'}} for r in (fa,fb)]
                rows.append((0,'concentric',fa,fb,ac._rows(m,es,origin,scale),None))
    for fa in a.get('completion_planes',[])+a.get('planes',[]):
        for fb in b.get('completion_planes',[])+b.get('planes',[]):
            na,nb=ac.unit(fa['axis_global']),ac.unit(fb['axis_global']);cosine=ac.dot(na,nb)
            if abs(cosine)>1-1e-8:
                es=[{'geometry':{**r,'kind':'planar_normal'}} for r in (fa,fb)]
                rows.append((1,'parallel',fa,fb,ac._rows({'type':3},es,origin,scale),None))
                dist=abs(ac.dot(na,[fa['reference_point_global_m'][i]-fb['reference_point_global_m'][i] for i in range(3)]))
                rows.append((2,'distance',fa,fb,ac._rows({'type':5},es,origin,scale),dist))
            else:
                es=[{'geometry':{**r,'kind':'planar_normal'}} for r in (fa,fb)]
                kind='perpendicular' if abs(cosine)<1e-8 else 'angle'
                value=None if kind=='perpendicular' else math.acos(max(-1,min(1,cosine)))
                rows.append((3,kind,fa,fb,ac._rows({'type':2 if kind=='perpendicular' else 6},es,origin,scale),value))
    return rows


def rotary_trial_driver(candidates, axis, component_a, component_b):
    """Stable datum-plane angle, away from singular zero/pi branches."""
    possible=[];axis=ac.unit(axis)
    for _,kind,fa,fb,_,_ in candidates:
        if kind not in {'angle','perpendicular'} or any(f.get('reference_kind')!='datum_plane' for f in (fa,fb)):continue
        na,nb=ac.unit(fa['axis_global']),ac.unit(fb['axis_global'])
        angle=math.acos(max(-1,min(1,ac.dot(na,nb))))
        sensitivity=abs(ac.dot(ac.cross(axis,na),nb))
        if sensitivity<.5 or not .01<angle<math.pi-.01:continue
        possible.append((-sensitivity,fa['native_reference'],fb['native_reference'],fa,fb,na,nb,angle))
    if not possible:return None
    _,_,_,fa,fb,na,nb,angle=min(possible,key=lambda x:x[:3])
    return {'component_a':component_a,'component_b':component_b,'reference_a':fa['native_reference'],
        'reference_b':fb['native_reference'],'reference_kind_a':'datum_plane','reference_kind_b':'datum_plane',
        'normal_a_global':na,'normal_b_global':nb,'kind':'angle','value':angle,
        'source':'current_native_datum_planes_non_singular_angle',
        'temporary_only':True,'removed_by_verified_result_checkpoint_after_each_trial':True}


def plan(survey, intents):
    if not isinstance(intents,list) or not 1<=len(intents)<=8: raise ValueError('one_to_8_connection_goals_required')
    cs=survey['components']; by_id={c['component_id']:c for c in cs};indices={c['component_id']:i for i,c in enumerate(cs)}
    r=review(survey)
    if not r['complete'] or r['mate_health_issues']: raise ValueError('native_inventory_or_health_requires_review')
    pairs,omitted,origin,scale=observed_rows(survey);matrix=SparseBasis()
    def lift(rows,a,b=None):
        return [{**{6*indices[a]+i:x for i,x in enumerate(row) if abs(x)>1e-12},
                 **({6*indices[b]+i:-x for i,x in enumerate(row) if abs(x)>1e-12} if b is not None else {})} for row in rows]
    for c in cs:
        if c.get('fixed_component'):
            for row in lift(target_rows('rigid',None,None,origin,scale),c['component_id']): matrix.add(row)
    for (a,b),p in pairs.items():
        for row in lift(p['rows'],a,b):matrix.add(row)
    actions=[];goals=[];seen=set()
    for raw in intents:
        if not isinstance(raw,dict) or set(raw)-{'component_a','component_b','kind','axis_hint','candidate_id'}:raise ValueError('invalid_connection_goal_fields')
        a_id,b_id=raw.get('component_a'),raw.get('component_b');kind=raw.get('kind')
        if a_id not in by_id or b_id not in by_id or a_id==b_id or kind not in KINDS: raise ValueError('invalid_connection_goal')
        pair_key=tuple(sorted((a_id,b_id)))
        if pair_key in seen:raise ValueError('duplicate_or_conflicting_connection_goals')
        seen.add(pair_key);a,b=by_id[a_id],by_id[b_id]
        if a.get('fixed_component') and not b.get('fixed_component'): a_id,b_id=b_id,a_id;a,b=b,a
        if a.get('fixed_component'):raise ValueError('both_components_fixed_no_floating_target_for_native_trial')
        full=(a.get('constraint_state') or {}).get('status')=='observed' and (a.get('constraint_state') or {}).get('fully_constrained') is True
        if kind!='rigid' and full:raise ValueError('native_fully_constrained_mobile_goal_requires_review')
        pair=pairs.get(pair_key,{'rows':[]})
        choices=_axes(survey,a,b,raw.get('axis_hint'),pair,origin,scale,kind) if kind!='rigid' else [{'axis_global':None,'reference_point_global_m':None,'source':'declared_rigid_goal'}]
        selected=raw.get('candidate_id')
        numbered=[{'candidate_id':'axis-'+str(i+1),**c} for i,c in enumerate(choices)]
        if selected:
            choices=[c for c in numbered if selected==c['candidate_id']]
            if not choices:raise ValueError('invalid_axis_candidate_for_current_goal')
        if len(choices)!=1:
            return {'status':'axis_selection_required','write_dispatched':False,'goals':[], 'actions':[],
                'component_a':a_id,'component_b':b_id,'axis_choices':numbered,
                'question':'请按材料轴线或运动用途澄清目标方向，AI使用候选，不要求用户填写实体ID。'}
        chosen=choices[0];target=target_rows(kind,chosen['axis_global'],chosen['reference_point_global_m'],origin,scale)
        if len(ac.basis(target+pair['rows']))>len(ac.basis(target)):
            raise ValueError('existing_constraints_conflict_with_declared_motion')
        target_global=lift(target,a_id,b_id);before=matrix.trial(target_global);start=len(actions)
        if full and before:raise ValueError('native_full_constraint_conflicts_with_supported_missing_rank')
        native_links=[m for m in survey['mates'] if m.get('suppressed') is not True and any(e.get('component_id')==a_id for e in m.get('entities',[]))]
        if any(m.get('type')==16 for m in native_links):
            return {'status':'unsupported_native_lock_trial','goals':[],'actions':[],'write_dispatched':False,
                'instance_a':a['instance'],'instance_b':b['instance'],
                'instruction':'原生锁定配合不能由本版小幅移动后端独立认证；只读报告，不删除旧锁定配合。可另行采用已有完整Motion验证流程，不冒充本次通过。'}
        candidates=_candidates(a,b,origin,scale)
        while matrix.trial(target_global):
            options=[]
            for priority,k,fa,fb,rows,value in candidates:
                if len(ac.basis(target+rows))>len(ac.basis(target)):continue
                delta=matrix.trial(lift(rows,a_id,b_id))
                if delta:options.append((-delta,priority,k,fa,fb,rows,value))
            if not options:break
            _,_,k,fa,fb,rows,value=min(options,key=lambda x:(x[0],x[1],x[2],x[3]['native_reference'],x[4]['native_reference']))
            for row in lift(rows,a_id,b_id):matrix.add(row)
            actions.append({'kind':k,'component_a':a_id,'component_b':b_id,'reference_a':fa['native_reference'],
                'reference_b':fb['native_reference'],'reference_kind_a':fa.get('reference_kind','cylindrical_face'),
                'reference_kind_b':fb.get('reference_kind','cylindrical_face'),'value':value,
                'flip_dimension':k=='distance' and ac.dot(ac.unit(fa['axis_global']),[fa['reference_point_global_m'][i]-fb['reference_point_global_m'][i] for i in range(3)])>0,
                'reason':'independent_supplement_within_declared_motion_target'})
        remaining=matrix.trial(target_global)
        trial_driver=None
        if kind=='prismatic':
            possible=[]
            for _,k,fa,fb,rows,value in candidates:
                if k!='distance' or abs(ac.dot(ac.unit(fa['axis_global']),chosen['axis_global']))<1-1e-8:continue
                n=ac.unit(fa['axis_global']);signed=ac.dot(n,[fa['reference_point_global_m'][i]-fb['reference_point_global_m'][i] for i in range(3)])
                # Avoid a zero-distance branch ambiguity in the small trial.
                if abs(signed)>.0002:possible.append((fa.get('reference_kind')!='datum_plane',-abs(signed),fa['native_reference'],fa,fb,signed,n))
            if possible:
                _,_,_,fa,fb,signed,n=min(possible,key=lambda x:x[:3])
                trial_driver={'component_a':a_id,'component_b':b_id,'reference_a':fa['native_reference'],'reference_b':fb['native_reference'],
                    'reference_kind_a':fa['reference_kind'],'reference_kind_b':fb['reference_kind'],
                    'normal_global':n,'signed_distance_m':signed,'kind':'distance','value':abs(signed),
                    'source':'current_native_parallel_planes_nonzero_separation',
                    'temporary_only':True,'removed_by_verified_result_checkpoint_after_each_trial':True}
        rotary_driver=rotary_trial_driver(candidates,chosen['axis_global'],a_id,b_id) if kind=='revolute' else None
        goals.append({'component_a':a_id,'component_b':b_id,'instance_a':a['instance'],'instance_b':b['instance'],
            'kind':kind,**chosen,'missing_supported_constraints_before':before,'remaining_supported_constraints':remaining,
            'added_action_count':len(actions)-start,'linear_trial_driver':trial_driver,
            'rotary_trial_driver':rotary_driver,'motion_verified':False})
    return {'status':'unsupported_references' if any(g['remaining_supported_constraints'] for g in goals) else 'plan_ready',
        'goals':goals,'actions':actions,'omitted_native_feature_ids':omitted,'requires_explicit_confirmation':True,
        'existing_mates_deleted':[],'existing_mates_suppressed':[],'fixed_state_changes':[],
        'global_DOF':None,'native_compatibility_verified':False,'motion_verified':False,'write_dispatched':False}
