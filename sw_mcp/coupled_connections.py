"""Strict, zero-supplement review of an already observed screw linkage.

No helical equation is inserted into the supported linear matrix. The native
component status is retained; actual coupled movement must still be measured.
"""
import math
from . import assembly_constraints as a, constraint_graph, connection_trials as t
from .conversation import geometry_audit as g

def _number(x):return type(x) in (int,float) and math.isfinite(x)
def _shape(e):
    v=e.get('geometry') or e.get('constraint_geometry') or {}
    p=v.get('reference_point_global_m');axis=a.unit(v.get('axis_global'))
    if not isinstance(p,list) or len(p)!=3 or not all(_number(x) for x in p):raise ValueError('unobserved_material_point')
    return v.get('kind'),axis,p

def review(survey,target,reference,kind):
    """An explicit exception for verification only, never permission to add mates."""
    if kind!='prismatic':return None
    try:
        graph=constraint_graph.model(survey);by=graph.by_id
        if by[target].get('fixed_component') is not False:return None
        status=by[target].get('constraint_state') or {}
        if status.get('status')!='observed' or status.get('native_value')!=3 or status.get('fully_constrained') is not True:return None
        if graph.rank(target,reference)!=5 or graph.rank(reference,None)!=6:return None
        from .assembly_connections import mobility
        motion=mobility(graph.relative(target,reference)['rows'],graph.origin,graph.scale)
        if motion.get('recommended_joint_type')!='prismatic':return None
        axis=a.unit(motion['axis_global']);mates={m['native_feature_id']:m for m in survey['mates']}
        observations={n['native_feature_id']:n for n in survey.get('nonlinear_constraints',[])}
        candidates=[]
        for mid,n in observations.items():
            if n.get('kind')!='screw' or n.get('status')!='observed' or n.get('parameters_in_input_signature') is not True:continue
            if type(n.get('native_revolution_type')) is not int or n['native_revolution_type']!=1 or not _number(n.get('native_revolution_value')) or n['native_revolution_value']<=0 or type(n.get('reverse')) is not bool:continue
            # The bounded verification also caps every component rotation at 1 degree.
            if 2*math.pi*t.TRANSLATION_STEP_M/n['native_revolution_value']>math.pi/180:continue
            m=mates[mid];es=m.get('entities') or []
            if m.get('type')!=17 or m.get('error')!=0 or m.get('warning') or m.get('suppressed') is not False or len(es)!=2:continue
            for nut,shaft in ((es[0],es[1]),(es[1],es[0])):
                ni,si=nut.get('component_id'),shaft.get('component_id')
                if ni not in by or si not in by or ni==si:continue
                if ni!=target and graph.rank(ni,target)!=6:continue
                if graph.rank(si,reference)!=5:continue
                shaft_motion=mobility(graph.relative(si,reference)['rows'],graph.origin,graph.scale)
                if shaft_motion.get('recommended_joint_type')!='revolute':continue
                kn,an,pn=_shape(nut);ks,as_,ps=_shape(shaft)
                nut_geometry=nut.get('geometry') or nut.get('constraint_geometry') or {}
                nut_axis_known=kn=='cylindrical_axis' or (kn=='circular_edge' and nut_geometry.get('full_circle') is True and nut_geometry.get('native_reference_roundtrip_verified') is True)
                if not nut_axis_known or ks!='cylindrical_axis' or abs(a.dot(an,as_))<1-1e-8 or abs(a.dot(axis,as_))<1-1e-8 or abs(a.dot(shaft_motion['axis_global'],as_))<1-1e-8:continue
                if g.norm(a.cross(g.sub(pn,ps),as_))>1e-7:continue
                candidates.append({'native_feature_id':mid,'nut_component_id':ni,'shaft_component_id':si,'axis_global':as_,'reference_point_global_m':ps,'lead_m_per_revolution':n['native_revolution_value'],'native_reverse':n['reverse'],'native_mate_alignment':n.get('mate_alignment')})
        if len(candidates)!=1:return None
        screw=candidates[0];accepted={screw['native_feature_id']};limits=[]
        for unknown in graph.unknown:
            mid=unknown['native_feature_id']
            if mid in accepted:continue
            n=observations.get(mid) or {};m=mates.get(mid) or {};es=m.get('entities') or []
            if n.get('kind')!='limit_distance' or n.get('status')!='observed' or n.get('parameters_in_input_signature') is not True or len(es)!=2:return None
            if m.get('type')!=5 or m.get('error')!=0 or m.get('warning') or m.get('suppressed') is not False:return None
            ids=[e.get('component_id') for e in es]
            if target not in ids or any(cid not in by for cid in ids):return None
            other=ids[1-ids.index(target)]
            if graph.rank(other,None)!=6:return None
            ka,na,pa=_shape(es[0]);kb,nb,pb=_shape(es[1])
            if ka!='planar_normal' or kb!='planar_normal' or abs(a.dot(na,nb))<1-1e-8 or abs(a.dot(na,axis))<1-1e-8:return None
            low,high,current=(n.get(k) for k in ('minimum_distance_m','maximum_distance_m','distance_m'))
            if not all(_number(x) for x in (low,high,current)) or low<0 or high<=low:return None
            measured=abs(a.dot(na,g.sub(pa,pb)))
            if abs(measured-current)>t.POSITION_TOLERANCE_M or measured-low<2*t.TRANSLATION_STEP_M or high-measured<2*t.TRANSLATION_STEP_M:return None
            limits.append({'native_feature_id':mid,'component_a':ids[0],'component_b':ids[1],'normal_a_global':na,'normal_b_global':nb,'point_a_global_m':pa,'point_b_global_m':pb,'minimum_distance_m':low,'maximum_distance_m':high,'current_distance_m':measured});accepted.add(mid)
        return {'mode':'existing_screw_linkage_verification_only','screw':screw,'limits':limits,'grounded_components':[cid for cid in by if graph.rank(cid,None)==6],
                'native_full_observation':status,'native_full_observation_overridden':False,'persistent_mate_writes_allowed':False,
                'unknown_constraints_modelled_as_missing':False,'nonlinear_equations_inserted_into_linear_matrix':False,'motion_verified':False,'global_DOF_certified':False}
    except (ValueError,KeyError,TypeError,ZeroDivisionError):return None

