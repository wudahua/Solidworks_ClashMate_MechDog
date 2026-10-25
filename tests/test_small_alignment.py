"""Strict-card typed errors and separately confirmed bounded alignment; no CAD."""
import ast,copy,math,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from sw_mcp.conversation import core,concentric_card as card,small_alignment as alignment
from sw_mcp.conversation.task_engine import TaskEngine
from sw_mcp.task_errors import TASK_ACTION_CLASSES
from test_conversation_tasks import FakeSession

ROOT=Path(__file__).resolve().parents[1]

def example(offset=0.541479375e-6,tilt=0):
    fixed={'component_id':'fixed','instance':'body','fixed_component':True,'transform':[1,0,0,0,1,0,0,0,1,0,0,0,1]}
    moving={'component_id':'moving','instance':'shaft','fixed_component':False,'transform':[1,0,0,0,1,0,0,0,1,offset,0,0,1]}
    a={'entity_id':'edge-fixed','component_id':'fixed','instance':'body','fixed_component':True,'axis_global':[0,0,1],
        'reference_point_global_m':[0,0,0],'kind':'circular_edge'}
    b={'entity_id':'edge-moving','component_id':'moving','instance':'shaft','fixed_component':False,'axis_global':[math.sin(tilt),0,math.cos(tilt)],
        'reference_point_global_m':[offset,0,0],'kind':'circular_edge'}
    return {'mate_type':'concentric','lock_rotation':False,'reference_a':a,'reference_b':b},[fixed,moving]

