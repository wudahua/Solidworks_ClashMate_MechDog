import json,os,subprocess,sys,time,uuid,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from sw_mcp.conversation.task_engine import TaskEngine,ConversationSession,release_executor,core,HERE

class FakeSession:
    def __init__(self,project,folder,runtime_base,**kw):
        folder.mkdir();self.folder=folder;self.model='model-'+uuid.uuid4().hex;self.bridge=None;self.unknown=False;self.committed=False
        self.applied=0;self.restored=0;self.selected=['a','b'];self.on_stage=kw.get('on_stage')
    def discover(self,path):
        self.recommendation={'requires_geometric_selection':False,'geometry_complete':True,'reference_state_signature':'s',
            'selection_question':'confirm pair','recommendations':[{'instances':['shaft','housing'],'geometry':{},'reason':'coaxial','rank_cost':0}]}
        return self.recommendation
    def preview(self,index):self.plan={'reference_a':{'entity_id':'a'},'reference_b':{'entity_id':'b'}};return self.plan
    def call(self,*a,**kw):return {'components':[]}
    def apply(self,confirmed):self.applied+=1;self.committed=True
    def restore(self):self.restored+=1;return {'restoration_status':'restored'}
    def close(self):
        core.write(self.folder/'exit.json',{'normal_zero_exit':True,'native_process_exited':True,'exit_code':0})
        core.write(self.folder/'执行器收尾.json',{'confirmed':True,'executor_exit_code':0})
        return {'ended':True,'import_checkpoint_restored':True}

