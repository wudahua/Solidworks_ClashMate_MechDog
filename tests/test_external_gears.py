"""Two-axis recommendations and independent non-unit ratio counterexamples; no CAD."""
import copy,csv,json,math,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from sw_mcp.conversation import core,external_gears as eg,external_gear_task as task
from sw_mcp.conversation.motion_tasks import MotionTaskEngine,prepare_inputs
from test_conversation_tasks import FakeSession

ROOT=Path(__file__).resolve().parents[1]


def cylinder(cid,x,r=.003):
    return {'component_id':cid,'axis_global':[0,0,1],'reference_point_global_m':[x,0,0],
            'cylinder_radius_m':r,'area_m2':.001,'native_reference':cid+'-face','entity_id':cid+'-axis','fixed_component':cid=='body'}


def survey(teeth=(20,40)):
    components=[];design={}
    def add(cid,name,box,x,fixed,gear=False):
        c={'component_id':cid,'instance':name,'box':box,'fixed_component':fixed,'cylinders':[cylinder(cid,x)],
           'source_configuration_matches':True,'design_key':cid,'transform':[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0]}
        components.append(c);design[cid]={'properties':[],'patterns':[],'features':[],'issues':[]}
        return c
    body=add('body','frame',[-.02,-.02,-.01,.08,.02,.01],0,True);body['cylinders'].append(cylinder('body',.045))
    for side,x,z in [('input',0,teeth[0]),('output',.045,teeth[1])]:
        add(side+'_shaft','rotorA' if side=='input' else 'rotorB',[x-.003,-.003,-.05,x+.003,.003,.05],x,side!='input')
        add(side+'_gear','discA' if side=='input' else 'discB',[x-.015,-.015,-.005,x+.015,.015,.005],x,True,True)
        design[side+'_gear']['properties']=[{'name':'齿数','scope':'','raw':str(z),'resolved':str(z),'was_resolved':True}]
        key=add(side+'_key','联接键甲' if side=='input' else '联接键乙',[x+.002,-.001,-.01,x+.004,.001,.01],x,True)
        key['cylinders']=[]
    return {'model_id':'user_'+'a'*32,'reference_state_signature':'native-signature','inventory_complete':True,
            'components':components,'design_evidence':design,'mates':[],'skipped':[]}