class CardTests(unittest.TestCase):
    def test_strict_card_keeps_original_tolerances_and_reports_measured_refusal(self):
        plan,components=example()
        with self.assertRaises(card.CardError) as caught:card.create(plan,components,'s')
        self.assertEqual(caught.exception.code,'CARD_REQUIRES_ALIGNED_INITIAL_AXES_NO_REPOSITIONING')
        self.assertAlmostEqual(caught.exception.diagnostics['observed_radial_offset_mm'],.000541479375)
        self.assertAlmostEqual(caught.exception.diagnostics['radial_limit_mm'],.0001)
        self.assertFalse(caught.exception.diagnostics['constraint_write_dispatched'])
        plan,components=example(0);value=card.create(plan,components,'s');card.validate(value)
        self.assertEqual(value['schema'],'concentric-scope-1.0');self.assertEqual(card.TOL['translation_m'],1e-7)
    def test_all_card_error_literals_have_deliberate_classification(self):
        tree=ast.parse(Path(card.__file__).read_text(encoding='utf8'))
        codes={n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
            and n.func.id=='CardError' and n.args and isinstance(n.args[0],ast.Constant)}
        self.assertGreaterEqual(len(codes),9)
        self.assertFalse(codes-set(TASK_ACTION_CLASSES))
    def test_small_proposal_records_signed_world_shift_and_distinct_scope(self):
        plan,components=example();value=alignment.proposal(plan,components,'s');alignment.validate(value)
        self.assertAlmostEqual(value['expected_translation_world_mm'][0],-.000541479375)
        self.assertEqual(value['maximum_translation_mm'],.01);self.assertTrue(value['separate_alignment_confirmation_required'])
        self.assertFalse(value['pre_alignment_motion_preservation_certified']);self.assertFalse(value['axis_tilt_correction_allowed'])
        self.assertEqual(value['motion_test']['independent_runs'],2)
    def test_larger_displacement_or_tilt_is_refused_before_write(self):
        for offset,tilt,code in [(11e-6,0,'ALIGNMENT_TRANSLATION_LIMIT_EXCEEDED'),(.5e-6,.001,'ALIGNMENT_REQUIRES_PARALLEL_AXES')]:
            with self.subTest(code=code):
                with self.assertRaises(core.StopBatch) as caught:alignment.proposal(*example(offset,tilt),'s')
                self.assertEqual(caught.exception.code,code)
    def test_more_than_one_floating_component_remains_unsupported(self):
        plan,components=example();components.append({'component_id':'another','fixed_component':False,'transform':components[1]['transform'][:]})
        with self.assertRaises(card.CardError) as caught:alignment.proposal(plan,components,'s')
        self.assertEqual(caught.exception.code,'CARD_REQUIRES_ONLY_SELECTED_COMPONENT_FLOATING')
    def test_forged_card_or_changed_budget_cannot_authorize_execution(self):
        plan,components=example();value=alignment.proposal(plan,components,'s');value['maximum_translation_mm']=1
        value['card_id']=card.seal(value)
        with self.assertRaises(core.StopBatch) as caught:alignment.validate(value)
        self.assertEqual(caught.exception.code,'ALIGNMENT_PROPOSAL_STALE')
    def test_realigned_pose_passes_but_axial_rotation_or_other_motion_fails(self):
        plan,components=example();value=alignment.proposal(plan,components,'s')
        after=copy.deepcopy(components);after[1]['transform'][9]=0
        result=alignment.audit(value,after);self.assertTrue(result['passed'])
        self.assertAlmostEqual(result['target_translation_mm'],.000541479375)
        for kind in ('axial','other','rotation','fixed'):
            changed=copy.deepcopy(after)
            if kind=='axial':changed[1]['transform'][11]=.001
            if kind=='other':changed[0]['transform'][9]=.001
            if kind=='rotation':changed[1]['transform'][:9]=[0,-1,0,1,0,0,0,0,1]
            if kind=='fixed':changed[1]['fixed_component']=True
            with self.subTest(kind=kind):
                with self.assertRaises(core.StopBatch) as caught:alignment.audit(value,changed)
                self.assertEqual(caught.exception.code,'ALIGNMENT_AUDIT_FAILED')
    def test_original_geometry_binding_catches_residual_misalignment(self):
        plan,components=example();value=alignment.proposal(plan,components,'s')
        with self.assertRaises(core.StopBatch):alignment.audit(value,components)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        p=ROOT/'runs/small-alignment-tests'/uuid.uuid4().hex[:8];source=p/'models/a.SLDASM';source.parent.mkdir(parents=True);source.write_bytes(b'fixture')
        class Session(FakeSession):
            def discover(s,path):
                value=super().discover(path);s.native,s.components=example();s.previews=0;return value
            def preview(s,index,*budgets):s.previews+=1;s.plan=copy.deepcopy(s.native);return s.plan
            def call(s,*a,**kw):return {'components':s.components}
        self.e=TaskEngine(p,p/'work',p/'runtime',Session);self.addCleanup(self.e.shutdown)
        self.tid=self.e.prepare(str(source))['task_id'];self.wait()
    def wait(self):
        for _ in range(300):
            value=self.e.get(self.tid)
            if not value['busy']:return value
            time.sleep(.005)
        self.fail('timeout')
    def planned(self):
        self.e.plan(self.tid);state=self.wait();self.assertEqual(state['phase'],'alignment_choice_required')
        self.e.plan(self.tid,alignment_mode='small_translation');state=self.wait()
        self.assertEqual(state['phase'],'awaiting_confirmation');return state
    def test_strict_refusal_suggests_but_never_automatically_authorizes_alignment(self):
        self.e.plan(self.tid);state=self.wait();self.assertEqual(state['phase'],'alignment_choice_required')
        self.assertEqual(state['strict_card_rejection']['code'],'CARD_REQUIRES_ALIGNED_INITIAL_AXES_NO_REPOSITIONING')
        self.assertNotIn('execution_consumed',state);self.assertNotIn('plan_token',state)
        s=self.e.sessions[self.tid];count=s.previews
        self.assertTrue(self.e.plan(self.tid)['needs_alignment_scope_selection']);self.assertEqual(s.previews,count)
        self.assertEqual(s.applied,0)
    def test_general_confirmation_is_insufficient_and_does_not_consume_token(self):
        state=self.planned()
        with patch('sw_mcp.conversation.small_alignment.execute') as write:
            with self.assertRaises(core.StopBatch) as caught:self.e.execute(self.tid,state['plan_token'],True,True)
            self.assertEqual(caught.exception.code,'CONFIRMATION_REQUIRED');write.assert_not_called()
        self.assertNotIn('execution_consumed',self.e.get(self.tid))
    def test_separate_confirmation_is_recorded_and_execution_is_exactly_once(self):
        state=self.planned();result={'declared_scope_passed':True,'scope':'post_alignment_only'}
        with patch('sw_mcp.conversation.small_alignment.execute',return_value=result) as execute:
            self.e.execute(self.tid,state['plan_token'],True,True,True);done=self.wait()
            self.assertEqual(done['phase'],'verified');self.assertTrue(done['confirmation']['alignment_confirmed'])
            with self.assertRaises(core.StopBatch) as caught:self.e.execute(self.tid,state['plan_token'],True,True,True)
            self.assertEqual(caught.exception.code,'TASK_ALREADY_EXECUTED');self.assertEqual(execute.call_count,1)
    def test_invalid_mode_does_not_enqueue_or_change_session(self):
        with self.assertRaises(core.StopBatch) as caught:self.e.plan(self.tid,alignment_mode='loose')
        self.assertEqual(caught.exception.code,'INVALID_ALIGNMENT_MODE');self.assertFalse(self.e.get(self.tid)['busy'])

if __name__=='__main__':unittest.main(verbosity=2)
