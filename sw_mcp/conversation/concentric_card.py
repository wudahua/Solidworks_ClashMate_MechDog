"""A declared constraint scope, separate from full trajectory equivalence. No CAD calls."""
import copy,datetime,hashlib,json,math
from . import geometry_audit as g

VERSION='concentric-scope-1.0'
TOL={'translation_m':1e-7,'rotation_rad':1e-6,'target_rotation_deg':.1,'interval_rotation_deg':.01}
RULES={'may_remove':['transverse_axis_offset','axis_tilt'],'must_preserve':['signed_twist_waveform','axial_displacement_waveform','all_other_component_poses','all_component_initial_poses'],
       'mate_type':'concentric','lock_rotation':False,'speed_rpm':12,'duration_s':1,'output_fps':30,'expected_signed_twist_deg':72,'initial_axis_must_already_align':True}

class CardError(ValueError):
    def __init__(self,code,diagnostics=None):
        self.code=code;self.diagnostics=diagnostics or {};super().__init__(code)

def seal(card):return hashlib.sha256(json.dumps({k:v for k,v in card.items() if k!='card_id'},sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')).hexdigest()
def pose_row(c):
    p=c['transform']
    if len(p)<13 or not all(math.isfinite(x) for x in p) or abs(p[12]-1)>1e-8:raise CardError('INVALID_INITIAL_TRANSFORM')
    row={'component_id':c['component_id'],'instance':c['instance'],'frame':'0','time_s':'0',**{k:p[9+i] for i,k in enumerate(('x_m','y_m','z_m'))}}
    row.update({'r'+str(i)+str(j):p[3*i+j] for i in range(3) for j in range(3)});return row
def create(plan,components,signature,confirmed=False,retrospective=False):
    if type(confirmed) is not bool:raise CardError('SCOPE_CONFIRMATION_MUST_BE_BOOLEAN')
    if plan.get('mate_type')!='concentric' or plan.get('lock_rotation') is not False:raise CardError('UNSUPPORTED_CARD_MATE')
    refs=[plan['reference_a'],plan['reference_b']];moving=[r for r in refs if r['fixed_component'] is False];fixed=[r for r in refs if r['fixed_component'] is True]
    if len(moving)!=1 or len(fixed)!=1:raise CardError('CARD_REQUIRES_ONE_FLOATING_ONE_FIXED')
    mid,fid=moving[0]['component_id'],fixed[0]['component_id'];ids=[c['component_id'] for c in components]
    if len(ids)!=len(set(ids)) or mid not in ids or fid not in ids or any(c['fixed_component'] is not (c['component_id']!=mid) or c.get('suppressed') for c in components):raise CardError('CARD_REQUIRES_ONLY_SELECTED_COMPONENT_FLOATING')
    initial={(0,c['component_id']):pose_row(c) for c in components};bound=g.binding(plan,initial,mid,fid);start=g.series(initial,bound)[0]
    if start['axis_radial_offset_mm']>TOL['translation_m']*1000 or math.radians(start['axis_tilt_deg'])>TOL['rotation_rad']:
        raise CardError('CARD_REQUIRES_ALIGNED_INITIAL_AXES_NO_REPOSITIONING',{'observed_radial_offset_mm':start['axis_radial_offset_mm'],
            'radial_limit_mm':TOL['translation_m']*1000,'observed_axis_tilt_deg':start['axis_tilt_deg'],
            'tilt_limit_deg':math.degrees(TOL['rotation_rad']),'constraint_write_dispatched':False,'card_policy':'strict_initial_axes_no_repositioning'})
    card={'schema':VERSION,'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'test_purpose':'specified_twist_and_axial_motion_retention_while_concentric_constraint_removes_transverse_offset_and_tilt',
        'rules':copy.deepcopy(RULES),'tolerances':copy.deepcopy(TOL),'binding':bound,'initial_components':copy.deepcopy(components),'native_pair':copy.deepcopy(refs),
        'input_reference_state_signature':signature,'scope_confirmed':confirmed,'confirmation_kind':'explicit_developer_or_operator_boolean_not_inferred_from_geometry',
        'retrospective_rule_application':retrospective,'native_execution_attested_by_card_alone':False,'automatic_mate_or_fixed_state_changes':False,'full_trajectory_equivalence_overridden':False}
    card['card_id']=seal(card);return card

def validate(card):
    if card.get('schema')!=VERSION or card.get('card_id')!=seal(card) or card.get('tolerances')!=TOL or card.get('rules')!=RULES:raise CardError('CARD_ID_OR_IMMUTABLE_POLICY_CHANGED')
    if type(card.get('scope_confirmed')) is not bool:raise CardError('INVALID_SCOPE_CONFIRMATION')

def rotation_distance(a,b):
    x,y=g.rotation(a),g.rotation(b)
    return math.acos(max(-1,min(1,(sum(x[i][j]*y[i][j] for i in range(3) for j in range(3))-1)/2)))
def evaluate(card,before_path,after_path):
    validate(card);before,after=g.load(before_path),g.load(after_path);ids={c['component_id'] for c in card['initial_components']};expected={(f,c) for f in range(31) for c in ids}
    if before.keys()!=expected or after.keys()!=expected:raise CardError('CARD_SAMPLE_SCOPE_OR_GRID_CHANGED')
    for rows in (before,after):
        if any(abs(float(r['time_s'])-f/30)>1e-7 for (f,c),r in rows.items()):raise CardError('CARD_TIME_GRID_CHANGED')
    a,b=g.series(before,card['binding']),g.series(after,card['binding']);moving=card['binding']['moving'];others=ids-{moving};checks={}
    initial={c['component_id']:pose_row(c) for c in card['initial_components']}
    initial_t=max(g.norm(g.sub(g.origin(rows[0,c]),g.origin(initial[c]))) for rows in (before,after) for c in ids)
    initial_r=max(rotation_distance(rows[0,c],initial[c]) for rows in (before,after) for c in ids)
    stationary_t=max(g.norm(g.sub(g.origin(rows[f,c]),g.origin(initial[c]))) for rows in (before,after) for f in range(31) for c in others)
    stationary_r=max(rotation_distance(rows[f,c],initial[c]) for rows in (before,after) for f in range(31) for c in others)
    axial=max(abs(x['axial_displacement_mm']-y['axial_displacement_mm'])/1000 for x,y in zip(a,b))
    twist=math.radians(max(abs(x['signed_twist_deg']-y['signed_twist_deg']) for x,y in zip(a,b)))
    for name,value,tol in [('initial_translation_m',initial_t,TOL['translation_m']),('initial_rotation_rad',initial_r,TOL['rotation_rad']),('stationary_component_translation_m',stationary_t,TOL['translation_m']),('stationary_component_rotation_rad',stationary_r,TOL['rotation_rad']),('axial_waveform_difference_m',axial,TOL['translation_m']),('signed_twist_waveform_difference_rad',twist,TOL['rotation_rad']),('after_axis_radial_offset_m',max(x['axis_radial_offset_mm'] for x in b)/1000,TOL['translation_m']),('after_axis_tilt_rad',math.radians(max(x['axis_tilt_deg'] for x in b)),TOL['rotation_rad'])]:
        checks[name]={'observed':value,'tolerance':tol,'passed':value<=tol}
    for label,values in [('before',a),('after',b)]:
        target_error=max(abs(x['signed_twist_deg']-72*x['time_s']) for x in values)
        interval_error=max(abs((y['signed_twist_deg']-x['signed_twist_deg'])-2.4) for x,y in zip(values,values[1:]))
        checks[label+'_signed_twist_target_deg']={'observed':target_error,'tolerance':.1,'passed':target_error<=.1}
        checks[label+'_signed_twist_interval_deg']={'observed':interval_error,'tolerance':.01,'passed':interval_error<=.01}
    passed=all(c['passed'] for c in checks.values())
    return {'schema':VERSION,'card_id':card['card_id'],'scope_measurements_passed':passed,'scope_confirmed':card['scope_confirmed'],
        'scope_acceptance_passed':passed and card['scope_confirmed'],'status':'measurements_pass_awaiting_scope_confirmation' if passed and not card['scope_confirmed'] else 'declared_scope_pass' if passed else 'declared_scope_failed',
        'retrospective_rule_application':card['retrospective_rule_application'],'native_execution_attested_by_evaluator':False,
        'full_trajectory_equivalence':'reported_separately_never_overridden','checks':checks,'frames':31,'component_count':len(ids),'pose_rows_per_run':31*len(ids),
        'allowed_changes_observed':{'radial_offset_before_max_mm':max(x['axis_radial_offset_mm'] for x in a),'radial_offset_after_max_mm':max(x['axis_radial_offset_mm'] for x in b),
            'tilt_before_max_deg':max(x['axis_tilt_deg'] for x in a),'tilt_after_max_deg':max(x['axis_tilt_deg'] for x in b)},
        'coordinate_convention':'native_selected_material_circle_centers_and_axes_SW_row_basis_in_fixed_peer_frame; quaternion_swing_twist_about_initial_fixed_axis',
        'component_origin_used_as_shaft_center':False,'native_DOF_count_proven':False,'physics_root_cause_proven':False,'CAD_calls':0,'before_series':a,'after_series':b}
