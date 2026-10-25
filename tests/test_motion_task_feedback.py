"""Preserve native solve failures and bridge replacements through owner routing."""
import asyncio
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch
import uuid

from sw_mcp.bridge import Bridge
from sw_mcp.conversation import core
from sw_mcp.conversation.formal_engine import FormalEngine
from sw_mcp.conversation.motion_tasks import MotionTaskEngine
from sw_mcp.conversation.owner_transport import fingerprint
from sw_mcp.validation import packed
from test_conversation_tasks import FakeSession

ROOT=Path(__file__).resolve().parents[1]


def folder():
    p=ROOT/'runs/motion-task-feedback-tests'/uuid.uuid4().hex[:8];p.mkdir(parents=True);return p


class FinishBridgeTests(unittest.TestCase):
    def engine(self):
        p=folder();old=Bridge(p);self.addCleanup(old.close)
        e=FormalEngine.__new__(FormalEngine);e.source_fingerprint=fingerprint();e.managed_upgrade_guard=False
        e.tasks=SimpleNamespace(active=None,prior_unfinished=[],sessions={},tasks={},work=p/'work')
        e.product=SimpleNamespace(ROOT=p,bridge=old,jobs=SimpleNamespace(_jobs={},bridge=old),artifacts=object())
        return p,e,old

    def test_finish_tool_keeps_replacement_bridge_and_can_prepare_without_owner_restart(self):
        p,e,old=self.engine()
        # Real retained Popen fixture exits on EOF. It never loads CAD or an executor binary.
        child=subprocess.Popen([sys.executable,'-c','import sys; sys.stdin.buffer.read()'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        old._process=child
        def cleanup():
            if child.stdin and not child.stdin.closed:child.stdin.close()
            child.wait(timeout=10);child.stdout.close();e.product.bridge.close()
        self.addCleanup(cleanup)
        old.recovery_state=Mock(return_value={'recovery_required':False})
        async def call(name,args):
            if name=='finish_motion_session':return packed({'ok':True,'result':e.finish_legacy()})
            return packed({'ok':True,'result':{'accepted':'no_CAD_handler_fixture'}})
        e.product.mcp=SimpleNamespace(call_tool=AsyncMock(side_effect=call))
        result=e.tool('finish_motion_session',{})
        self.assertTrue(result['structuredContent']['result']['confirmed'])
        self.assertEqual(child.poll(),0)
        self.assertIsNot(e.product.bridge,old)
        self.assertIs(e.product.bridge,e.product.jobs.bridge)
        self.assertIsNone(e.product.bridge._process)
        source=p/'fixture.SLDASM';source.write_bytes(b'fixture only')
        value=e.tool('prepare_mechanism_task',{'assembly_path':str(source)})
        self.assertTrue(value['structuredContent']['ok']);self.assertFalse(e.managed_upgrade_guard)

    def test_temporary_recovery_bridge_is_restored_when_handler_raises(self):
        p,e,old=self.engine();temporary=Mock()
        e.tasks.active='a'*32;e.tasks.sessions[e.tasks.active]=SimpleNamespace(bridge=temporary)
        e.product.mcp=SimpleNamespace(call_tool=AsyncMock(side_effect=RuntimeError('fixture refusal')))
        with self.assertRaisesRegex(RuntimeError,'fixture refusal'):e.tool('get_recovery_state',{})
        self.assertIs(e.product.bridge,old)

    def test_unknown_legacy_recovery_keeps_original_bridge_and_does_not_close_it(self):
        p,e,old=self.engine();old.recovery_state=Mock(return_value={'recovery_required':True})
        with patch.object(old,'close') as close:
            with self.assertRaises(core.StopBatch) as error:e.finish_legacy()
            self.assertEqual(error.exception.code,'NATIVE_STATE_UNKNOWN');close.assert_not_called()
        self.assertIs(e.product.bridge,old);self.assertIs(e.product.jobs.bridge,old)


class MotionFailureTests(unittest.TestCase):
    def fixture(self,answer):
        p=folder();(p/'models').mkdir();source=p/'models/fixture.SLDASM';source.write_bytes(b'offline only')
        class Session(FakeSession):
            def discover(s,path):
                s.runtime=s.folder/'runtime';s.motion_signature='same'
                s.initial_inspection={'components':[{'component_id':'moving','transform':[1,0,0,0,1,0,0,0,1,0,0,0]}]}
                s.motion_candidates=[{'drive':{'component_id':'moving','entity_id':'face'},'reference':{'component_id':'ground'},
                    'component_name':'slider','reference_name':'rail','axis_global':[1,0,0],'axis_point_global_m':[0,0,0],'reason':'fixture'}]
                return {'motion_candidates':s.motion_candidates,'scope':'fixture','studies':[]}
            def call(s,operation,**args):
                if operation=='_circular_reference_state':return {'signature':'same'}
                if operation=='inspect_model':return s.initial_inspection
                if operation=='verify_motion_preservation':return dict(answer)
                return {}
            def state(s,*a,**kw):pass
        engine=MotionTaskEngine(p,p/'work',p/'runtime',Session);self.addCleanup(engine.shutdown)
        def wait(tid):
            for _ in range(1000):
                value=engine.get(tid)
                if not value['busy']:return value
                time.sleep(.005)
            self.fail('fixture timeout')
        with patch('sw_mcp.conversation.startup_gate.require_idle'):
            tid=engine.prepare(str(source),motion='linear',speed=1,duration_s=2)['task_id']
        self.assertEqual(wait(tid)['phase'],'proposal_ready');engine.plan(tid);planned=wait(tid)
        return p,engine,tid,planned,wait

    def test_native_incomplete_error_survives_missing_pose_file_and_no_export_or_reexecute(self):
        answer={'run_id':'a'*32,'assertion':'inconclusive','error_code':'MOTION_RESULTS_INCOMPLETE',
                'failure':'Native results cover only t=0','failure_diagnostics':{'time_axis':{'native_frames':1,'expected_frames':61}},
                'restoration_status':'restored','source_files_unchanged':True,'report_path':'native-motion-validation.json'}
        p,e,tid,plan,wait=self.fixture(answer)
        with patch('sw_mcp.artifacts.Artifacts.export_history_curve') as export:
            e.execute(tid,plan['plan_token'],True,True);state=wait(tid)
        self.assertEqual(state['phase'],'failed')
        self.assertEqual(state['error']['code'],'MOTION_RESULTS_INCOMPLETE')
        self.assertEqual(state['error']['diagnostics']['run_id'],answer['run_id'])
        self.assertEqual(state['verification']['native_error_code'],'MOTION_RESULTS_INCOMPLETE')
        self.assertEqual(state['verification']['curve_status'],'not_exported_native_verification_not_passed')
        export.assert_not_called()
        self.assertEqual(core.read(Path(state['directory'])/'session/运动验证.json'),answer)
        with self.assertRaises(core.StopBatch) as error:e.execute(tid,plan['plan_token'],True,True)
        self.assertEqual(error.exception.code,'TASK_ALREADY_EXECUTED')
        e.finish(tid);self.assertTrue(wait(tid)['closed'])

    def test_failed_motion_criterion_without_native_error_does_not_read_missing_poses(self):
        answer={'run_id':'b'*32,'assertion':'fail','signed_net_travel':0,
                'restoration_status':'restored','source_files_unchanged':True}
        p,e,tid,plan,wait=self.fixture(answer)
        with patch('sw_mcp.artifacts.Artifacts.export_history_curve') as export:
            e.execute(tid,plan['plan_token'],True,True);state=wait(tid)
        self.assertEqual(state['phase'],'verification_failed');self.assertFalse(state['verification']['declared_scope_passed'])
        export.assert_not_called();e.finish(tid);self.assertTrue(wait(tid)['closed'])

    def test_reported_success_without_pose_artifact_is_explicit_evidence_error(self):
        answer={'run_id':'c'*32,'assertion':'pass','signed_net_travel':2,
                'restoration_status':'restored','source_files_unchanged':True}
        p,e,tid,plan,wait=self.fixture(answer)
        with patch('sw_mcp.artifacts.Artifacts.export_history_curve') as export:
            e.execute(tid,plan['plan_token'],True,True);state=wait(tid)
        self.assertEqual(state['error']['code'],'MOTION_POSE_EVIDENCE_UNAVAILABLE');export.assert_not_called()


class AxisGuidanceTests(unittest.TestCase):
    def rows(self):
        return [{'drive':{'component_id':'moving'},'reference':{'component_id':'rail'},'component_name':'slider',
            'reference_name':'rail','axis_global':axis,'axis_point_global_m':[0,0,0],'reason':'native face'}
            for axis in ([1,0,0],[0,1,0],[0,0,1])]

    def mate(self,axis=(0,0,1),**changes):
        return {'name':'concentric','native_feature_id':1,'type_name':'swMateCONCENTRIC','error':0,'warning':False,
                'entities':[{'component_id':c,'instance':c,'geometry':{'kind':'cylindrical_axis','axis_global':list(axis)}}
                            for c in ('moving','neighbor')],**changes}

    def test_existing_native_mate_axis_suggests_Z_without_removing_other_axes(self):
        from sw_mcp.conversation.axis_guidance import annotate_linear_axes
        rows=annotate_linear_axes(self.rows(),[self.mate()])
        self.assertEqual(len(rows),3);self.assertEqual([r['recommended_from_native_mate_axis'] for r in rows],[False,False,True])
        self.assertTrue(rows[0]['axis_evidence']['nonparallel_does_not_prove_blocked'])
        e=MotionTaskEngine.__new__(MotionTaskEngine);e.sessions={'t':SimpleNamespace(model='model')}
        t={'task_id':'t','task_kind':'motion'};e._proposals(t,{'motion_candidates':rows,'scope':'fixture','studies':[]})
        self.assertEqual(t['suggested_candidate_id'],'candidate-3')
        self.assertEqual(t['next_action']['arguments']['candidate_id'],'candidate-3')
        self.assertEqual(t['proposals'][2]['axis_evidence']['degrees_of_freedom_status'],'unknown')

    def test_unhealthy_unsupported_or_conflicting_mates_do_not_recommend(self):
        from sw_mcp.conversation.axis_guidance import annotate_linear_axes
        for mates in ([],[self.mate(error=1)],[self.mate(type_name='swMateCOINCIDENT')],[self.mate(),self.mate(axis=(1,0,0))]):
            with self.subTest(mates=mates):
                rows=annotate_linear_axes(self.rows(),mates)
                self.assertFalse(any(r['recommended_from_native_mate_axis'] for r in rows))

    def test_foreign_component_or_unresolved_other_axis_is_not_used(self):
        from sw_mcp.conversation.axis_guidance import annotate_linear_axes
        mate=self.mate();mate['entities'][0]['component_id']='unrelated'
        self.assertFalse(any(r['recommended_from_native_mate_axis'] for r in annotate_linear_axes(self.rows(),[mate])))
        mate=self.mate();mate['entities'][1]['geometry']=None
        self.assertFalse(any(r['recommended_from_native_mate_axis'] for r in annotate_linear_axes(self.rows(),[mate])))

    def test_linear_face_sign_is_stable_when_equivalent_entity_ids_change(self):
        from sw_mcp.conversation.motion_tasks import group_directions
        for positive_id,negative_id in [('z-positive','a-negative'),('a-positive','z-negative')]:
            rows=[{'entity_id':negative_id,'axis_global':[0,0,-1],'reference_point_global_m':[0,0,1],'area_m2':10},
                  {'entity_id':positive_id,'axis_global':[0,0,1],'reference_point_global_m':[0,0,0],'area_m2':1}]
            chosen=group_directions(rows,'linear')[0]
            self.assertEqual(chosen['entity_id'],positive_id);self.assertEqual(chosen['axis_global'],[0,0,1])


if __name__=='__main__':unittest.main(verbosity=2)