class EngineTests(unittest.TestCase):
    def setUp(self):
        self.root=HERE.parents[1]/'runs/dialogue-fixtures'/uuid.uuid4().hex[:8];self.root.mkdir(parents=True)
        models=self.root/'models';models.mkdir()
        self.source=models/'case.SLDASM';self.source.write_bytes(b'fixture only')
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(HERE.parents[1]/'runs/l')});self.env.start()
        self.engine=TaskEngine(self.root,self.root/'work',self.root/'runtime',FakeSession)
    def tearDown(self):self.engine.shutdown();self.env.stop()
    def wait(self,tid):
        for _ in range(500):
            value=self.engine.get(tid)
            if not value['busy']:return value
            time.sleep(.005)
        self.fail('fixture did not finish')
    def prepared(self):
        tid=self.engine.prepare(str(self.source))['task_id'];self.assertEqual(self.wait(tid)['phase'],'proposal_ready');return tid
    def planned(self):
        tid=self.prepared()
        with patch('sw_mcp.conversation.concentric_card.create',return_value={'card_id':'fixture'}):
            self.engine.plan(tid);state=self.wait(tid)
        self.assertEqual(state['phase'],'awaiting_confirmation');return tid,state['plan_token']
    def test_second_round_requires_first_finish_and_same_owner_then_works(self):
        first=self.prepared()
        with self.assertRaises(core.StopBatch) as e:self.engine.prepare(str(self.source))
        self.assertEqual(e.exception.code,'TASK_SESSION_ACTIVE')
        self.engine.finish(first);self.assertTrue(self.wait(first)['closed'])
        second=self.prepared();self.assertNotEqual(first,second)
        self.assertEqual(self.engine.get(first)['server_pid'],self.engine.get(second)['server_pid'])
        self.assertEqual(self.engine.get(first)['server_instance_id'],self.engine.get(second)['server_instance_id'])
    def test_missing_confirmation_and_wrong_token_never_execute(self):
        tid,token=self.planned()
        for args in [(token,False,True),(token,True,False),('wrong',True,True)]:
            with self.assertRaises(core.StopBatch):self.engine.execute(tid,*args)
        self.assertEqual(self.engine.sessions[tid].applied,0)
    def test_exactly_once_and_failure_does_not_replay(self):
        tid,token=self.planned()
        with patch('sw_mcp.conversation.mate_motion.baseline',side_effect=core.StopBatch('CAD_TIMEOUT')) as baseline:
            self.engine.execute(tid,token,True,True);state=self.wait(tid)
            self.assertEqual(state['phase'],'failed')
            with self.assertRaises(core.StopBatch):self.engine.execute(tid,token,True,True)
            self.assertEqual(baseline.call_count,1)
        self.assertFalse(state['error']['retry_write_allowed'])
    def test_unknown_state_prevents_finish_and_second_task(self):
        tid=self.prepared();self.engine.sessions[tid].unknown=True
        self.engine.finish(tid);self.assertEqual(self.wait(tid)['error']['code'],'NATIVE_STATE_UNKNOWN')
        with self.assertRaises(core.StopBatch):self.engine.prepare(str(self.source))
        self.assertEqual(self.engine.sessions[tid].restored,0)
    def test_no_silent_resume_of_other_process_unfinished_task(self):
        self.prepared()
        other=TaskEngine(self.root,self.root/'work',self.root/'runtime',FakeSession)
        try:
            with self.assertRaises(core.StopBatch) as e:other.prepare(str(self.source))
            self.assertEqual(e.exception.code,'PRIOR_TASK_UNCONFIRMED')
        finally:other.shutdown()
    def test_lost_owner_record_is_readable_but_cannot_consume_token_or_write(self):
        tid,token=self.planned()
        other=TaskEngine(self.root,self.root/'work',self.root/'runtime',FakeSession)
        try:
            state=other.get(tid)
            self.assertEqual(state['connection_status'],'owner_lost_read_only')
            self.assertEqual(state['plan_token'],token)
            self.assertIn(tid,[t['task_id'] for t in other.get()['tasks']])
            with self.assertRaises(core.StopBatch) as e:other.execute(tid,token,True,True)
            self.assertEqual(e.exception.code,'TASK_OWNER_UNAVAILABLE')
            self.assertNotIn('execution_consumed',other.get(tid))
            with self.assertRaises(core.StopBatch):other.finish(tid)
        finally:other.shutdown()
    def test_ambiguity_is_dialogue_selection_and_reuses_session(self):
        class Ambiguous(FakeSession):
            def discover(session,path):
                raise core.StopBatch('COMPONENT_NAME_AMBIGUOUS',diagnostics={'choices':[{'name':'gear-1'},{'name':'gear-2'}]})
            def rescan(session):return FakeSession.discover(session,self.source)
        self.engine.session_factory=Ambiguous
        tid=self.engine.prepare(str(self.source))['task_id'];state=self.wait(tid)
        self.assertEqual(state['phase'],'awaiting_component_selection')
        session=self.engine.sessions[tid];session.moving_hint='shaft';session.reference_hint='gear'
        self.assertEqual(len(self.engine.plan(tid)['choices']),2)
        self.engine.plan(tid,reference_component_hint='gear-2');state=self.wait(tid)
        self.assertEqual(state['phase'],'proposal_ready');self.assertIs(self.engine.sessions[tid],session)
        self.assertEqual(session.reference_hint,'gear-2');self.assertEqual(session.applied,0)
    def test_finish_is_idempotent_without_second_restore(self):
        tid=self.prepared();self.engine.finish(tid);self.wait(tid)
        self.engine.finish(tid);self.assertEqual(self.engine.sessions[tid].restored,1)
    def test_explicit_recovery_revokes_old_plan_and_preserves_failure(self):
        tid,token=self.planned()
        self.engine.tasks[tid]['error']={'code':'ORIGINAL_FAILURE'}
        self.engine.mark_recovered(tid,{'restoration_status':'restored'})
        state=self.engine.get(tid)
        self.assertEqual(state['phase'],'recovered');self.assertNotIn('plan_token',state)
        self.assertEqual(state['original_failure']['code'],'ORIGINAL_FAILURE')
        self.assertEqual(state['next_action']['tool'],'finish_mechanism_task')
        with self.assertRaises(core.StopBatch):self.engine.execute(tid,token,True,True)
        self.assertEqual(self.engine.sessions[tid].applied,0)
    def test_forged_candidate_never_dispatches(self):
        tid=self.prepared()
        with self.assertRaises(core.StopBatch):self.engine.plan(tid,'candidate-999')

    def test_scope_pass_never_overwrites_full_trajectory_failure(self):
        tid,token=self.planned()
        verdict={'scope_verification':{'scope_acceptance_passed':True},'passed':False,
                 'baseline':{'run_id':'before'},'after':{'run_id':'after'},'mechanical_card':{'card_id':'fixture'}}
        with patch('sw_mcp.conversation.mate_motion.baseline'),patch('sw_mcp.conversation.mate_motion.verify',return_value=verdict):
            self.engine.execute(tid,token,True,True);state=self.wait(tid)
        self.assertEqual(state['phase'],'verified')
        self.assertTrue(state['verification']['declared_scope_passed'])
        self.assertFalse(state['verification']['full_trajectory_equivalent'])
        self.assertEqual(self.engine.sessions[tid].applied,1)

    def test_busy_execution_does_not_consume_confirmation(self):
        tid,token=self.planned();self.engine.tasks[tid]['busy']=True
        try:
            with self.assertRaises(core.StopBatch) as e:self.engine.execute(tid,token,True,True)
            self.assertEqual(e.exception.code,'TASK_BUSY')
            self.assertNotIn('execution_consumed',self.engine.tasks[tid])
        finally:self.engine.tasks[tid]['busy']=False

    def test_real_session_gate_refusal_can_finish_without_CAD_or_server_restart(self):
        from sw_mcp.conversation import startup_gate
        class RefusedBeforeCAD(ConversationSession):
            def discover(session,path):
                startup_gate.require_idle(session.folder,lambda:{'status':'occupied','COM_called':False})
        self.engine.session_factory=RefusedBeforeCAD
        with patch('sw_mcp.conversation.mate_worker.compile_runtime') as compile_native,patch('sw_mcp.conversation.core.subprocess.Popen') as launch:
            first=self.engine.prepare(str(self.source))['task_id'];failed=self.wait(first)
            self.assertEqual(failed['phase'],'failed')
            self.assertEqual(failed['error']['code'],'EXECUTOR_ALREADY_RUNNING')
            session=self.engine.sessions[first]
            self.assertIsNone(session.proc);self.assertIsNone(session.bridge);self.assertFalse(session.unknown)
            self.engine.finish(first);closed=self.wait(first)
            self.assertTrue(closed['closed']);self.assertIsNone(closed['finish']['native_exit'])
            self.assertIsNone(closed['finish']['restoration'])
            self.assertTrue(closed['finish']['executor_exit']['confirmed'])
            second=self.engine.prepare(str(self.source))['task_id'];self.wait(second)
            self.assertNotEqual(first,second)
            self.assertEqual(self.engine.get(first)['server_instance_id'],self.engine.get(second)['server_instance_id'])
            self.engine.finish(second);self.assertTrue(self.wait(second)['closed'])
            compile_native.assert_not_called();launch.assert_not_called()

