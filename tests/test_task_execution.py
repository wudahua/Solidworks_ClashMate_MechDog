"""Wrong-token recovery and blocking-call observation; no CAD or scheduler."""
import copy
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from sw_mcp.conversation import core, task_execution as execution, task_progress as progress
from sw_mcp.task_errors import task_failure

ROOT = Path(__file__).resolve().parents[1]


class TokenTests(unittest.TestCase):
    def task(self):
        return {'task_id': 'a'*32, 'phase': 'awaiting_confirmation', 'plan_token': 'b'*32,
                'proposal': {'plan_id': 'original-plan'}, 'closed': False}

    def test_wrong_token_keeps_original_confirmation_and_never_leaks_expected_token(self):
        task = self.task(); before = copy.deepcopy(task)
        with self.assertRaises(core.StopBatch) as raised:
            execution.require_plan_token(task, 'c'*32)
        self.assertEqual(task, before)
        e = raised.exception
        self.assertEqual(e.code, 'PLAN_TOKEN_MISMATCH')
        self.assertTrue(e.diagnostics['current_plan_still_valid'])
        self.assertFalse(e.diagnostics['requires_new_plan'])
        self.assertNotIn(task['plan_token'], str(e.diagnostics))
        envelope = task_failure(e.code, str(e), e.diagnostics, task_id=task['task_id'])
        self.assertFalse(envelope['diagnostics']['cad_dispatched'])
        self.assertTrue(envelope['next_action']['readback_required'])
        self.assertFalse(envelope['next_action']['automatic_retry'])
        self.assertFalse(envelope['next_action']['requires_new_plan'])
        execution.require_plan_token(task, task['plan_token'])
        self.assertEqual(task, before)

    def test_consumed_plan_outranks_wrong_token(self):
        task = {**self.task(), 'execution_consumed': True, 'phase': 'failed'}
        for token in ('wrong', task['plan_token']):
            with self.subTest(token=token), self.assertRaises(core.StopBatch) as raised:
                execution.require_plan_token(task, token)
            self.assertEqual(raised.exception.code, 'TASK_ALREADY_EXECUTED')

    def test_revoked_closed_missing_and_stale_plans_never_take_correction_route(self):
        for changes in ({'plan_token_revoked': True}, {'closed': True}, {'plan_token': None}, {'phase': 'recovered'}, {'phase': 'proposal_ready'}):
            with self.subTest(changes=changes), self.assertRaises(core.StopBatch) as raised:
                execution.require_plan_token({**self.task(), **changes}, 'wrong')
            self.assertEqual(raised.exception.code, 'TASK_NOT_READY_FOR_EXECUTION')

    def test_bare_or_async_mismatch_does_not_infer_plan_validity(self):
        for asynchronous in (False, True):
            e = task_failure('PLAN_TOKEN_MISMATCH', 'fixture', asynchronous=asynchronous)
            self.assertNotIn('requires_new_plan', e['next_action'])
            self.assertNotIn('旧方案失效', e['next_action']['instruction'])
            self.assertNotEqual(e['next_action']['options_status'], 'fresh_task_plan_required_no_write_retry')
            if asynchronous:self.assertIsNone(e['diagnostics']['cad_dispatched'])


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.folder = ROOT/'runs/task-progress-fixtures'/uuid.uuid4().hex[:8]
        self.folder.mkdir(parents=True)
        self.values = []
        self.session = SimpleNamespace(runtime=self.folder, on_progress=self.values.append, bridge=Mock())
        self.run = uuid.uuid4().hex
        self.args = {'run_id': self.run, 'job_id': self.run}
        self.file = self.folder/'runs/progress'/(self.run+'.json')

    def wait_for(self, predicate):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if any(predicate(v) for v in self.values):return
            time.sleep(.005)
        self.fail('observer fixture did not publish expected state')

    def write(self, name, **kw):
        now=time.time()
        core.write(self.file, {'job_id':self.run,'run_id':self.run,'stage':name,'updated_at':now,'stage_started_at':now,**kw})

    def test_blocking_call_heartbeats_preserve_native_age_and_only_sampling_fraction(self):
        with progress.watch_call(self.session,'run_user_study',self.args,interval=.01):
            self.write('native_calculate',completed=0,total=31)
            self.wait_for(lambda v:v['stage']=='native_calculate')
            first=next(v['heartbeat_at'] for v in self.values if v['stage']=='native_calculate')
            # A busy host can deliver its first observation after 25ms; age
            # alone must not be mistaken for observing a second heartbeat.
            self.wait_for(lambda v:v['stage']=='native_calculate' and v['heartbeat_at']>first and v['native_update_age_s']>.025)
            calculated=[v for v in self.values if v['stage']=='native_calculate']
            self.assertGreater(calculated[-1]['heartbeat_at'],calculated[0]['heartbeat_at'])
            self.assertEqual(calculated[-1]['last_native_update_at'],calculated[0]['last_native_update_at'])
            self.assertIsNone(calculated[-1]['sampling_fraction'])
            self.write('capture_solver_poses',completed=15,total=31)
            self.wait_for(lambda v:v['sampling_fraction']==15/31)
            self.write('restore_solve_scope',completed=31,total=31)
            self.wait_for(lambda v:v['stage']=='restore_solve_scope')
        self.assertIsNone(self.values[-1]['sampling_fraction'])
        for v in self.values:
            self.assertFalse(v['heartbeat_proves_native_progress'])
            self.assertFalse(v['native_completion_proven_by_observer'])
            self.assertIsNone(v['overall_fraction'])
            self.assertIsNone(v['estimated_remaining_s'])
        self.session.bridge.request.assert_not_called()
        count=len(self.values);time.sleep(.025);self.assertEqual(len(self.values),count)

    def test_foreign_old_and_malformed_progress_never_become_native_evidence(self):
        for kw in ({'job_id':'foreign'},{'run_id':'foreign'},{'updated_at':time.time()-20},{'updated_at':True},{'stage':'../bad'}):
            with self.subTest(kw=kw):
                self.write('native_calculate',**kw)
                self.assertIsNone(progress._native_record(self.file,self.run,self.run,time.time()))
        self.file.write_text('{broken',encoding='utf8')
        with progress.watch_call(self.session,'run_user_study',self.args,interval=.01):
            self.wait_for(lambda v:v['observation_source']=='owner_wait_heartbeat_only')
        self.assertTrue(all(not v['native_progress_observed'] for v in self.values))

    def test_observer_failure_does_not_mask_native_failure_or_trigger_retry(self):
        self.session.on_progress=Mock(side_effect=OSError('fixture-only'))
        with self.assertRaisesRegex(RuntimeError,'native-failure'):
            with progress.watch_call(self.session,'run_user_study',self.args,interval=.01):
                raise RuntimeError('native-failure')
        self.assertEqual(self.session.progress_observation_error,'OSError')
        self.session.bridge.request.assert_not_called()

    def test_round_two_resets_old_success_and_whole_task_stays_running(self):
        engine=SimpleNamespace(lock=threading.RLock(),save=Mock())
        task={'busy':True,'phase':'running'}
        progress.start_round(engine,task,1,2)
        task['progress'].update(verification_passed=True,stage='verified')
        progress.start_round(engine,task,2,2)
        self.assertEqual(task['phase'],'running')
        self.assertEqual(task['progress']['completed_rounds'],1)
        self.assertNotIn('verification_passed',task['progress'])
        progress.observe_call(engine,task,{'stage':'native_calculate','stage_started_at':time.time(),'native_completion_proven_by_observer':False})
        self.assertEqual(task['round_index'],2)
        self.assertEqual(task['native_stage'],'native_calculate')
        self.assertEqual(task['phase'],'running')
        self.assertIn('第2/2轮',task['message'])

    def test_late_observation_cannot_overwrite_finished_task(self):
        engine=SimpleNamespace(lock=threading.RLock(),save=Mock())
        task={'busy':False,'phase':'verified'}
        progress.observe_call(engine,task,{'stage':'native_calculate'})
        self.assertEqual(task,{'busy':False,'phase':'verified'})
        engine.save.assert_not_called()

    def test_retained_session_dispatches_solve_once_with_bound_progress_identity(self):
        from sw_mcp.conversation.task_engine import ConversationSession
        from sw_mcp.conversation import mate_worker
        session=ConversationSession.__new__(ConversationSession)
        session.runtime=self.folder;session.on_progress=self.values.append;session.persist_ownership=Mock()
        with patch.object(mate_worker.Session,'call',return_value={'native_returned':True}) as native:
            result=session.call('run_user_study',run_id=self.run,model_id='model',study='test',duration_s=1,output_fps=30)
        self.assertTrue(result['native_returned'])
        native.assert_called_once_with('run_user_study',run_id=self.run,job_id=self.run,model_id='model',study='test',duration_s=1,output_fps=30)
        self.assertEqual(session.persist_ownership.call_count,2)
        self.assertEqual(session.persist_ownership.call_args.args,({},))

    def test_owner_stage_and_cleanup_never_relabel_old_native_observation_as_current(self):
        engine=SimpleNamespace(lock=threading.RLock(),save=Mock())
        task={'busy':True,'phase':'verified','native_stage':'native_calculate',
              'progress':{'native_progress_observed':True,'verification_passed':True,'stage':'native_calculate'}}
        progress.observe_stage(engine,task,'closing','closing')
        self.assertFalse(task['progress']['native_progress_observed'])
        self.assertEqual(task['progress']['stage_source'],'task_owner_stage')
        progress.observe_call(engine,task,{'stage':'native_call_pending','stage_started_at':time.time(),
            'native_completion_proven_by_observer':False,'stage_source':'owner_wait_heartbeat_only'})
        self.assertTrue(task['progress']['verification_passed'])
        self.assertFalse(task['progress']['native_completion_proven_by_observer'])


if __name__=='__main__':unittest.main(verbosity=2)