class RecommendationTests(unittest.TestCase):
    def test_arbitrary_names_and_component_count_with_design_ratio_and_auto_keys(self):
        value=eg.recommend(survey());self.assertEqual(len(value['proposals']),1)
        p=value['proposals'][0];self.assertEqual(p['roles']['input_shaft'],'input_shaft')
        self.assertEqual(set(p['groups']['input']),{'input_shaft','input_gear','input_key'})
        self.assertEqual(p['supports']['output']['component_id'],'body')
        self.assertEqual(p['gear_ratio']['expected_output_over_input'],-.5)
        self.assertEqual(p['gear_ratio']['source'],'design_tooth_counts');self.assertFalse(p['write_dispatched'])

    def test_natural_language_shaft_hint_can_reverse_recommended_input(self):
        p=eg.recommend(survey(),moving_hint='rotorB')['proposals'][0]
        self.assertEqual(p['roles']['input_shaft'],'output_shaft')
        self.assertEqual(p['gear_ratio']['expected_output_over_input'],-2)

    def test_missing_parameters_never_promote_bore_or_outside_diameter_to_pitch(self):
        s=survey()
        for c in s['components']:
            if c['component_id'].endswith('gear'):
                c['instance']='gear-'+c['component_id'];s['design_evidence'][c['design_key']]['properties']=[]
        p=eg.recommend(s)['proposals'][0]['gear_ratio']
        self.assertIsNone(p['numerator']);self.assertFalse(p['hole_and_outside_diameters_used_as_pitch_diameters'])
        self.assertIn('question',p)

    def test_same_part_configuration_recommends_one_to_one_without_claiming_teeth(self):
        s=survey()
        for c in s['components']:
            if c['component_id'].endswith('gear'):c.update(instance='gear-'+c['component_id'],design_key='shared')
        s['design_evidence']['shared']={'properties':[],'patterns':[]}
        ratio=eg.recommend(s)['proposals'][0]['gear_ratio'];self.assertEqual(ratio['numerator'],1)
        self.assertEqual(ratio['source'],'same_part_and_configuration')

    def test_circle_pattern_is_only_a_trial_suggestion_not_proven_tooth_count(self):
        s=survey()
        for c,n in [(c,20 if c['component_id'].startswith('input') else 40) for c in s['components'] if c['component_id'].endswith('gear')]:
            c['instance']='gear-'+c['component_id'];s['design_evidence'][c['design_key']]={'properties':[],
                'patterns':[{'feature':'CirPattern1','total_instances':n,'equal_spacing':True,'spacing_rad':2*math.pi}]}
        ratio=eg.recommend(s)['proposals'][0]['gear_ratio']
        self.assertEqual(ratio['confidence'],'mechanical_review_required');self.assertIn('not_proven',ratio['source'])

    def test_contradictory_teeth_are_not_silently_ranked(self):
        s=survey();s['design_evidence']['input_gear']['properties'].append({'name':'ToothCount','scope':'','raw':'30','resolved':'30','was_resolved':True})
        with self.assertRaises(core.StopBatch) as error:eg.recommend(s)
        self.assertEqual(error.exception.diagnostics['pair_issues'][0]['code'],'EXTERNAL_GEAR_RATIO_AMBIGUOUS')

    def test_configuration_parameter_overrides_document_parameter(self):
        p={'name':'齿数','scope':'','raw':'20','resolved':'20','was_resolved':True}
        found=eg.design_teeth({'properties':[p,{**p,'scope':'configurationA','raw':'32','resolved':'32'}]})
        self.assertEqual(found['teeth'],32)

    def test_unknown_floating_parts_are_not_silently_fixed(self):
        s=survey();extra=copy.deepcopy(s['components'][0]);extra.update(component_id='extra',fixed_component=False);s['components'].append(extra)
        with self.assertRaises(core.StopBatch) as error:eg.recommend(s)
        self.assertIn('unassigned_floating_components',error.exception.diagnostics['pair_issues'][0]['diagnostics'])

    def test_nonparallel_and_coincident_axes_do_not_form_external_pair(self):
        for change in ('angle','same_axis'):
            s=survey();c=next(c for c in s['components'] if c['component_id']=='output_gear')
            if change=='angle':c['cylinders'][0]['axis_global']=[1,0,0]
            else:c['cylinders'][0]['reference_point_global_m']=[0,0,0]
            with self.subTest(change=change),self.assertRaises(core.StopBatch):eg.recommend(s)

    def test_native_gear_ratio_has_provenance_and_respects_reference_order(self):
        s=survey();s['mates']=[{'type':10,'native_feature_id':12,'entities':[{'component_id':'output_gear'},{'component_id':'input_gear'}],
                              'gear_ratio':{'numerator':3,'denominator':1}}]
        p=eg.recommend(s)['proposals'][0]['gear_ratio'];self.assertAlmostEqual(p['expected_output_over_input'],-1/3)
        self.assertEqual(p['source'],'existing_native_gear_mate')

    def test_declared_trial_weights_never_claim_measured_teeth(self):
        s=survey()
        for name in ('input_gear','output_gear'):s['design_evidence'][name]['properties'][0]['name']='ClashMateTrialTeeth'
        ratio=eg.recommend(s)['proposals'][0]['gear_ratio']
        self.assertEqual(ratio['source'],'declared_trial_ratio_weights_not_tooth_measurement')

    def test_native_gear_mate_can_reference_shafts_in_the_same_rotor_groups(self):
        s=survey();s['mates']=[{'type':10,'native_feature_id':18,'entities':[{'component_id':'input_shaft'},{'component_id':'output_shaft'}],
                              'gear_ratio':{'numerator':1,'denominator':3}}]
        ratio=eg.recommend(s)['proposals'][0]['gear_ratio']
        self.assertAlmostEqual(ratio['expected_output_over_input'],-1/3);self.assertEqual(ratio['source'],'existing_native_gear_mate')

    def test_integral_gear_or_gear_without_separate_shaft_uses_its_own_axis(self):
        s=survey();s['components']=[c for c in s['components'] if c['component_id'] not in {'input_shaft','input_key'}]
        p=eg.recommend(s)['proposals'][0]
        self.assertEqual(p['roles']['input_shaft'],'input_gear');self.assertEqual(p['groups']['input'],['input_gear'])

    def test_suppressed_gear_definition_cannot_override_live_design_ratio(self):
        s=survey();s['mates']=[{'type':10,'suppressed':True,'native_feature_id':19,
            'entities':[{'component_id':'input_gear'},{'component_id':'output_gear'}],
            'gear_ratio':{'numerator':3,'denominator':1}}]
        ratio=eg.recommend(s)['proposals'][0]['gear_ratio']
        self.assertEqual(ratio['expected_output_over_input'],-.5);self.assertEqual(ratio['source'],'design_tooth_counts')

    def test_public_recommendation_keeps_native_references_in_owner_evidence(self):
        raw=eg.recommend(survey())['proposals'][0];public=eg.public_card(raw)
        self.assertNotIn('"native_reference":',json.dumps(public));self.assertIn('native_reference',raw['shaft_axes']['input'])
        self.assertNotIn(raw['shaft_axes']['input']['native_reference'],json.dumps(public))
        self.assertEqual(public['gear_ratio'],raw['gear_ratio'])

    def test_explicit_shaft_hint_cannot_silently_fall_back_to_gear(self):
        with self.assertRaises(core.StopBatch) as error:eg.recommend(survey(),role_hints={'input_shaft':'missing-shaft'})
        self.assertIn('指定轴名称',error.exception.diagnostics['pair_issues'][0]['message'])