class ExecutorCloseTests(unittest.TestCase):
    def folder(self):
        p=HERE.parents[1]/'runs/dialogue-fixtures'/uuid.uuid4().hex[:8];p.mkdir(parents=True);return p
    def test_real_child_eof_and_exit_precede_lease_close(self):
        proc=subprocess.Popen([sys.executable,'-c','import sys;sys.stdin.read()'],stdin=subprocess.PIPE)
        bridge=Mock(_process=proc);bridge.close.side_effect=lambda:self.assertIsNotNone(proc.poll())
        result=release_executor(bridge,self.folder(),timeout=5)
        self.assertTrue(result['confirmed']);self.assertEqual(result['executor_exit_code'],0);bridge.close.assert_called_once()
    def test_unconfirmed_child_keeps_lease_and_no_force_kill(self):
        proc=subprocess.Popen([sys.executable,'-c','import sys,time;sys.stdin.read();time.sleep(1)'],stdin=subprocess.PIPE)
        bridge=Mock(_process=proc)
        try:
            with self.assertRaises(core.StopBatch) as e:release_executor(bridge,self.folder(),timeout=.02)
            self.assertEqual(e.exception.code,'EXECUTOR_EXIT_UNCONFIRMED');bridge.close.assert_not_called()
        finally:proc.wait(timeout=5)

if __name__=='__main__':unittest.main(verbosity=2)
