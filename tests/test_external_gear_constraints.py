"""Constraint semantics and failure routing; fixtures are not CAD acceptance."""
import copy,uuid,time,json,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from sw_mcp.conversation import component_constraints as cc,external_gears as eg,external_gear_task as task,core
from sw_mcp.task_errors import task_failure
from test_external_gears import survey
from test_conversation_tasks import FakeSession
from sw_mcp.conversation.motion_tasks import MotionTaskEngine
from sw_mcp.bridge import Bridge
from unittest.mock import patch


class ConstraintTests(unittest.TestCase):
    def test_saved_initial_plan_exposes_copy_only_discard_and_grid_before_confirmation(self):
        folder=Path(__file__).resolve().parents[1]/'runs'/('saved-initial-'+uuid.uuid4().hex[:8]);folder.mkdir()
        raw=survey();recommendation=eg.recommend(raw)
        studies=[{'name':'historical','time_s':.5,'fps':2500,'duration_s':.5,'type':4}]
        core.write(folder/'导入.json',{'checkpoint':{'studies':studies}})
        preparation={'required':True,'starting_pose':'saved_imported_assembly_pose',
                     'nonzero_copy_studies_to_remove':studies,'old_study_frame_zero_verified':False,
                     'source_and_import_checkpoint_preserved':True,'public_checkpoint_or_reset_tools_required':False}
        def native(operation,**args):
            self.assertEqual(operation,'_preview_external_gear_pair')
            return {'plan_id':'read-only','initial_state_preparation':preparation}
        session=SimpleNamespace(folder=folder,model=raw['model_id'],external_survey=raw,external_recommendation=recommendation,call=Mock(side_effect=native))
        state={'task_id':'a'*32,'phase':'proposal_ready','motion_parameters':{'speed':60,'duration_s':2,'output_fps':30,'reverse_direction':False,'signed_target_travel_deg':720}}
        def submit(t,phase,operation):operation();return t
        engine=SimpleNamespace(sessions={state['task_id']:session},_require_session=Mock(),_submit=submit)
        task.propose(engine,state,'','saved','strict','','',0,0,{},None,None)
        self.assertEqual(state['phase'],'awaiting_confirmation')
        self.assertEqual(state['proposal']['initial_state_preparation'],preparation)
        motion=state['proposal']['motion'];self.assertEqual(motion['output_fps'],50)
        self.assertEqual(motion['native_grid_recommendation']['requested_output_fps'],30)
        self.assertFalse(motion['native_grid_recommendation']['interpolation_allowed'])
        self.assertIn('不是重算历史零时刻',state['next_action']['instruction'])
        self.assertNotIn('execution_consumed',state)
        self.assertEqual([c.args[0] for c in session.call.call_args_list],['_preview_external_gear_pair'])
        self.assertEqual(core.read(folder/'导入.json')['checkpoint']['studies'],studies)

    def test_study_zero_refusal_explains_saved_pose_alternative_without_dispatch(self):
        t={'task_id':'b'*32,'phase':'proposal_ready'}
        engine=SimpleNamespace(_require_session=Mock(),_submit=Mock())
        with self.assertRaises(core.StopBatch) as error:
            task.propose(engine,t,'candidate-1','study_zero','strict','rotor','body',2,3,{'input_shaft':'rotorA'},['附件甲'])
        e=error.exception;self.assertEqual(e.code,'EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE')
        self.assertFalse(e.diagnostics['old_study_frame_zero_supported_in_this_task'])
        arguments=e.diagnostics['next_action']['arguments']
        self.assertEqual(arguments['task_id'],t['task_id']);self.assertEqual(arguments['initial_state'],'saved')
        self.assertEqual(arguments['candidate_id'],'candidate-1');self.assertEqual(arguments['input_shaft_hint'],'rotorA')
        self.assertEqual(arguments['stationary_component_hints'],['附件甲'])
        self.assertEqual((arguments['gear_ratio_numerator'],arguments['gear_ratio_denominator']),(2,3))
        self.assertIn('保留本次角色',e.diagnostics['next_action']['instruction'])
        engine._submit.assert_not_called();self.assertEqual(t['phase'],'proposal_ready')
        envelope=task_failure(e.code,str(e),e.diagnostics,task_id=t['task_id'])
        self.assertEqual(envelope['next_action']['tool'],'plan_mechanism_task')
        self.assertEqual(envelope['next_action']['options_status'],'initial_state_selection_required')
        self.assertEqual(envelope['next_action']['arguments'],arguments)
        self.assertTrue(envelope['next_action']['initial_state_change_is_not_execution_authorization'])
        self.assertFalse(envelope['next_action']['automatic_retry'])

    def test_impossible_known_grid_fails_before_native_plan_not_rounded_or_defaulted(self):
        folder=Path(__file__).resolve().parents[1]/'runs'/('saved-grid-'+uuid.uuid4().hex[:8]);folder.mkdir()
        core.write(folder/'导入.json',{'checkpoint':{'studies':[{'fps':2503,'type':4}]}})
        with self.assertRaises(core.StopBatch) as error:
            task.motion_settings({'motion_parameters':{'duration_s':2,'output_fps':30}},SimpleNamespace(folder=folder),80)
        self.assertEqual(error.exception.code,'EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE')

    def test_gear_import_keeps_long_operation_budget_without_native_dispatch(self):
        root=Path(__file__).resolve().parents[1]/'runs'/('gear-budget-'+uuid.uuid4().hex[:8]);root.mkdir()
        bridge=Bridge(root,timeout=5,motion_scan_timeout=600);self.addCleanup(bridge.close)
        self.assertEqual(bridge._wait_budget('_import_gear_assembly',{}),600)
        self.assertIsNone(bridge._process)

    def test_floating_fully_constrained_is_neither_free_nor_motion_certified(self):
        s=survey();c=s['components'][0];c['fixed_component']=False
        c['constraint_state']={'status':'observed','native_value':3,'fully_constrained':True}
        inv=cc.inventory(s['components'],[])
        self.assertEqual(inv['components'][0]['category'],'native_fully_constrained_not_fixed')
        self.assertIsNone(inv['components'][0]['remaining_DOF'])
        self.assertFalse(inv['components'][0]['stationary_during_motion_verified'])
        self.assertFalse(inv['automatic_fix_or_lock_performed'])

    def test_unavailable_unknown_and_underconstrained_are_not_promoted(self):
        for state in ({},{'status':'unavailable','native_value':3,'fully_constrained':True},
                      {'status':'observed','native_value':2,'fully_constrained':False},
                      {'status':'observed','native_value':3,'fully_constrained':False}):
            s=survey();c=s['components'][0];c.update(fixed_component=False,constraint_state=state)
            self.assertEqual(cc.inventory(s['components'],[])['components'][0]['category'],'unassigned_constraint_review_required')

    def test_rotor_roles_outrank_native_fixed_and_full_constraints(self):
        s=survey();inv=cc.inventory(s['components'],[],{'output':['output_gear']})
        c=next(c for c in inv['components'] if c['component_id']=='output_gear')
        self.assertEqual(c['category'],'recommended_output_rotor')

    def test_mate_links_keep_native_evidence_but_do_not_prove_stationarity(self):
        s=survey();mates=[{'native_feature_id':8,'name':'link','type':1,'entities':[{'component_id':'body'},{'component_id':'input_shaft'}]},
                          {'native_feature_id':9,'suppressed':True,'entities':[{'component_id':'input_shaft'}]}]
        c=next(c for c in cc.inventory(s['components'],mates)['components'] if c['component_id']=='input_shaft')
        self.assertEqual(len(c['mate_links']),1);self.assertEqual(c['mate_links'][0]['peers'],['body'])
        self.assertEqual(c['category'],'unassigned_constraint_review_required')

    def test_scope_root_is_not_masked_as_name_selection_and_unknowns_still_block(self):
        s=survey();extra=copy.deepcopy(s['components'][0]);extra.update(component_id='extra',instance='extra',fixed_component=False)
        extra['constraint_state']={'status':'observed','native_value':3,'fully_constrained':True};s['components'].append(extra)
        with self.assertRaises(core.StopBatch) as found:eg.recommend(s)
        e=found.exception;self.assertEqual(e.code,'EXTERNAL_GEAR_SCOPE_UNSUPPORTED')
        self.assertFalse(e.diagnostics['name_clarification_can_resolve'])
        self.assertEqual(e.diagnostics['constraint_inventory']['native_fully_constrained_not_fixed_count'],1)
        self.assertIn('extra',e.diagnostics['unassigned_floating_components'])
        self.assertNotEqual(task_failure(e.code,str(e),e.diagnostics)['next_action']['options_status'],'mechanical_selection_required')

    def test_declared_stationary_parts_are_planned_separately_from_rotors_without_write(self):
        s=survey();extra=copy.deepcopy(s['components'][0]);extra.update(component_id='extra',instance='附件甲',fixed_component=False)
        s['components'].append(extra)
        p=eg.recommend(s,stationary_hints=['附件甲'])['proposals'][0]
        self.assertEqual(p['stationary_components'],['extra']);self.assertFalse(p['write_dispatched'])
        self.assertFalse(extra['fixed_component']);self.assertNotIn('extra',p['groups']['input']+p['groups']['output'])

    def test_stationary_names_are_exact_and_cannot_capture_a_rotor(self):
        for hint in ('rotor','rotorA'):
            with self.assertRaises(core.StopBatch):eg.recommend(survey(),stationary_hints=[hint])
        for wrong in (False,True,1,'frame',{},[False],['']):
            with self.subTest(wrong=wrong),self.assertRaises(core.StopBatch):eg.recommend(survey(),stationary_hints=wrong)

    def test_explicit_stationary_support_can_be_proposed_but_is_not_fixed_yet(self):
        s=survey();s['components'][0]['fixed_component']=False
        p=eg.recommend(s,stationary_hints=['frame'])['proposals'][0]
        self.assertEqual(p['roles']['body'],'body');self.assertEqual(p['stationary_components'],['body'])
        self.assertFalse(s['components'][0]['fixed_component'])

    def test_unfixed_support_geometry_requests_scope_review_instead_of_more_name_hints(self):
        s=survey();s['components'][0]['fixed_component']=False
        with self.assertRaises(core.StopBatch) as e:eg.recommend(s)
        self.assertEqual(e.exception.code,'EXTERNAL_GEAR_SCOPE_UNSUPPORTED')
        self.assertIn('frame',e.exception.diagnostics['support_geometry_candidates'])

    def test_all_fixed_can_prepare_but_any_real_health_error_blocks(self):
        cc.require_import_health({'native_rebuild_succeeded':True,'feature_diagnostics':[],'blockers':['ALL_COMPONENTS_FIXED']},'saved.json')
        for p in (None,{'native_rebuild_succeeded':False,'blockers':[]},
                  {'native_rebuild_succeeded':True,'feature_diagnostics':[{'native_error':1}],'blockers':[]},
                  {'native_rebuild_succeeded':True,'blockers':['UNRESOLVED_COMPONENT shaft']}):
            with self.assertRaises(core.StopBatch) as error:cc.require_import_health(p,'saved.json')
            self.assertEqual(error.exception.code,'MODEL_PREFLIGHT_FAILED')

    def test_failed_import_preflight_stops_before_geometry_survey_and_keeps_finishable_model(self):
        if True:
            d=Path(__file__).resolve().parents[1]/"runs"/("constraint-unit-"+uuid.uuid4().hex[:8]);d.mkdir()
            s=SimpleNamespace(model='registered',folder=Path(d),moving_hint='',reference_hint='',
                import_preflight={'native_rebuild_succeeded':False,'blockers':['REBUILD_FAILED']},
                call=Mock(return_value={'components':survey()['components'],'mates':[]}),state=Mock())
            with self.assertRaises(core.StopBatch):task.discover(s)
            self.assertEqual(s.call.call_count,1);self.assertEqual(s.model,'registered')
            self.assertTrue((Path(d)/'组件约束分类.json').is_file())

    def test_scope_review_plan_and_confirmation_are_separate_and_reuse_one_session(self):
        raw=survey();extra=copy.deepcopy(raw['components'][0]);extra.update(component_id='extra',instance='附件甲',fixed_component=False)
        raw['components'].append(extra)
        class Session(FakeSession):
            def discover(s,path):
                super().discover(path);s.import_preflight={'native_rebuild_succeeded':True,'blockers':[]};s.moving_hint=s.reference_hint='';s.calls=[]
                return task.discover(s)
            def state(s,*a,**kw):pass
            def call(s,operation,**args):
                s.calls.append(operation)
                if operation=='inspect_model':return {'components':raw['components'],'mates':[]}
                if operation=='_survey_external_gear_pair':return raw
                if operation=='_preview_external_gear_pair':
                    rec=json.loads(args['recommendation_json'])
                    return {'plan_id':'fixture','roles':rec['roles'],'groups':rec['groups'],'actions':[{'kind':'fix_declared_stationary','component_a':'extra'}]}
                raise AssertionError(operation)
        d=Path(__file__).resolve().parents[1]/'runs'/('scope-unit-'+uuid.uuid4().hex[:8]);d.mkdir();source=d/'fixture.SLDASM';source.write_bytes(b'not CAD')
        engine=MotionTaskEngine(d,d/'work',d/'runtime',Session);self.addCleanup(engine.shutdown)
        with patch('sw_mcp.conversation.startup_gate.require_idle'):
            tid=engine.prepare(str(source),task_kind='external_gear_pair')['task_id']
        def wait():
            for _ in range(400):
                value=engine.get(tid)
                if not value['busy']:return value
                time.sleep(.005)
            self.fail('fixture timeout')
        prepared=wait();self.assertEqual(prepared['phase'],'scope_review_required')
        self.assertIn('assembly_intent',prepared['next_action']['instruction'])
        self.assertIn('完整stationary/input/output',prepared['next_action']['instruction'])
        with self.assertRaises(core.StopBatch):engine.plan(tid)
        engine.plan(tid,stationary_component_hints=['附件甲']);planned=wait()
        self.assertEqual(planned['phase'],'awaiting_confirmation')
        self.assertFalse(planned['requires_stationary_scope_review']);self.assertNotIn('blocking_code',planned)
        self.assertEqual(planned['proposal']['recommendation']['stationary_scope'][0]['instance'],'附件甲')
        with self.assertRaises(core.StopBatch):engine.execute(tid,planned['plan_token'],False,True)
        self.assertEqual(engine.sessions[tid].calls.count('_survey_external_gear_pair'),1)
        self.assertNotIn('_apply_external_gear_pair',engine.sessions[tid].calls)


if __name__=='__main__':unittest.main()