def pose_fixture(folder,ratio=.5,keys=True):
    groups={side:[side+'_shaft',side+'_gear']+([side+'_key'] if keys else []) for side in ('input','output')}
    roles={r:r for r in ('input_shaft','output_shaft','input_gear','output_gear','body')};ids=['body',*groups['input'],*groups['output']]
    initial=[];rows=[];axes={'shaft_axes':{},'support_axes':{}}
    for side,x in [('input',0),('output',.045)]:
        axes['shaft_axes'][side]=cylinder(side+'_shaft',x);axes['support_axes'][side]=cylinder('body',x)
    for f in range(31):
        for cid in ids:
            side=cid.split('_')[0];center=[.045 if side=='output' else 0,0,0];a=math.radians(2.4*f)*(1 if side=='input' else -ratio if side=='output' else 0)
            c,s=math.cos(a),math.sin(a);matrix=[c,s,0,-s,c,0,0,0,1];offset=[.02,0,0] if cid.endswith('shaft') else [.004,0,.01] if cid.endswith('key') else [0,0,.02] if cid.endswith('gear') else [0,0,0]
            origin=[center[0]+c*offset[0]-s*offset[1],center[1]+s*offset[0]+c*offset[1],center[2]+offset[2]]
            row={'frame':f,'time_s':f/30,'component_id':cid,'instance':cid,**dict(zip(['x_m','y_m','z_m'],origin)),**dict(zip(['r'+str(i)+str(j) for i in range(3) for j in range(3)],matrix))};rows.append(row)
            if f==0:initial.append({'component_id':cid,'instance':cid,'transform':matrix+origin+[1,0,0,0],'fixed_component':cid=='body'})
    p={'duration_s':1,'output_fps':30,'reverse_direction':False,'speed':12};path=folder/'poses.csv'
    def save():
        with path.open('w',encoding='utf8',newline='') as out:
            w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    save();return path,roles,groups,[0,0,1],p,initial,axes,ratio,rows,save


