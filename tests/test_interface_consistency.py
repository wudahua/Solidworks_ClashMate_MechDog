"""Task-card frame policy and mechanical intent diagnostics; no real CAD."""
import asyncio,copy,json,time,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from sw_mcp import assembly_completion as ac
from sw_mcp.conversation import core,external_gear_task as gears
from sw_mcp.conversation.motion_tasks import prepare_inputs,validate_prepare_arguments,prepare_limits
from sw_mcp.native_grid import GridAdmissionError
from transport_cleanup import remove_test_root

ROOT=Path(__file__).resolve().parents[1]


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.base=ROOT/'runs/interface-consistency-tests';self.folder=self.base/uuid.uuid4().hex[:8];self.folder.mkdir(parents=True)
        self.addCleanup(remove_test_root,self.folder,self.base)
        self.source=self.folder/'fixture.SLDASM';self.source.write_bytes(b'not a CAD model; never dispatched')

    def test_external_accepts_aligned_integer_range_and_pump_card_stays_30_60(self):
        with patch('sw_mcp.conversation.startup_gate.require_idle') as gate:
            for fps in range(5,121):
                _,p=validate_prepare_arguments({'assembly_path':str(self.source),'task_kind':'external_gear_pair','speed':60,'duration_s':2,'output_fps':fps})
                self.assertEqual(p['output_fps'],fps);self.assertEqual(p['signed_target_travel_deg'],720)
                if fps in {30,60}:
                    prepare_inputs(self.source,'gear_transmission',duration_s=2,output_fps=fps)
                else:
                    with self.assertRaises(core.StopBatch) as caught:prepare_inputs(self.source,'gear_transmission',duration_s=2,output_fps=fps)
                    self.assertEqual(caught.exception.code,'GEAR_PARAMETERS_INVALID')
                    self.assertEqual(caught.exception.diagnostics['task_kind'],'gear_transmission')
            gate.assert_not_called()

    def test_external_speed_duration_motion_and_minimum_guards_remain(self):
        for changes in [{'speed':61},{'duration_s':2.1},{'motion':'linear'},{'minimum_travel':1}]:
            with self.subTest(changes=changes),self.assertRaises(core.StopBatch) as caught:
                prepare_inputs(self.source,'external_gear_pair',**changes)
            self.assertEqual(caught.exception.code,'GEAR_PARAMETERS_INVALID')
            self.assertEqual(caught.exception.diagnostics['limits'],prepare_limits()['external_gear_pair'])
            self.assertIn('external_gear_pair',str(caught.exception));self.assertFalse(caught.exception.diagnostics['cad_dispatched'])

    def test_frame_type_alignment_and_sparse_grid_guards_remain(self):
        for changes,code in [({'output_fps':121},'INVALID_MOTION_PARAMETERS'),({'output_fps':True},'INVALID_MOTION_PARAMETERS'),
                             ({'output_fps':50.0},'INVALID_MOTION_PARAMETERS'),({'duration_s':.1,'output_fps':50},'OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER'),
                             ({'duration_s':.5,'output_fps':31},'OUTPUT_GRID_NOT_FRAME_ALIGNED')]:
            with self.subTest(changes=changes),self.assertRaises((core.StopBatch,GridAdmissionError)) as caught:
                prepare_inputs(self.source,'external_gear_pair',**changes)
            self.assertEqual(caught.exception.code,code)

    def test_public_environment_distinguishes_low_level_and_managed_cards(self):
        import motion_server as ms
        original={'budget_matrix':{'new_solve':{'maximum_output_fps':120}},'version':core.VERSION};before=copy.deepcopy(original)
        with patch.object(ms.bridge,'request',return_value=original) as native:
            result=asyncio.run(ms.mcp.call_tool('get_environment',{}))
        self.assertFalse(result.is_error);value=result.structured_content['result']
        self.assertEqual(value['budget_matrix']['new_solve']['maximum_output_fps'],120)
        self.assertEqual(value['budget_matrix']['managed_tasks'],prepare_limits())
        self.assertIn('low_level_ceiling',value['budget_matrix_scope']);self.assertEqual(original,before)
        native.assert_called_once_with('get_environment')

    def inventory(self):
        cs=[{'component_id':str(i),'instance':('机体1-1' if i==0 else '零件-'+str(i)),'fixed_component':i==0} for i in range(80)]
        intent={'stationary':[c['instance'] for c in cs[:78]],'input':[cs[78]['instance']],'output':[cs[79]['instance']]}
        return cs,intent

    def test_missing_and_unknown_names_show_both_sides_of_difference(self):
        cs,intent=self.inventory();intent['stationary'].remove('机体1-1')
        with self.assertRaises(ac.IntentValidationError) as caught:ac.declared_groups(cs,intent)
        self.assertEqual(str(caught.exception),'intent_inventory_incomplete');self.assertEqual(caught.exception.diagnostics['missing'],['机体1-1'])
        self.assertEqual(caught.exception.diagnostics['unexpected'],[])
        intent['stationary'].append('机体l-1')
        with self.assertRaises(ac.IntentValidationError) as caught:ac.declared_groups(cs,intent)
        self.assertEqual(caught.exception.diagnostics['missing'],['机体1-1']);self.assertEqual(caught.exception.diagnostics['unexpected'],['机体l-1'])

    def test_ambiguous_names_and_duplicate_group_ownership_are_not_auto_resolved(self):
        cs,intent=self.inventory();intent['input'].append('零件-1')
        with self.assertRaises(ac.IntentValidationError) as caught:ac.declared_groups(cs,intent)
        overlap=caught.exception.diagnostics['overlaps'][0]
        self.assertEqual(overlap['instance'],'零件-1');self.assertEqual([v['group'] for v in overlap['occurrences']],['stationary','input'])
        cs,intent=self.inventory();cs[1]['instance']='机体1-1';intent['stationary'][1]='机体1-1'
        with self.assertRaises(ac.IntentValidationError) as caught:ac.declared_groups(cs,intent)
        self.assertEqual(len(caught.exception.diagnostics['ambiguous'][0]['matches']),2)

    def test_valid_casefold_exact_groups_preserve_native_ids_and_ground_guard(self):
        cs=[{'component_id':'a','instance':'BODY-1','fixed_component':True},{'component_id':'b','instance':'Rotor-1','fixed_component':False}]
        self.assertEqual(ac.declared_groups(cs,{'stationary':['body-1'],'rotor':['ROTOR-1']}),{'stationary':['a'],'rotor':['b']})
        cs[0]['fixed_component']=False
        with self.assertRaisesRegex(ValueError,'stationary_group_has_no_existing_ground'):ac.declared_groups(cs,{'stationary':['BODY-1'],'rotor':['Rotor-1']})

    def test_intent_refusal_reaches_public_envelope_without_queue_or_CAD(self):
        import motion_server as ms
        from sw_mcp.conversation.motion_tasks import MotionTaskEngine
        e=MotionTaskEngine(self.folder,self.folder/'work',self.folder/'runtime');self.addCleanup(e.shutdown)
        cs,intent=self.inventory();intent['stationary'].remove('机体1-1')
        tid='a'*32;task={'task_id':tid,'task_kind':'external_gear_pair','phase':'scope_review_required','busy':False,'closed':False};e.tasks[tid]=task;e.active=tid
        folder=self.folder/'session';folder.mkdir();native=Mock(side_effect=AssertionError('intent failure must not query CAD'))
        e.sessions[tid]=SimpleNamespace(folder=folder,model=None,external_survey={'components':cs},call=native)
        with patch.object(ms,'_task_engine',e),patch.object(e,'_submit',side_effect=AssertionError('must not queue')):
            response=asyncio.run(ms.mcp.call_tool('plan_mechanism_task',{'task_id':tid,'assembly_intent':intent}))
        self.assertTrue(response.is_error);wire=json.loads(response.content[0].text)
        self.assertEqual(wire['error']['code'],'EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE')
        self.assertIn('机体1-1',json.dumps(wire,ensure_ascii=False))
        d=core.read(folder/'机械分组校验失败.json');self.assertEqual(d['missing'],['机体1-1']);self.assertFalse(d['cad_dispatched'])
        self.assertEqual(task['phase'],'scope_review_required');self.assertNotIn('plan_token',task);native.assert_not_called()
        with patch.object(ms,'_task_engine',e),patch.object(e,'_submit',side_effect=AssertionError('must not queue')),patch.object(core,'write',side_effect=PermissionError('fixture evidence write denied')):
            response=asyncio.run(ms.mcp.call_tool('plan_mechanism_task',{'task_id':tid,'assembly_intent':intent}))
        self.assertEqual(response.structured_content['error']['code'],'EXTERNAL_GEAR_OPTIONS_NOT_APPLICABLE')
        self.assertIn('机体1-1',response.content[0].text);self.assertIn('write_failed',response.content[0].text)
        native.assert_not_called()

    def test_plan_still_requires_exact_native_subset_and_pose_budget(self):
        s=SimpleNamespace(folder=self.folder)
        core.write(self.folder/'导入.json',{'checkpoint':{'studies':[{'type':4,'fps':2500}]}})
        base={'motion_parameters':prepare_inputs(self.source,'external_gear_pair',duration_s=2,output_fps=50)[1]}
        result=gears.motion_settings(base,s,80)
        self.assertEqual(result['output_fps'],50);self.assertTrue(result['native_grid_recommendation']['requires_plan_confirmation'])
        self.assertFalse(result['native_grid_recommendation']['interpolation_allowed'])
        base['motion_parameters']['output_fps']=120
        with self.assertRaises(core.StopBatch):gears.motion_settings(base,s,80)
        (self.folder/'导入.json').unlink()
        with self.assertRaises(core.StopBatch) as caught:gears.motion_settings(base,s,500)
        self.assertEqual(caught.exception.diagnostics['reason'],'pose_sample_budget_exceeded')

    def test_public_prepare50_plan_confirmation_and_finish_use_same_owner_no_CAD(self):
        import motion_server as ms
        from test_external_gears import TaskTests
        fixture=TaskTests('test_plan_recommends_ratio_and_confirmation_stays_exactly_once')
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        first=fixture.tid;fixture.engine.finish(first);self.assertTrue(fixture.wait()['closed'])
        with patch.object(ms,'_task_engine',fixture.engine):
            response=asyncio.run(ms.mcp.call_tool('prepare_mechanism_task',{'assembly_path':str(fixture.source),'task_kind':'external_gear_pair','output_fps':50}))
            self.assertFalse(response.is_error);fixture.tid=response.structured_content['result']['task_id'];prepared=fixture.wait()
            self.assertEqual(prepared['motion_parameters']['output_fps'],50)
            s=fixture.engine.sessions[fixture.tid]
            core.write(s.folder/'导入.json',{'checkpoint':{'studies':[{'type':4,'fps':2500}]}})
            response=asyncio.run(ms.mcp.call_tool('plan_mechanism_task',{'task_id':fixture.tid}))
            self.assertFalse(response.is_error);planned=fixture.wait()
            self.assertEqual(planned['phase'],'awaiting_confirmation');self.assertEqual(planned['proposal']['motion']['output_fps'],50)
            self.assertTrue(planned['proposal']['motion']['native_grid_recommendation']['requires_plan_confirmation'])
            self.assertNotIn('execution_consumed',fixture.engine.tasks[fixture.tid]);self.assertEqual(s.applied,0)
            response=asyncio.run(ms.mcp.call_tool('finish_mechanism_task',{'task_id':fixture.tid}))
            self.assertFalse(response.is_error);closed=fixture.wait();self.assertTrue(closed['closed'])
            self.assertEqual(closed['server_instance_id'],fixture.engine.get(first)['server_instance_id'])


if __name__=='__main__':unittest.main()