def bind(evidence,poses):
    screw=evidence['screw'];material=t.bind({'component_a':screw['nut_component_id'],'component_b':screw['shaft_component_id'],'kind':'revolute','axis_global':screw['axis_global'],'reference_point_global_m':screw['reference_point_global_m']},poses)
    limits=[]
    for l in evidence['limits']:
        pa,pb=(poses[l[k]] for k in ('component_a','component_b'))
        limits.append({**l,'point_a_local':g.mv(t.rotation(pa),g.sub(l['point_a_global_m'],pa[9:12])),'point_b_local':g.mv(t.rotation(pb),g.sub(l['point_b_global_m'],pb[9:12])),
                       'normal_a_local':g.mv(t.rotation(pa),l['normal_a_global']),'normal_b_local':g.mv(t.rotation(pb),l['normal_b_global'])})
    return {**evidence,'material_screw_binding':material,'material_limits':limits,'initial_ground_poses':{cid:poses[cid] for cid in evidence['grounded_components']}}

def audit(binding,poses):
    measured=t.measure(binding['material_screw_binding'],poses);s=binding['screw'];linear=measured['axial_displacement_m'];angle=measured['signed_twist_rad'];pitch=s['lead_m_per_revolution']/(2*math.pi)
    residual=abs(abs(linear)-pitch*abs(angle));tolerance=t.POSITION_TOLERANCE_M+pitch*t.ANGLE_TOLERANCE_RAD
    sign=(1 if linear*angle>0 else -1) if abs(linear)>t.POSITION_TOLERANCE_M and abs(angle)>t.ANGLE_TOLERANCE_RAD else None
    limits=[]
    for l in binding['material_limits']:
        pa,pb=(poses[l[k]] for k in ('component_a','component_b'));na=a.unit(g.mv(g.transpose(t.rotation(pa)),l['normal_a_local']));nb=a.unit(g.mv(g.transpose(t.rotation(pb)),l['normal_b_local']))
        value=abs(a.dot(na,g.sub(t.point(pa,l['point_a_local']),t.point(pb,l['point_b_local']))))
        limits.append({'native_feature_id':l['native_feature_id'],'actual_distance_m':value,'passed':l['minimum_distance_m']-t.POSITION_TOLERANCE_M<=value<=l['maximum_distance_m']+t.POSITION_TOLERANCE_M and g.norm(a.cross(na,nb))<=t.ANGLE_TOLERANCE_RAD})
    ground=[]
    for cid,p in binding['initial_ground_poses'].items():
        actual=poses[cid];q=g.quat(g.mm(g.transpose(t.rotation(p)),t.rotation(actual)));d=math.dist(p[9:12],actual[9:12]);r=2*math.atan2(g.norm(q[1:]),abs(q[0]))
        ground.append({'component_id':cid,'translation_m':d,'rotation_rad':r,'passed':d<=t.POSITION_TOLERANCE_M and r<=t.ANGLE_TOLERANCE_RAD})
    return {'passed':residual<=tolerance and measured['radial_offset_m']<=t.POSITION_TOLERANCE_M and measured['axis_tilt_rad']<=t.ANGLE_TOLERANCE_RAD and all(v['passed'] for v in limits+ground),
            'native_feature_id':s['native_feature_id'],'relative_axial_displacement_m':linear,'relative_twist_rad':angle,'lead_relation_residual_m':residual,'lead_relation_tolerance_m':tolerance,
            'observed_signed_relation':sign,'sign_scope':'material_frame_observed_consistency_not_inferred_design_intent_or_reverse_flag_semantics',
            'limit_checks':limits,'grounded_reference_checks':ground,'full_travel_certified':False}
