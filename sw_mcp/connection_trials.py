"""Material-bound, small-displacement checks; no contact or full travel claim."""
import math
from . import assembly_constraints as a
from .conversation import geometry_audit as g

TRANSLATION_STEP_M=.0001
ROTATION_STEP_RAD=math.pi/3600
POSITION_TOLERANCE_M=1e-7
ANGLE_TOLERANCE_RAD=1e-6


def rotation(p):return [p[i:i+3] for i in (0,3,6)]


def validate(p):
    if not isinstance(p,list) or len(p)!=16 or any(type(x) not in (int,float) or not math.isfinite(x) for x in p):
        raise ValueError('invalid_rigid_transform')
    r=rotation(p);o=g.mm(r,g.transpose(r))
    if max(abs(o[i][j]-(i==j)) for i in range(3) for j in range(3))>1e-7 or abs(a.dot(r[0],a.cross(r[1],r[2]))-1)>1e-7 or abs(p[12]-1)>1e-9 or any(abs(x)>1e-9 for x in p[13:]):
        raise ValueError('invalid_rigid_transform')


def point(p,local):return [x+y for x,y in zip(g.mv(g.transpose(rotation(p)),local),p[9:12])]


def target(p,axis,amount,angular=False,pivot=None):
    validate(p);axis=a.unit(axis);out=list(p)
    if not angular:
        out[9:12]=[p[9+i]+amount*axis[i] for i in range(3)];return out
    c,s=math.cos(amount),math.sin(amount);x,y,z=axis
    skew=[[0,-z,y],[z,0,-x],[-y,x,0]]
    q=[[c*(i==j)+(1-c)*axis[i]*axis[j]+s*skew[i][j] for j in range(3)] for i in range(3)]
    out[:9]=sum(g.mm(rotation(p),g.transpose(q)),[])
    pivot=p[9:12] if pivot is None else pivot
    out[9:12]=[pivot[i]+v for i,v in enumerate(g.mv(q,g.sub(p[9:12],pivot)))];validate(out);return out


def bind(goal,poses):
    pa,pb=(poses[goal[k]] for k in ('component_a','component_b'))
    validate(pa);validate(pb)
    p=goal['reference_point_global_m'] if goal['kind']!='rigid' else pa[9:12]
    axis=a.unit(goal['axis_global']) if goal['kind']!='rigid' else [0,0,1]
    return {**goal,'anchor_a_local_m':g.mv(rotation(pa),g.sub(p,pa[9:12])),
        'anchor_b_local_m':g.mv(rotation(pb),g.sub(p,pb[9:12])),
        'axis_a_local':g.mv(rotation(pa),axis),'axis_b_local':g.mv(rotation(pb),axis),
        'relative_rotation_initial':g.mm(rotation(pa),g.transpose(rotation(pb)))}


def measure(bound,poses):
    pa,pb=(poses[bound[k]] for k in ('component_a','component_b'));validate(pa);validate(pb)
    rb=rotation(pb);axis=a.unit(bound['axis_b_local'])
    d=g.mv(rb,g.sub(point(pa,bound['anchor_a_local_m']),point(pb,bound['anchor_b_local_m'])))
    axial=a.dot(d,axis);radial=g.norm(g.sub(d,[axial*x for x in axis]))
    actual=a.unit(g.mv(rb,g.mv(g.transpose(rotation(pa)),bound['axis_a_local'])))
    tilt=math.atan2(g.norm(a.cross(actual,axis)),a.dot(actual,axis))
    relative=g.mm(rotation(pa),g.transpose(rb))
    q=g.quat(g.mm(g.transpose(relative),bound['relative_rotation_initial']))
    angle=2*math.atan2(g.norm(q[1:]),abs(q[0]))
    twist=2*math.atan2(a.dot(q[1:],axis),q[0]);twist=(twist+math.pi)%(2*math.pi)-math.pi
    kind=bound['kind']
    passed=(g.norm(d)<=POSITION_TOLERANCE_M and angle<=ANGLE_TOLERANCE_RAD if kind=='rigid' else
            g.norm(d)<=POSITION_TOLERANCE_M and tilt<=ANGLE_TOLERANCE_RAD if kind=='revolute' else
            radial<=POSITION_TOLERANCE_M and angle<=ANGLE_TOLERANCE_RAD)
    return dict(passed=passed,anchor_gap_m=g.norm(d),axial_displacement_m=axial,radial_offset_m=radial,
        relative_rotation_rad=angle,axis_tilt_rad=tilt,signed_twist_rad=twist)


