import copy,math,unittest,tempfile,csv,pathlib
from types import SimpleNamespace
from sw_mcp import coupled_connections as c,assembly_connections as j,connection_trials as t

def pose(z=0):return [1,0,0,0,1,0,0,0,1,0,0,z,1,0,0,0]
def scene():
    cs=[]
    for name,z,fixed in [('rail',0,True),('slider',.1,False),('nut',.1,False),('shaft',0,False)]:
        planes=[{'axis_global':n,'reference_point_global_m':[0,0,z],'native_reference':name+str(i),'reference_kind':'datum_plane'} for i,n in enumerate(([1,0,0],[0,1,0],[0,0,1]))]
        cs.append({'component_id':name,'instance':name,'fixed_component':fixed,'transform':pose(z),'box':[-.1,-.1,z-.1,.1,.1,z+.1],'completion_planes':planes,
                   'constraint_state':{'status':'observed','native_value':3,'fully_constrained':True}})
    mates=[]
    def mate(a,b,kind,axis=(0,0,1),point=(0,0,0),feature='MateCoincident'):
        es=[{'component_id':cid,'instance':cid,'geometry':{'kind':'cylindrical_axis' if kind in (1,17) else 'planar_normal','axis_global':list(axis),'reference_point_global_m':list(point)}} for cid in (a,b)]
        m={'native_feature_id':len(mates)+1,'type':kind,'native_feature_type':feature,'error':0,'warning':False,'suppressed':False,'alignment':0,'entities':es};mates.append(m);return m
    mate('slider','rail',0,(1,0,0));mate('slider','rail',0,(0,1,0))
    for axis in ((1,0,0),(0,1,0),(0,0,1)):mate('nut','slider',0,axis,(0,0,.1))
    mate('shaft','rail',1);mate('shaft','rail',0)
    screw=mate('nut','shaft',17,feature='MateScrew');screw['entities'][0]['geometry'].update(kind='circular_edge',full_circle=True,native_reference_roundtrip_verified=True)
    limit=mate('slider','rail',5,feature='MateLimitDistanceDim');limit['entities'][0]['geometry']['reference_point_global_m']=[0,0,.1]
    nla=[{'native_feature_id':screw['native_feature_id'],'kind':'screw','status':'observed','parameters_in_input_signature':True,'native_revolution_type':1,'native_revolution_value':.3,'reverse':True,'mate_alignment':1},
         {'native_feature_id':limit['native_feature_id'],'kind':'limit_distance','status':'observed','parameters_in_input_signature':True,'distance_m':.1,'minimum_distance_m':.001,'maximum_distance_m':1}]
    return {'components':cs,'mates':mates,'inventory_complete':True,'nonlinear_constraints':nla}

