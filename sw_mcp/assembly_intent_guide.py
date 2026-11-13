"""Geometry-backed mechanical questions, not inferred design or write references."""
import hashlib
import json
import math

LINE_TOLERANCE_M=1e-6
MAX_AXIS_ROWS=4000
MAX_COMPARISONS=250000


def build(survey,analytic=None):
    components={c['component_id']:c for c in survey.get('components',[])}
    rows=(analytic or {}).get('rows')
    if rows is None:
        rows=[dict(r,component_id=c['component_id'],kind='cylindrical_axis') for c in components.values() for r in c.get('cylinders',[])]
    axes=[r for r in rows if (r.get('kind')=='cylindrical_axis' or r.get('reference_kind')=='cylindrical_face')
          and r.get('axis_global') is not None and r.get('reference_point_global_m') is not None]
    groups=[];comparisons=0;processed=0;invalid=0;budget=False
    for row in axes[:MAX_AXIS_ROWS]:
        if row.get('component_id') not in components:invalid+=1;continue
        try:
            axis=row['axis_global'];point=row['reference_point_global_m']
            if len(axis)!=3 or len(point)!=3 or any(type(x) not in (float,int) or not math.isfinite(x) for x in axis+point):raise ValueError()
            norm=math.sqrt(sum(x*x for x in axis))
            if norm<1e-12:raise ValueError()
            axis=[x/norm for x in axis]
            if next(x for x in axis if abs(x)>1e-12)<0:axis=[-x for x in axis]
            foot=[point[i]-sum(point[j]*axis[j] for j in range(3))*axis[i] for i in range(3)]
        except (ValueError,TypeError,StopIteration):invalid+=1;continue
        matched=None
        for group in groups:
            comparisons+=1
            if comparisons>MAX_COMPARISONS:budget=True;break
            if (sum((axis[i]-group['axis'][i])**2 for i in range(3))<=1e-12
                    and sum((foot[i]-group['point'][i])**2 for i in range(3))<=LINE_TOLERANCE_M**2):
                matched=group;break
        if budget:break
        if matched is None:
            matched={'axis':axis,'point':foot,'members':set()};groups.append(matched)
        matched['members'].add(row['component_id']);processed+=1
    suggestions=[];covered=set()
    for group in groups:
        members=sorted(group['members'])
        if len(members)<2:continue
        covered.update(members)
        gid=hashlib.sha256(json.dumps([group['axis'],group['point'],members],sort_keys=True).encode()).hexdigest()[:16]
        names=[components[cid]['instance'] for cid in members]
        for start in range(0,len(names),16):
            suggestions.append({'group_id':gid,'member_range_start':start,'member_count':len(names),
                'members':names[start:start+16],'members_suffix_complete':start+16>=len(names),
                'axis_global':group['axis'],'axis_point_global_m':group['point'],
                'observed_fixed_members':[components[c]['instance'] for c in members[start:start+16] if components[c].get('fixed_component') is True],
                'recommended_question':'这些同轴成员中，哪些随同一运动组刚性联动，哪些保留转动或轴向滑动？AI复用已有机械目标，仅集中澄清未说明部分。',
                'mechanical_options':['rigid','revolute','prismatic'],
                'scope':'near_coaxial_material_lines_only_not_proven_connection_or_stationary_ownership',
                'native_write_reference':False,'design_intent_proven':False})
    complete=(not budget and len(axes)<=MAX_AXIS_ROWS and invalid==0
              and (analytic or {}).get('analytic_geometry_complete') is True)
    return {'schema_version':1,'scope':'grouped_geometry_hypotheses_not_executable_plan',
        'geometry_search_scope':'cylindrical_axis_groups_only_not_all_connection_types',
        'zero_mate_assembly':len(survey.get('mates',[]))==0,'component_count':len(components),
        'axis_rows_available':len(axes),'axis_rows_processed':processed,'invalid_rows':invalid,
        'comparison_count':comparisons,'budget_reached':budget or len(axes)>MAX_AXIS_ROWS,
        'geometry_search_complete':complete,'line_tolerance_m':LINE_TOLERANCE_M,
        'group_count':len({g['group_id'] for g in suggestions}),'groups':suggestions,
        'components_without_axis_group':[c['instance'] for cid,c in components.items() if cid not in covered],
        'rigid_ownership_inferred':False,'automatic_plan_available':False,'write_dispatched':False,
        'whole_assembly_route':{'completion_scope':'whole_assembly','maximum_goals':128,
            'maximum_new_mates':512,'public_execution_confirmation_count':1,'native_batches_are_internal':True,
            'verification_choices':{'independent_joint_trials':'局部连接可独立活动时使用；成本随目标数增加。',
                'driven_loop':'完整平面/空间刚体连接目标及主直线输入、参考、输出明确时使用；逐帧检查全部声明关节和输出。'},
            'instruction':'AI结合全部机械目标补充完整connection_intent或rigid_groups，检查全部组件覆盖后一次预演和确认。几何组不是自动锁定授权，不因候选搜索未完而要求逐件交互。'}}
