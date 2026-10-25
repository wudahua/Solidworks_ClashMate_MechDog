"""Synthetic rigid-body counterexamples and task confirmation; no CAD here."""
import copy,csv,math,time,uuid,unittest
from pathlib import Path
from unittest.mock import patch
from sw_mcp.conversation import core,gear_transmission as gt
from sw_mcp.conversation.motion_tasks import MotionTaskEngine,prepare_inputs,parameters
from test_conversation_tasks import FakeSession

ROOT=Path(__file__).resolve().parents[1]

def fixture(folder,reverse=False):
    roles={r:r for r in gt.ROLES};centers={'input':[0,0,0],'output':[.035,0,0]};ids=list(roles)+['fixed'+str(i) for i in range(11)]
    initial=[];rows=[]
    for f in range(31):
        for cid in ids:
            side=cid.split('_')[0];theta=(1 if side=='input' else -1)*(-1 if reverse else 1)*math.radians(2.4*f) if side in centers else 0
            c,s=math.cos(theta),math.sin(theta);matrix=[c,s,0,-s,c,0,0,0,1]
            center=centers.get(side,[0,0,0]);offset=[.2,0,0] if cid.endswith('shaft') else [.005,0,.01] if cid.endswith('key') else [0,0,.02] if cid.endswith('gear') else [0,0,0]
            origin=[center[0]+c*offset[0]-s*offset[1],center[1]+s*offset[0]+c*offset[1],center[2]+offset[2]]
            row={'frame':f,'time_s':f/30,'component_id':cid,'instance':cid,**dict(zip(['x_m','y_m','z_m'],origin)),**dict(zip(['r'+str(i)+str(j) for i in range(3) for j in range(3)],matrix))};rows.append(row)
            if not f:initial.append({'component_id':cid,'instance':cid,'transform':matrix+origin+[1,0,0,0],'fixed_component':cid not in set(roles.values())-{'body'}})
    axes={'shaft_axes':{},'support_axes':{}}
    for side,point in centers.items():
        axes['shaft_axes'][side]={'component_id':side+'_shaft','fixed_component':False,'axis_global':[0,0,1],'reference_point_global_m':point}
        axes['support_axes'][side]={'component_id':'body','fixed_component':True,'axis_global':[0,0,1],'reference_point_global_m':point}
    settings=parameters('rotary',12,1,30,reverse,0);path=folder/'poses.csv'
    def save():
        with path.open('w',encoding='utf8',newline='') as out:w=csv.DictWriter(out,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    save();return path,rows,roles,initial,axes,settings,save

class GeometryTests(unittest.TestCase):
    def setUp(self):self.folder=ROOT/'runs/gear-unit'/uuid.uuid4().hex[:8];self.folder.mkdir(parents=True)
    def check(self,case):
        path,rows,roles,initial,axes,settings,save=case;save();return gt.audit(path,roles,[0,0,1],settings,initial,axes)
    def test_positive_and_negative_full_chain_with_orbiting_origins(self):
        for reverse in (False,True):
            result=self.check(fixture(self.folder,reverse));self.assertTrue(result['passed']);self.assertEqual(result['rows'],558)
            self.assertAlmostEqual(result['signed_final_degrees']['input_shaft'],-72 if reverse else 72)
            self.assertAlmostEqual(result['signed_final_degrees']['output_shaft'],72 if reverse else -72)
            self.assertFalse(result['contact_or_tooth_geometry_validated'])
    def test_key_slip_is_not_hidden_by_correct_shaft_ratio(self):
        case=fixture(self.folder)
        for r in case[1]:
            if r['frame']==30 and r['component_id']=='input_key':r['x_m']+=.00001
        with self.assertRaises(core.StopBatch):self.check(case)
    def test_fixed_part_motion_is_rejected(self):
        case=fixture(self.folder)
        for r in case[1]:
            if r['frame']==30 and r['component_id']=='fixed0':r['z_m']+=.00001
        with self.assertRaises(core.StopBatch):self.check(case)
    def test_wrong_output_rotation_is_rejected(self):
        case=fixture(self.folder)
        for r in case[1]:
            if r['component_id'].startswith('output_'):
                c,s=math.cos(math.radians(2.4*r['frame'])),math.sin(math.radians(2.4*r['frame']))
                r.update(dict(zip(['r'+str(i)+str(j) for i in range(3) for j in range(3)],[c,s,0,-s,c,0,0,0,1])))
        with self.assertRaises(core.StopBatch):self.check(case)
    def test_whole_rotor_axial_drift_is_rejected(self):
        case=fixture(self.folder)
        for r in case[1]:
            if r['component_id'].startswith('input_'):r['z_m']+=r['frame']*1e-6
        with self.assertRaises(core.StopBatch):self.check(case)
    def test_missing_samples_and_wrong_time_are_rejected(self):
        case=fixture(self.folder);case[1].pop()
        with self.assertRaises(core.StopBatch):self.check(case)
        case=fixture(self.folder);case[1][-1]['time_s']=1.1
        with self.assertRaises(core.StopBatch):self.check(case)
    def test_corrupt_pose_file_keeps_a_typed_evidence_error(self):
        path,rows,roles,initial,axes,settings,save=fixture(self.folder)
        with path.open('a',encoding='utf8',newline='') as out:
            writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writerow(rows[-1])
        with self.assertRaises(core.StopBatch) as caught:gt.audit(path,roles,[0,0,1],settings,initial,axes)
        self.assertEqual(caught.exception.code,'GEAR_MOTION_EVIDENCE_FAILED')
        self.assertIn('DUPLICATE_SAMPLE',caught.exception.diagnostics['cause'])

class TaskTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'runs/gear-unit'/uuid.uuid4().hex[:8];self.source=folder/'models/case.SLDASM';self.source.parent.mkdir(parents=True);self.source.write_bytes(b'fixture')
        proposal={'roles':{r:{'component_id':r,'instance':r,'currently_fixed':r!='input_shaft'} for r in gt.ROLES},
                  'plan_id':'fixture-plan','gear_ratio':{'expected_output_over_input':-1},'scope':gt.SCOPE}
        class Session(FakeSession):
            def state(s,*args,**kw):pass
            def discover(s,path):
                super().discover(path);s.gear_candidate=copy.deepcopy(proposal);s.writes=0;return {'gear_transmission':s.gear_candidate}
            def call(s,operation,**kw):
                if operation=='_preview_gear_transmission':return copy.deepcopy(proposal)
                if operation=='_apply_gear_transmission':s.writes+=1;raise core.StopBatch('GEAR_CONSTRAINT_CREATE_FAILED','controlled fixture')
                raise AssertionError(operation)
        self.engine=MotionTaskEngine(folder,folder/'work',folder/'runtime',Session);self.addCleanup(self.engine.shutdown)
    def wait(self,tid):
        for _ in range(300):
            state=self.engine.get(tid)
            if not state['busy']:return state
            time.sleep(.005)
        self.fail('timeout')
    def planned(self):
        with patch('sw_mcp.conversation.startup_gate.require_idle'):
            tid=self.engine.prepare(str(self.source),task_kind='gear_transmission')['task_id']
        self.assertEqual(self.wait(tid)['phase'],'proposal_ready');self.engine.plan(tid);state=self.wait(tid)
        self.assertEqual(state['phase'],'awaiting_confirmation');return tid,state
    def test_prepare_invalid_scope_does_not_create_task_or_touch_gate(self):
        with patch('sw_mcp.conversation.startup_gate.require_idle') as gate:
            for kwargs in ({'motion':'linear'},{'speed':61},{'minimum_travel':1},{'moving':'wrong'}):
                with self.assertRaises(core.StopBatch):self.engine.prepare(str(self.source),task_kind='gear_transmission',**kwargs)
            gate.assert_not_called();self.assertIsNone(self.engine.active)
    def test_confirmation_token_no_write_then_one_shot_failure(self):
        tid,state=self.planned();session=self.engine.sessions[tid]
        self.assertTrue(state['proposal']['requires_explicit_component_unfix_and_nine_constraint_confirmation'])
        self.assertNotIn('confirmation',state)
        with self.assertRaises(core.StopBatch):self.engine.execute(tid,state['plan_token'],True,False)
        self.assertEqual(session.writes,0);self.assertNotIn('execution_consumed',self.engine.get(tid))
        self.engine.execute(tid,state['plan_token'],True,True);done=self.wait(tid)
        self.assertEqual(done['error']['code'],'GEAR_CONSTRAINT_CREATE_FAILED');self.assertEqual(session.writes,1)
        with self.assertRaises(core.StopBatch):self.engine.execute(tid,state['plan_token'],True,True)
        self.assertEqual(session.writes,1)
    def test_plan_does_not_ignore_other_scope_flags(self):
        tid,state=self.planned()
        with self.assertRaises(core.StopBatch):self.engine.plan(tid,alignment_mode='small_translation')
        with self.assertRaises(core.StopBatch):self.engine.execute(tid,state['plan_token'],True,True,True)
        self.assertEqual(self.engine.sessions[tid].writes,0)

if __name__=='__main__':unittest.main(verbosity=2)