class CoupledConnectionsTests(unittest.TestCase):
    def review(self,s):return c.review(s,'slider','rail','prismatic')
    def test_eligible_linkage_retains_native_status_and_zero_write_scope(self):
        r=self.review(scene());self.assertIsNotNone(r);self.assertFalse(r['native_full_observation_overridden']);self.assertFalse(r['persistent_mate_writes_allowed']);self.assertEqual(r['native_full_observation']['native_value'],3)
    def test_plan_has_zero_actions_and_uncertified_motion(self):
        r=j.plan(scene(),[{'component_a':'slider','component_b':'rail','kind':'prismatic'}]);self.assertEqual(r['actions'],[]);self.assertTrue(r['goals'][0]['coupled_verification_only']);self.assertFalse(r['goals'][0]['supported_target_fulfilment_certified'])
    def test_missing_signature_witness_refuses(self):
        s=scene();s['nonlinear_constraints'][0].pop('parameters_in_input_signature');self.assertIsNone(self.review(s))
    def test_unsupported_revolution_mode_refuses(self):
        s=scene();s['nonlinear_constraints'][0]['native_revolution_type']=0;self.assertIsNone(self.review(s))
    def test_nan_pitch_refuses(self):
        s=scene();s['nonlinear_constraints'][0]['native_revolution_value']=math.nan;self.assertIsNone(self.review(s))
    def test_arc_is_not_silently_accepted_as_axis(self):
        s=scene();s['mates'][7]['entities'][0]['geometry']['full_circle']=False;self.assertIsNone(self.review(s))
    def test_unverified_edge_identity_refuses(self):
        s=scene();s['mates'][7]['entities'][0]['geometry']['native_reference_roundtrip_verified']=False;self.assertIsNone(self.review(s))
    def test_duplicate_coupling_is_not_guessed(self):
        s=scene();m=copy.deepcopy(s['mates'][7]);m['native_feature_id']=30;s['mates'].append(m);n=copy.deepcopy(s['nonlinear_constraints'][0]);n['native_feature_id']=30;s['nonlinear_constraints'].append(n);self.assertIsNone(self.review(s))
    def test_limit_observation_must_match_material_geometry(self):
        s=scene();s['nonlinear_constraints'][1]['distance_m']=.2;self.assertIsNone(self.review(s))
    def test_near_limit_requires_separate_review(self):
        s=scene();s['nonlinear_constraints'][1]['minimum_distance_m']=.0999;self.assertIsNone(self.review(s))
    def test_unknown_constraint_is_not_discarded(self):
        s=scene();m=copy.deepcopy(s['mates'][0]);m.update(native_feature_id=40,type=99);s['mates'].append(m);self.assertIsNone(self.review(s))
    def test_overconstrained_direction_is_not_relaxed(self):
        s=scene();m=copy.deepcopy(s['mates'][0]);m.update(native_feature_id=40);m['entities'][0]['geometry']['axis_global']=[0,0,1];m['entities'][1]['geometry']['axis_global']=[0,0,1];s['mates'].append(m);self.assertIsNone(self.review(s))
    def test_reference_must_be_supported_grounded(self):
        s=scene();s['components'][0]['fixed_component']=False;self.assertIsNone(self.review(s))
    def test_ordinary_full_component_remains_rejected(self):
        s=scene();s['nonlinear_constraints']=[]
        with self.assertRaisesRegex(ValueError,'native_fully_constrained_mobile_goal_requires_review'):j.plan(s,[{'component_a':'slider','component_b':'rail','kind':'prismatic'}])
    def test_existing_lock_or_other_mobile_kind_not_enabled(self):self.assertIsNone(c.review(scene(),'slider','rail','revolute'))
    def test_mixed_supplement_is_refused(self):
        s=scene();x=copy.deepcopy(s['components'][1]);x.update(component_id='extra',instance='extra',constraint_state={'status':'observed','native_value':2,'fully_constrained':False});s['components'].append(x)
        with self.assertRaisesRegex(ValueError,'coupled_verification_cannot_mix_supplements'):j.plan(s,[{'component_a':'slider','component_b':'rail','kind':'prismatic'},{'component_a':'extra','component_b':'rail','kind':'rigid'}])
    def binding(self):
        s=scene();poses={x['component_id']:x['transform'] for x in s['components']};return c.bind(self.review(s),poses),poses
    def movement(self,amount):
        b,poses=self.binding();poses=copy.deepcopy(poses);poses['slider'][11]+=amount;poses['nut'][11]+=amount;poses['shaft']=t.target(poses['shaft'],[0,0,1],2*math.pi*amount/.3,True,[0,0,0]);return b,poses
    def test_forward_and_reverse_material_relation(self):
        results=[c.audit(*self.movement(d)) for d in (.0001,-.0001)];self.assertTrue(all(x['passed'] for x in results));self.assertEqual(results[0]['observed_signed_relation'],results[1]['observed_signed_relation'])
    def test_locked_shaft_is_not_a_motion_success(self):
        b,p=self.movement(.0001);p['shaft']=pose();self.assertFalse(c.audit(b,p)['passed'])
    def test_ground_drift_is_not_hidden_by_relative_measurement(self):
        b,p=self.movement(.0001)
        for v in p.values():v[9]+=.001
        self.assertFalse(c.audit(b,p)['passed'])
    def test_limit_exceeded_is_reported(self):
        b,p=self.movement(.901);r=c.audit(b,p);self.assertFalse(r['passed']);self.assertFalse(r['limit_checks'][0]['passed'])
    def test_short_lead_cannot_exceed_confirmed_one_degree_budget(self):
        s=scene();s['nonlinear_constraints'][0]['native_revolution_value']=.005;self.assertIsNone(self.review(s))
    def test_automatic_draft_identifies_existing_coupling_without_unfix(self):
        from sw_mcp.connection_recommendations import draft
        r=draft(scene());rows=[x for x in r['candidates'] if {x['instance_a'],x['instance_b']}=={'slider','rail'}]
        self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['blocker']);self.assertEqual(rows[0]['instance_a'],'slider')
        option=rows[0]['options'][rows[0]['preferred_option_index']];self.assertTrue(option['verification_only']);self.assertEqual(option['persistent_mates_added'],0)