class MotionEvidenceTests(unittest.TestCase):
    def setUp(self):self.folder=ROOT/'runs/external-gear-unit'/uuid.uuid4().hex[:8];self.folder.mkdir(parents=True)
    def test_non_unit_ratio_and_variable_rotor_members_pass(self):
        for ratio in (.5,2,1.5):
            for keys in (True,False):
                case=pose_fixture(self.folder,ratio,keys);v=task.audit(*case[:8])
                self.assertTrue(v['passed']);self.assertAlmostEqual(v['signed_final_degrees']['output_shaft'],-72*ratio)
    def test_rotating_gear_with_stationary_shaft_fails_even_with_good_gear_ratio(self):
        case=pose_fixture(self.folder,.5,keys=False)
        start=next(r.copy() for r in case[8] if r['component_id']=='output_shaft' and r['frame']==0)
        for row in case[8]:
            if row['component_id']=='output_shaft':
                row.update({k:v for k,v in start.items() if k not in {'frame','time_s'}})
        case[9]()
        with self.assertRaises(core.StopBatch) as error:task.audit(*case[:8])
        self.assertGreater(error.exception.diagnostics['rotor_relative_angle_errors_deg']['output'],35)
    def test_constrained_unfixed_support_requires_observed_stationary_trajectory(self):
        case=pose_fixture(self.folder,.5);axes=case[6]
        for side in ('input','output'):axes['support_axes'][side]['fixed_component']=False
        with self.assertRaises(core.StopBatch):task.audit(*case[:8])
        axes['constraint_completion']=True
        proof=task.audit(*case[:8]);self.assertTrue(proof['passed'])
        for evidence in proof['support_stationarity_evidence'].values():
            self.assertEqual(evidence['admission'],'observed_stationary_full_sampled_trajectory')
            self.assertEqual(evidence['checked_frames'],31);self.assertTrue(evidence['fixed_flag_not_overridden'])
        self.assertFalse(axes['support_axes']['input']['fixed_component'])

    def test_unfixed_support_with_actual_motion_is_never_admitted(self):
        case=pose_fixture(self.folder,.5);axes=case[6];axes['constraint_completion']=True
        for side in ('input','output'):axes['support_axes'][side]['fixed_component']=False
        for row in case[8]:
            if row['component_id']=='body' and row['frame']==30:row['x_m']+=.0001
        case[9]()
        with self.assertRaises(core.StopBatch) as error:task.audit(*case[:8])
        self.assertEqual(error.exception.diagnostics['cause'],'REFERENCE_NOT_STATIONARY_IN_SAMPLED_TRAJECTORY')

    def test_wrong_ratio_key_slip_fixed_motion_and_axial_drift_fail(self):
        for fault in ('ratio','key','fixed','axial'):
            case=pose_fixture(self.folder,.5)
            if fault=='ratio':case=list(case);case[7]=1
            else:
                for r in case[8]:
                    if r['frame']==30 and (fault=='key' and r['component_id']=='input_key' or fault=='fixed' and r['component_id']=='body' or fault=='axial' and r['component_id'].startswith('output_')):r['z_m']+=.00001
                case[9]()
            with self.subTest(fault=fault),self.assertRaises(core.StopBatch):task.audit(*case[:8])


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'runs/external-gear-unit'/uuid.uuid4().hex[:8];self.source=self.folder/'fixture.SLDASM';self.source.parent.mkdir(parents=True);self.source.write_bytes(b'fixture only')
        raw=survey();raw['model_id']='fixture-model'
        class Session(FakeSession):
            def discover(s,path):
                super().discover(path);s.external_survey=copy.deepcopy(raw);s.external_recommendation=eg.recommend(raw);s.moving_hint='';s.reference_hint='';s.calls=[]
                return {'external_gear_pair':s.external_recommendation}
            def call(s,operation,**args):
                s.calls.append((operation,args))
                if operation=='_preview_external_gear_pair':
                    r=json.loads(args['recommendation_json']);return {'plan_id':'native-plan','roles':r['roles'],'groups':r['groups'],'expected_mate_count':9,
                        'gear_ratio':{'numerator':args['numerator'],'denominator':args['denominator']}}
                if operation=='_apply_external_gear_pair':raise core.StopBatch('GEAR_APPLY_ROLLED_BACK','fixture controlled rollback')
                raise AssertionError(operation)
            def state(s,*a,**kw):pass
        self.engine=MotionTaskEngine(self.folder,self.folder/'work',self.folder/'runtime',Session);self.addCleanup(self.engine.shutdown)
        with patch('sw_mcp.conversation.startup_gate.require_idle'):
            self.tid=self.engine.prepare(str(self.source),task_kind='external_gear_pair')['task_id']
        self.assertEqual(self.wait()['phase'],'proposal_ready')
    def wait(self):
        for _ in range(500):
            value=self.engine.get(self.tid)
            if not value['busy']:return value
            time.sleep(.005)
        self.fail('fixture timeout')
    def test_plan_recommends_ratio_and_confirmation_stays_exactly_once(self):
        self.engine.plan(self.tid);planned=self.wait();self.assertEqual(planned['phase'],'awaiting_confirmation')
        self.assertEqual(planned['proposal']['gear_ratio'],{'numerator':20,'denominator':40})
        with self.assertRaises(core.StopBatch):self.engine.execute(self.tid,planned['plan_token'],True,False)
        self.assertNotIn('execution_consumed',self.engine.get(self.tid))
        self.engine.execute(self.tid,planned['plan_token'],True,True);failed=self.wait()
        self.assertEqual(failed['error']['code'],'GEAR_APPLY_ROLLED_BACK')
        with self.assertRaises(core.StopBatch):self.engine.execute(self.tid,planned['plan_token'],True,True)
        self.assertEqual(sum(op=='_apply_external_gear_pair' for op,a in self.engine.sessions[self.tid].calls),1)
    def test_alias_sensitive_speed_recommendation_is_explicit_in_plan(self):
        self.engine.plan(self.tid,gear_ratio_numerator=1000,gear_ratio_denominator=6);p=self.wait()['proposal']
        self.assertTrue(p['motion']['speed_recommendation_changed']);self.assertEqual(p['motion']['requested_speed_rpm'],12)
        self.assertAlmostEqual(p['motion']['speed'],1.2);self.assertEqual(p['ratio_provenance']['source'],'explicit_plan_ratio_override')
    def test_wrong_token_readback_uses_original_plan_once_without_replanning(self):
        self.engine.plan(self.tid);planned=self.wait();token=planned['plan_token']
        with self.assertRaises(core.StopBatch) as error:self.engine.execute(self.tid,'wrong',True,True)
        self.assertEqual(error.exception.code,'PLAN_TOKEN_MISMATCH')
        self.assertTrue(error.exception.diagnostics['current_plan_still_valid'])
        current=self.engine.get(self.tid)
        self.assertEqual(current['phase'],'awaiting_confirmation');self.assertEqual(current['plan_token'],token)
        self.assertNotIn('execution_consumed',current)
        self.assertEqual([op for op,a in self.engine.sessions[self.tid].calls],['_preview_external_gear_pair'])
        self.engine.execute(self.tid,current['plan_token'],True,True);self.wait()
        with self.assertRaises(core.StopBatch) as error:self.engine.execute(self.tid,'wrong',True,True)
        self.assertEqual(error.exception.code,'TASK_ALREADY_EXECUTED')
        self.assertEqual(sum(op=='_apply_external_gear_pair' for op,a in self.engine.sessions[self.tid].calls),1)
    def test_invalid_ratio_or_other_mode_does_not_queue_native_preview(self):
        for kwargs in ({'gear_ratio_numerator':-1},{'gear_ratio_numerator':20},{'gear_ratio_denominator':float('nan')},{'alignment_mode':'small_translation'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(core.StopBatch):self.engine.plan(self.tid,**kwargs)
        self.assertEqual(self.engine.sessions[self.tid].calls,[])
    def test_new_study_suppression_drift_blocks_solve_and_result_checkpoint(self):
        self.engine.plan(self.tid);planned=self.wait();proposal=planned['proposal'];session=self.engine.sessions[self.tid]
        case=pose_fixture(self.folder);components=case[5];operations=[]
        def call(operation,**args):
            operations.append(operation)
            if operation=='_apply_external_gear_pair':
                return {'roles':proposal['roles'],'groups':proposal['groups'],'native_parameters':{'verified':True,'reported_mate_count':1},
                    'drive':{'axis_global':[0,0,1],'entity_id':'drive'},'axis_global':[0,0,1],
                    'observed_mate_suppression':{'99':False}}
            if operation=='inspect_model':return {'components':components,'mates':[{'native_feature_id':99,'suppressed':True}]}
            if operation=='create_motion_study':return {'fixture':'activation_reapplied_an_old_suppression_track'}
            raise AssertionError('must not dispatch '+operation)
        session.call=call
        session.capture_applied_result=lambda: self.fail('must not freeze a constraint-drifted result')
        self.engine.execute(self.tid,planned['plan_token'],True,True);failed=self.wait()
        self.assertEqual(failed['error']['code'],'GEAR_PARAMETERS_UNVERIFIED')
        self.assertEqual(failed['error']['diagnostics']['stage'],'new_motion_study_constraint_mask')
        self.assertFalse(failed['error']['diagnostics']['solve_dispatched'])
        self.assertNotIn('run_user_study',operations)

    def test_motion_limits_remain_checked_before_native_start(self):
        for changes in ({'speed':61},{'minimum_travel':1},{'motion':'linear'}):
            with self.subTest(changes=changes),self.assertRaises(core.StopBatch):prepare_inputs(str(self.source),task_kind='external_gear_pair',**changes)


if __name__=='__main__':unittest.main(verbosity=2)