def trials(goal,poses):
    p=poses[goal['component_a']];kind=goal['kind'];axis=goal.get('axis_global') or [0,0,1]
    perpendicular=a.perpendiculars(axis);out=[]
    def add(label,axis,angular,allowed=False,sign=1):
        amount=sign*(ROTATION_STEP_RAD if angular else TRANSLATION_STEP_M)
        out.append(dict(label=label,allowed=allowed,angular=angular,requested=amount,
            target=target(p,axis,amount,angular,goal.get('reference_point_global_m'))))
    if kind=='revolute':
        for sign in (1,-1):add('allowed_rotation_'+str(sign),axis,True,True,sign)
        for i,v in enumerate(([1,0,0],[0,1,0],[0,0,1])):add('forbidden_translation_'+str(i),v,False)
        for i,v in enumerate(perpendicular):add('forbidden_tilt_'+str(i),v,True)
    elif kind=='prismatic':
        for sign in (1,-1):add('allowed_translation_'+str(sign),axis,False,True,sign)
        for i,v in enumerate(perpendicular):add('forbidden_transverse_'+str(i),v,False)
        for i,v in enumerate(([1,0,0],[0,1,0],[0,0,1])):add('forbidden_rotation_'+str(i),v,True)
    else:
        for angular in (False,True):
            for i,v in enumerate(([1,0,0],[0,1,0],[0,0,1])):add('forbidden_'+('rotation_' if angular else 'translation_')+str(i),v,angular)
    return out


def audit(evidence,bounds,selected,trial,expected_poses=None):
    before,after,restored=(evidence[k] for k in ('before','after','restored'))
    if set(before)!=set(after) or set(before)!=set(restored):raise ValueError('trial_component_scope_changed')
    if set(evidence['fixed_states'])!=set(before) or any(type(v) is not bool for v in evidence['fixed_states'].values()):raise ValueError('trial_fixed_state_scope_invalid')
    for poses in (before,after,restored):
        for p in poses.values():validate(p)
    def same(x,y):
        q=g.quat(g.mm(g.transpose(rotation(x)),rotation(y)))
        return math.dist(x[9:12],y[9:12])<=POSITION_TOLERANCE_M and 2*math.atan2(g.norm(q[1:]),abs(q[0]))<=ANGLE_TOLERANCE_RAD
    fixed=all(same(before[k],after[k]) for k,v in evidence['fixed_states'].items() if v)
    restore=all(same(before[k],restored[k]) for k in before)
    initial=expected_poses is None or set(expected_poses)==set(before) and all(same(expected_poses[k],before[k]) for k in before)
    checks=[measure(b,after) for b in bounds];current=checks[selected]
    travel=current['signed_twist_rad' if trial['angular'] else 'axial_displacement_m']
    native_return=evidence.get('native_trial_return',evidence.get('native_set_transform_return'))
    allowed=(not trial['allowed'] or native_return is True and abs(travel-trial['requested'])<=max(abs(trial['requested'])*.05,ANGLE_TOLERANCE_RAD if trial['angular'] else POSITION_TOLERANCE_M))
    passed=initial and fixed and restore and allowed and all(c['passed'] for c in checks) and evidence.get('original_mates_parameters_unchanged') is True and evidence.get('restoration_status')=='restored'
    return dict(passed=passed,trial=trial['label'],allowed_travel_verified=allowed,
        travel_requirement_applicable=trial['allowed'],
        fixed_poses_unchanged=fixed,all_poses_restored=restore,initial_pose_scope_matches=initial,connection_checks=checks,
        actual_travel=travel,requested_travel=trial['requested'],requested_travel_unit='rad' if trial['angular'] else 'm',native_return_is_not_verification=True,
        global_DOF_certified=False,whole_travel_certified=False,native_motion_study_solved=False)