class CoupledMotionAuditTests(unittest.TestCase):
    review=CoupledConnectionsTests.review
    binding=CoupledConnectionsTests.binding
    movement=CoupledConnectionsTests.movement
    def grid(self,sign=1):
        from sw_mcp.conversation import coupled_motion as m
        s=scene();poses={v['component_id']:v['transform'] for v in s['components']};goal=j.plan(s,[{'component_a':'slider','component_b':'rail','kind':'prismatic'}])['goals'][0]
        bound=t.bind(goal,poses);coupled=c.bind(c.review(s,'slider','rail','prismatic'),poses)
        values=[self.movement(sign*.0001*i/30)[1] for i in range(31)]
        trial={'label':'allowed_translation_'+str(sign),'requested':sign*.0001,'allowed':True}
        return m,values,poses,[bound],coupled,trial
    def test_motion_samples_measure_both_signed_directions(self):
        for sign in (-1,1):
            m,grid,p,b,coupled,trial=self.grid(sign);r=m.audit(grid,p,b,0,coupled,trial)
            self.assertTrue(r['passed']);self.assertEqual(r['pose_rows'],124);self.assertAlmostEqual(r['actual_travel'],sign*.0001)
    def test_stationary_native_frames_cannot_count_as_motion(self):
        m,grid,p,b,coupled,trial=self.grid();grid=[copy.deepcopy(p) for _ in grid];self.assertFalse(m.audit(grid,p,b,0,coupled,trial)['passed'])
    def test_motion_wrong_sign_cannot_pass(self):
        m,grid,p,b,coupled,trial=self.grid(-1);trial['requested']=.0001;self.assertFalse(m.audit(grid,p,b,0,coupled,trial)['passed'])
    def test_motion_wrong_initial_frame_is_not_rebound(self):
        m,grid,p,b,coupled,trial=self.grid();grid[0]['slider'][11]+=.001
        with self.assertRaisesRegex(Exception,'机械起点'):m.audit(grid,p,b,0,coupled,trial)
    def test_native_face_direction_switch_is_explicit(self):
        from sw_mcp.conversation.coupled_motion import choose
        goal={'component_a':'slider','component_b':'rail','axis_global':[0,0,1]};face={'component_id':'slider','kind':'planar_normal','axis_global':[0,0,-1],'entity_id':'face'}
        r=choose(goal,[face]);self.assertTrue(r['positive_trial_reverse']);self.assertFalse(r['temporary_distance_or_angle_mate_added'])
    def test_nonparallel_or_missing_native_face_refuses(self):
        from sw_mcp.conversation.coupled_motion import choose
        with self.assertRaises(Exception):choose({'component_a':'slider','component_b':'rail','axis_global':[0,0,1]},[{'component_id':'slider','kind':'planar_normal','axis_global':[1,0,0],'entity_id':'face'}])
    def test_incomplete_or_duplicate_csv_is_not_a_success(self):
        m,grid,p,b,coupled,trial=self.grid()
        with tempfile.TemporaryDirectory() as temp:
            path=pathlib.Path(temp)/'poses.csv';columns=['frame','component_id','time_s','x_m','y_m','z_m']+['r'+str(i)+str(k) for i in range(3) for k in range(3)]
            with path.open('w',newline='',encoding='utf8') as f:
                w=csv.DictWriter(f,columns);w.writeheader()
                for i,frame in enumerate(grid):
                    for cid,v in frame.items():
                        w.writerow(dict(frame=i,component_id=cid,time_s=i/30,x_m=v[9],y_m=v[10],z_m=v[11],**{columns[6+k]:v[k] for k in range(9)}))
            self.assertEqual(len(m.samples(path,p)),31)
            lines=path.read_text().splitlines();path.write_text('\n'.join(lines[:-1])+'\n')
            with self.assertRaisesRegex(ValueError,'incomplete'):m.samples(path,p)
            path.write_text('\n'.join(lines+[lines[-1]])+'\n')
            with self.assertRaisesRegex(ValueError,'invalid'):m.samples(path,p)
    def rejected_run(self,unknown):
        from sw_mcp.conversation import core
        m,grid,p,b,coupled,trial=self.grid();calls=[]
        with tempfile.TemporaryDirectory() as temp:
            s=SimpleNamespace(model='owned',result_checkpoint='saved',unknown=False,folder=pathlib.Path(temp),state=lambda *args,**kwargs:None)
            goal={**b[0],'coupled_motion_driver':{'drive':{'entity_id':'real_face'},'positive_trial_reverse':False,'speed_mm_s':.1,'translation_step_m':.0001}}
            def call(name,**kwargs):
                calls.append(name)
                if name=='_connection_reference_state':return {'mate_parameters_signature':'guarded','native_mate_count':9,'fixed_states':{'rail':True},'study_states':[]}
                if name=='inspect_model':return {'components':[{'component_id':cid,'transform':pose} for cid,pose in p.items()]}
                if name=='create_motion_study':return {}
                if name=='verify_motion_preservation':
                    if unknown:s.unknown=True;raise core.StopBatch('CONNECTION_NATIVE_UNKNOWN')
                    return {'assertion':'inconclusive','restoration_status':'restored','source_files_unchanged':True}
                if name=='restore_model_checkpoint':return {'restoration_status':'restored','source_files_unchanged':True,'maximum_transform_delta':0}
                raise AssertionError(name)
            s.call=call
            with self.assertRaises(core.StopBatch) as caught:m.run(s,goal,trial,p,b,0,coupled)
            self.assertEqual(caught.exception.code,'CONNECTION_NATIVE_UNKNOWN' if unknown else 'CONNECTION_EVIDENCE_FAILED')
        self.assertEqual(calls.count('create_motion_study'),1);self.assertEqual(calls.count('verify_motion_preservation'),1)
        self.assertEqual(calls.count('restore_model_checkpoint'),0 if unknown else 1)
    def test_known_native_failure_restores_once_without_retry(self):self.rejected_run(False)
    def test_unknown_native_state_never_retries_or_restores(self):self.rejected_run(True)
