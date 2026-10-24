"""Offline material-axis measurements, SW row-basis transforms. Never writes CAD."""
from pathlib import Path
import csv,math

def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def norm(a):return math.sqrt(dot(a,a))
def unit(a):
    if len(a)!=3 or not all(math.isfinite(x) for x in a) or norm(a)<1e-12:raise ValueError('INVALID_AXIS')
    n=norm(a);return [x/n for x in a]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def transpose(a):return list(map(list,zip(*a)))
def mm(a,b):return [[sum(x*y for x,y in zip(row,col)) for col in zip(*b)] for row in a]
def mv(a,v):return [dot(row,v) for row in a]
def rotation(row):return [[float(row['r'+str(i)+str(j)]) for j in range(3)] for i in range(3)]
def origin(row):return [float(row[k]) for k in ('x_m','y_m','z_m')]
def point_world(row,local):return [x+y for x,y in zip(mv(transpose(rotation(row)),local),origin(row))]
def quat(q):
    t=sum(q[i][i] for i in range(3))
    if t>0:
        s=2*math.sqrt(t+1);return [s/4,(q[2][1]-q[1][2])/s,(q[0][2]-q[2][0])/s,(q[1][0]-q[0][1])/s]
    i=max(range(3),key=lambda i:q[i][i]);j=(i+1)%3;k=(i+2)%3;s=2*math.sqrt(max(0,1+q[i][i]-q[j][j]-q[k][k]))
    if s<1e-12:raise ValueError('INVALID_ROTATION_QUATERNION')
    v=[0.,0.,0.];v[i]=s/4;v[j]=(q[j][i]+q[i][j])/s;v[k]=(q[k][i]+q[i][k])/s
    return [(q[k][j]-q[j][k])/s,*v]
def load(path):
    rows={}
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        for r in csv.DictReader(stream):
            key=int(r['frame']),r['component_id']
            if key in rows:raise ValueError('DUPLICATE_SAMPLE')
            values=[float(r[k]) for k in ['time_s','x_m','y_m','z_m',*['r'+str(i)+str(j) for i in range(3) for j in range(3)]]]
            if not all(math.isfinite(x) for x in values):raise ValueError('NONFINITE_SAMPLE')
            a=rotation(r);orth=mm(a,transpose(a));det=dot(a[0],cross(a[1],a[2]))
            if max(abs(orth[i][j]-(i==j)) for i in range(3) for j in range(3))>1e-6 or abs(det-1)>1e-6:raise ValueError('POSE_NOT_PROPER_RIGID_ROTATION')
            rows[key]=r
    return rows
def binding(plan,data,moving,reference):
    refs={r['component_id']:r for r in (plan['reference_a'],plan['reference_b'])}
    if set(refs)!={moving,reference} or refs[moving]['fixed_component'] or not refs[reference]['fixed_component']:raise ValueError('PAIR_SCOPE_MISMATCH')
    m,f=data[0,moving],data[0,reference];pm,pf=(refs[c]['reference_point_global_m'] for c in (moving,reference))
    um,uf=(unit(refs[c]['axis_global']) for c in (moving,reference))
    if dot(um,uf)<0:uf=[-x for x in uf]
    return {'moving':moving,'reference':reference,'moving_axis_local':mv(rotation(m),um),'reference_axis_local':mv(rotation(f),uf),
        'moving_anchor_local_m':mv(rotation(m),sub(pm,origin(m))),'reference_anchor_local_m':mv(rotation(f),sub(pf,origin(f))),
        'source':'native_selected_edge_geometry_and_bound_frame0_inverse_rigid_transform','automatic_origin_as_shaft_axis':False}
def series(data,bound):
    moving,reference=bound['moving'],bound['reference'];axis=unit(bound['reference_axis_local']);initial=mm(rotation(data[0,moving]),transpose(rotation(data[0,reference])))
    values=[];previous=None;unwrapped=0
    for frame in sorted({k[0] for k in data}):
        m,f=data[frame,moving],data[frame,reference];rf=rotation(f)
        delta=mv(rf,sub(point_world(m,bound['moving_anchor_local_m']),point_world(f,bound['reference_anchor_local_m'])))
        axial=dot(delta,axis);radial=norm(sub(delta,[axial*x for x in axis]))
        actual_axis=unit(mv(rf,mv(transpose(rotation(m)),bound['moving_axis_local'])))
        tilt=math.degrees(math.atan2(norm(cross(actual_axis,axis)),dot(actual_axis,axis)))
        relative=mm(rotation(m),transpose(rf));q=quat(mm(transpose(relative),initial));projection=dot(q[1:],axis)
        if math.hypot(q[0],projection)<1e-9:raise ValueError('TWIST_UNDEFINED_AT_HALF_TURN_SWING')
        angle=math.degrees(2*math.atan2(projection,q[0]))
        if previous is not None:
            step=(angle-previous+180)%360-180
            if abs(step)>45:raise ValueError('TWIST_SAMPLE_ALIASING')
            unwrapped+=step
        previous=angle
        values.append({'frame':frame,'time_s':float(m['time_s']),'axial_position_mm':axial*1000,'axis_radial_offset_mm':radial*1000,'axis_tilt_deg':tilt,'signed_twist_deg':unwrapped})
    for row in values:row['axial_displacement_mm']=row['axial_position_mm']-values[0]['axial_position_mm']
    return values
