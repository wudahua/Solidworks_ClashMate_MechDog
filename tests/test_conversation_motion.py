"""New dialogue contracts: no CAD, no scheduler registration."""
import asyncio,hashlib,json,uuid,unittest,zipfile,time,threading
from pathlib import Path
from unittest.mock import patch
import motion_server
from sw_mcp.conversation.motion_tasks import parameters,group_directions,MotionTaskEngine,require_same_poses
from sw_mcp.conversation import evidence_bundle,core


class MotionContractTests(unittest.TestCase):
    def test_missing_task_is_structured_and_never_creates_native_session(self):
        from types import SimpleNamespace
        with patch.object(motion_server,'_task_engine',SimpleNamespace(tasks={})):
            response=asyncio.run(motion_server.mcp.call_tool('execute_mechanism_task',{'task_id':'a'*32,'plan_token':'b'*32})).structured_content
        self.assertEqual(response['error']['code'],'TASK_NOT_IN_CURRENT_SERVER')
        self.assertEqual(response['error']['next_action']['tool'],'get_mechanism_task')

    def test_owned_recovery_admission_refuses_pending_or_lost_original_handles(self):
        from unittest.mock import Mock
        from sw_mcp.conversation.task_engine import ConversationSession
        s=ConversationSession.__new__(ConversationSession);s.model='model';s.checkpoint='checkpoint'
        s.folder=Path(__file__).resolve().parents[1]/'runs'/('recovery-fixture-'+uuid.uuid4().hex[:8]);s.folder.mkdir()
        s.proc=Mock(pid=1);s.proc.poll.return_value=None
        s.bridge=Mock();s.bridge._process=Mock(pid=2);s.bridge._process.poll.return_value=None
        s.bridge._state_lock=threading.Lock();s.bridge._pending={};s.bridge._quarantined_request=None;s.bridge.cad_operation_state='idle'
        s.bridge._reader_thread.is_alive.return_value=True
        s.bridge.recovery_state.return_value={'status':'unknown','executor_pid':2,'solidworks_pid':1}
        s.admit_owned_recovery('model','checkpoint');s.bridge.request.assert_not_called()
        for mode in ['pending','disconnected','replacement','wrong_checkpoint']:
            s.bridge._pending={'request':object()} if mode=='pending' else {}
            s.bridge._reader_thread.is_alive.return_value=mode!='disconnected'
            with self.assertRaises(core.StopBatch):s.admit_owned_recovery('model','wrong' if mode=='wrong_checkpoint' else 'checkpoint',mode=='replacement')
        s.bridge.request.assert_not_called()

    def test_stale_read_restarts_once_preserves_selected_edges_and_never_solves(self):
        from types import SimpleNamespace
        from sw_mcp.conversation import mate_motion
        from sw_mcp.bridge import CadError
        root=Path(__file__).resolve().parents[1]/'runs'/('read-retry-fixture-'+uuid.uuid4().hex[:8]);root.mkdir()
        calls=[]
        def call(operation,**kw):calls.append(operation);return {'signature':'same'}
        s=SimpleNamespace(folder=root,model='model',unknown=False,recommendation={},call=call)
        binding={'pair_components':['A','B'],'pair_entities':['ea','eb'],'baseline':{'run_id':'a'*32}}
        a={'entity_id':'ea','component_id':'A','instance':'shaft','kind':'circular_edge'}
        b={'entity_id':'eb','component_id':'B','instance':'bearing','kind':'circular_edge'}
        with patch('sw_mcp.conversation.mate_motion.component_geometry',side_effect=[CadError('MATE_CURSOR_STALE','stale'),[a],[b]]) as geometry:
            mate_motion.refresh_pair(s,binding,{});self.assertEqual(geometry.call_count,3)
        self.assertEqual([r['entity_id'] for r in s.recommendation['recommendations'][0]['references']],['ea','eb'])
        self.assertEqual(set(calls),{'_circular_reference_state'})
        with patch('sw_mcp.conversation.mate_motion.component_geometry',side_effect=CadError('MATE_CURSOR_STALE','stale')) as geometry:
            with self.assertRaises(CadError):mate_motion.refresh_pair(s,binding,{})
            self.assertEqual(geometry.call_count,2)

    def test_uncertain_host_request_never_claims_CAD_was_not_dispatched(self):
        from sw_mcp.conversation.frontend import transport_refusal
        response=transport_refusal(core.StopBatch('TASK_OWNER_REQUEST_UNCONFIRMED',diagnostics={'request_id':'a'*32})).structured_content
        self.assertIsNone(response['error']['diagnostics']['cad_dispatched'])
        self.assertIsNone(response['error']['diagnostics']['job_created'])
        self.assertFalse(response['error']['next_action']['automatic_retry'])
        self.assertEqual(response['error']['next_action']['tool'],'get_mechanism_task')

    def test_source_change_blocks_new_native_work_before_acquiring_lease(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from sw_mcp.conversation.formal_engine import FormalEngine
        e=FormalEngine.__new__(FormalEngine);e.source_fingerprint='old'
        e.product=SimpleNamespace(bridge=Mock());e.tasks=SimpleNamespace()
        with patch('sw_mcp.conversation.owner_transport.fingerprint',return_value='new'):
            with self.assertRaises(core.StopBatch) as error:e.tool('prepare_mechanism_task',{'assembly_path':'unused'})
        self.assertEqual(error.exception.code,'HOST_SOURCE_CHANGED');e.product.bridge._acquire_lease.assert_not_called()

    def test_standalone_verification_dispatch_includes_empty_plan_and_reverse_is_checked(self):
        from test_conversation_tasks import FakeSession
        class MotionFixture(FakeSession):
            def discover(s,path):
                s.runtime=s.folder/'runtime';s.motion_signature='signature'
                s.initial_inspection={'components':[{'component_id':'moving','transform':[1,0,0,0,1,0,0,0,1,0,0,0]}]}
                s.motion_candidates=[{'drive':{'component_id':'moving','entity_id':'face'},'reference':{'component_id':'ground'},
                    'component_name':'slide','reference_name':'ground','axis_global':[0,0,1],
                    'axis_point_global_m':[0,0,0],'reason':'fixture'}]
                return {'motion_candidates':s.motion_candidates,'scope':'fixture','studies':[]}
            def call(s,operation,**args):
                if operation=='_circular_reference_state':return {'signature':'signature'}
                if operation=='inspect_model':return s.initial_inspection
                if operation=='verify_motion_preservation':
                    if 'plan_id' not in args:raise KeyError('Native dispatch requires plan_id even when empty')
                    if args['plan_id']!='':raise AssertionError('standalone validation must not bind a mate plan')
                    import csv
                    file=s.runtime/'runs'/('a'*32)/'component-poses.csv';file.parent.mkdir(parents=True)
                    with file.open('w',newline='',encoding='utf8') as f:
                        writer=csv.writer(f);writer.writerow(['frame','time_s','component_id',*[f'r{i}{j}' for i in range(3) for j in range(3)],'x_m','y_m','z_m'])
                        writer.writerow([0,0,'moving',1,0,0,0,1,0,0,0,1,0,0,0])
                    return dict(assertion='pass',restoration_status='restored',source_files_unchanged=True,run_id='a'*32,signed_net_travel=-2)
                return {}
            def state(s,*a,**kw):pass
        root=Path(__file__).resolve().parents[1]/'runs'/('motion-fixture-'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
        (root/'models').mkdir();source=root/'models/model.SLDASM';source.write_bytes(b'offline fixture only')
        engine=MotionTaskEngine(root,root/'work',root/'rt',MotionFixture)
        def wait(tid):
            for _ in range(500):
                value=engine.get(tid)
                if not value['busy']:return value
                time.sleep(.005)
            raise AssertionError('fixture timeout')
        try:
            with patch('sw_mcp.conversation.startup_gate.require_idle'):
                tid=engine.prepare(str(source),motion='linear',speed=1,duration_s=2,reverse_direction=True)['task_id']
            self.assertEqual(wait(tid)['phase'],'proposal_ready')
            engine.plan(tid);planned=wait(tid)
            with patch('sw_mcp.artifacts.Artifacts.export_history_curve',return_value={'path':'fixture.csv'}):
                engine.execute(tid,planned['plan_token'],True,True);result=wait(tid)
            self.assertEqual(result['phase'],'verified',result)
            self.assertTrue(result['verification']['direction_verified_about_selected_native_axis'])
            with self.assertRaises(core.StopBatch):engine.execute(tid,planned['plan_token'],True,True)
            engine.finish(tid);self.assertTrue(wait(tid)['closed'])
        finally:engine.shutdown()

    def test_scalar_policy_refuses_coercion_and_sparse_grid(self):
        for args in [('linear',True,1,30,False,0),('linear',1,1,30,1,0),('linear',1,6,30,False,0),('rotary',12,.1,30,False,0)]:
            with self.assertRaises((ValueError,core.StopBatch)):parameters(*args)
        self.assertEqual(parameters('linear',1,2,30,True,0)['expected_travel'],2)

    def test_initial_pose_gate_refuses_clock_only_zero_or_missing_components(self):
        a={'slide':[1,0,0,0,1,0,0,0,1,0,0,0]}
        b={'slide':[1,0,0,0,1,0,0,0,1,0,0,.002]}
        with self.assertRaises(core.StopBatch) as error:require_same_poses(a,b,'frame_zero')
        self.assertEqual(error.exception.code,'INITIAL_POSE_MISMATCH')
        with self.assertRaises(core.StopBatch):require_same_poses(a,{},'frame_zero')

    def test_group_parallel_planes_but_preserve_different_rotary_axes(self):
        def row(n,p,a):return dict(entity_id=n,axis_global=a,reference_point_global_m=p,area_m2=1)
        rows=[row('a',[0,0,0],[0,0,1]),row('b',[0,0,2],[0,0,-1]),row('c',[1,0,0],[0,0,1])]
        self.assertEqual(len(group_directions(rows,'linear')),1)
        self.assertEqual(len(group_directions(rows,'rotary')),2)

    def test_single_entry_retains_legacy_and_adds_dialogue_and_closed_types(self):
        tools=asyncio.run(motion_server.mcp.list_tools());names={t.name for t in tools}
        self.assertEqual(len(names),30)
        self.assertTrue({'import_assembly','run_motion_study','prepare_mechanism_task','finish_mechanism_task','finish_motion_session'}<=names)
        for t in tools:self.assertFalse(t.input_schema['additionalProperties'])
        with patch.object(motion_server,'_task_engine') as engine:
            result=asyncio.run(motion_server.mcp.call_tool('prepare_mechanism_task',{'assembly_path':'a','speed':True})).structured_content
            self.assertEqual(result['error']['code'],'INVALID_ARGUMENT');engine.prepare.assert_not_called()

    def test_offline_evidence_is_real_zip_scrubs_secrets_and_omits_CAD(self):
        base=Path(__file__).resolve().parents[1]/'runs'
        base.mkdir(exist_ok=True)
        w=base/('evidence-fixture-'+uuid.uuid4().hex[:8]);w.mkdir()
        secret='sensitive-auth-test';generation='a'*32
        core.write(w/'owner.json',{'secret':secret,'identity':{'pid':1}})
        core.write(w/'ipc'/generation/'launch.json',{'secret':secret})
        core.write(w/'task-x/session/state.json',{'message':secret})
        (w/'task-x/session/file.SLDASM').write_bytes(b'CAD not to be packed')
        result=evidence_bundle.collect(w)
        self.assertEqual(result['sha256'],core.digest(result['zip_path']))
        with zipfile.ZipFile(result['zip_path']) as z:
            self.assertIsNone(z.testzip());self.assertFalse(any(n.endswith('.SLDASM') or n.endswith('launch.json') for n in z.namelist()))
            for n in z.namelist():self.assertNotIn(secret.encode(),z.read(n))

if __name__=='__main__':unittest.main(verbosity=2)
