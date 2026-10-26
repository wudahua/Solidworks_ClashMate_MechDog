"""Explicit failure-record retirement, with no native recovery or process termination."""
import os
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from sw_mcp.conversation.task_engine import TaskEngine,HERE,core
from test_conversation_tasks import FakeSession


class OrphanCloseTests(unittest.TestCase):
    def setUp(self):
        self.root=HERE.parents[1]/'runs/dialogue-fixtures'/uuid.uuid4().hex[:8];self.root.mkdir(parents=True)
        self.source=self.root/'models/case.SLDASM';self.source.parent.mkdir();self.source.write_bytes(b'fixture source')
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':str(HERE.parents[1]/'runs/l')});self.env.start()
        self.first=TaskEngine(self.root,self.root/'work',HERE.parents[1]/'runs/cr',FakeSession)
        tid=self.first.prepare(str(self.source))['task_id']
        for _ in range(100):
            state=self.first.get(tid)
            if not state['busy']:break
            time.sleep(.01)
        self.tid=tid;state=self.first.tasks[tid];state.update(phase='awaiting_confirmation',plan_token='one-use')
        self.first.save(state)
        self.runtime=self.root/'old-runtime';self.folder=Path(state['directory'])/'session'
        self.ownership={'owner':{'pid':state['server_pid'],'created':'100'},'CAD':{'pid':101,'created':'101'},
            'executor':{'pid':102,'created':'102'},'runtime':str(self.runtime),'model_id':state['model_id'],
            'native_unknown':False,'in_flight':{},'committed':False}
        core.write(self.folder/'活会话归属.json',self.ownership)
        self.journal=self.runtime/'runs/executor-state.json'
        core.write(self.journal,{'status':'idle','recovery_required':False,'executor_pid':102,'solidworks_pid':101})
        self.other=TaskEngine(self.root,self.root/'work',HERE.parents[1]/'runs/cr',FakeSession)
        self.observer=patch('sw_mcp.conversation.orphan_close.same_process',return_value={'status':'exited'});self.observer.start()
        self.gate=patch('sw_mcp.conversation.startup_gate.observe',return_value={'status':'available'});self.gate.start()
    def tearDown(self):
        self.observer.stop();self.gate.stop();self.first.shutdown();self.other.shutdown();self.env.stop()

    def test_requires_explicit_unrestored_close_confirmation(self):
        with self.assertRaises(core.StopBatch) as e:self.other.finish(self.tid)
        self.assertEqual(e.exception.code,'ORPHAN_CLOSE_CONFIRMATION_REQUIRED')
        self.assertFalse(self.other.get(self.tid)['closed'])

    def test_safe_exit_closes_failed_record_without_claiming_restore(self):
        with patch.object(FakeSession,'restore') as restore:
            value=self.other.finish(self.tid,True)
            restore.assert_not_called()
        self.assertTrue(value['closed'])
        state=self.other.get(self.tid)
        self.assertEqual(state['phase'],'closed_unverified');self.assertTrue(state['plan_token_revoked'])
        self.assertIsNone(state['finish']['restoration']);self.assertFalse(state['finish']['previous_task_passed'])
        self.assertIsNone(state['finish']['native_exit']['exit_code']);self.assertFalse(self.other.prior_unfinished)
        self.assertTrue((Path(state['directory'])/'关闭前原任务状态.json').is_file())
        self.assertTrue(self.other.finish(self.tid)['closed'])
        fresh=self.other.prepare(str(self.source))['task_id'];self.assertNotEqual(fresh,self.tid)

    def test_live_or_unknown_resource_remains_blocked(self):
        for status in ['same','unknown']:
            with patch('sw_mcp.conversation.orphan_close.same_process',return_value={'status':status}):
                with self.assertRaises(core.StopBatch) as e:self.other.finish(self.tid,True)
            self.assertEqual(e.exception.code,'ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED')
        self.assertFalse(self.other.get(self.tid)['closed'])

    def test_unexecuted_alignment_choice_can_retire_only_after_original_resources_exit(self):
        self.other.tasks[self.tid]['phase']='alignment_choice_required'
        with patch.object(FakeSession,'restore') as restore:
            result=self.other.finish(self.tid,True);restore.assert_not_called()
        self.assertTrue(result['closed']);self.assertFalse(result['result']['previous_task_passed'])

    def test_unexecuted_stationary_scope_review_can_retire_without_restore_claim(self):
        self.other.tasks[self.tid]['phase']='scope_review_required'
        result=self.other.finish(self.tid,True)
        self.assertTrue(result['closed']);self.assertFalse(result['result']['previous_task_passed'])
        self.assertIsNone(result['result']['restoration'])

    def test_stale_pending_and_executed_work_can_only_retire_after_all_resources_end(self):
        self.ownership.update(in_flight={'operation':'inspect_model'},native_unknown=True,committed=True)
        core.write(self.folder/'活会话归属.json',self.ownership)
        self.other.tasks[self.tid].update(execution_consumed=True,phase='failed',error={'code':'CAD_TIMEOUT'})
        self.other.save(self.other.tasks[self.tid])
        core.write(self.journal,{'status':'active','recovery_required':True,'executor_pid':102,'solidworks_pid':101})
        journal_hash=core.digest(self.journal)
        with patch.object(FakeSession,'restore') as restore,patch.object(FakeSession,'close') as close:
            result=self.other.finish(self.tid,True)
            restore.assert_not_called();close.assert_not_called()
        self.assertTrue(result['closed']);self.assertEqual(core.digest(self.journal),journal_hash)
        state=self.other.get(self.tid);self.assertEqual(state['phase'],'closed_unverified')
        self.assertEqual(state['original_failure']['code'],'CAD_TIMEOUT')
        self.assertFalse(state['finish']['previous_task_passed']);self.assertIsNone(state['finish']['restoration'])
        self.assertTrue(state['execution_consumed']);self.assertTrue(state['plan_token_revoked'])
        self.assertNotEqual(self.other.prepare(str(self.source))['task_id'],self.tid)

    def test_source_change_does_not_erase_resource_close_or_claim_pass(self):
        self.source.write_bytes(b'changed')
        result=self.other.finish(self.tid,True)
        self.assertTrue(result['closed']);state=self.other.get(self.tid)
        self.assertEqual(state['phase'],'closed_source_changed');self.assertEqual(state['error']['code'],'SOURCE_CHANGED')
        self.assertFalse(state['finish']['source_files_unchanged']);self.assertFalse(state['finish']['next_round_allowed'])
        self.assertFalse(self.other.prior_unfinished)

    def test_historical_unknown_journal_can_retire_but_wrong_binding_cannot(self):
        core.write(self.journal,{'status':'unknown','recovery_required':True,'executor_pid':999,'solidworks_pid':101})
        with self.assertRaises(core.StopBatch):self.other.finish(self.tid,True)
        self.assertFalse(self.other.get(self.tid)['closed'])
        core.write(self.journal,{'status':'unknown','recovery_required':True,'executor_pid':102,'solidworks_pid':101})
        self.assertTrue(self.other.finish(self.tid,True)['closed'])

    def test_each_live_or_unknown_resource_blocks_even_when_CAD_exited(self):
        for role,pid in [('owner',self.ownership['owner']['pid']),('CAD',101),('executor',102)]:
            for status in ('same','unknown'):
                with self.subTest(role=role,status=status),patch('sw_mcp.conversation.orphan_close.same_process',
                        side_effect=lambda identity,pid=pid,status=status:{'status':status if identity['pid']==pid else 'exited'}):
                    with self.assertRaises(core.StopBatch) as error:self.other.finish(self.tid,True)
                    self.assertEqual(error.exception.code,'ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED')
                    self.assertFalse(self.other.tasks[self.tid]['closed'])

    def test_owner_model_and_creation_identity_must_be_bound(self):
        for field,value in [('owner',{'pid':-1,'created':'100'}),('model_id','foreign'),('CAD',{'pid':101,'created':True})]:
            with self.subTest(field=field):
                bad={**self.ownership,field:value};core.write(self.folder/'活会话归属.json',bad)
                with self.assertRaises(core.StopBatch):self.other.finish(self.tid,True)
                self.assertFalse(self.other.tasks[self.tid]['closed'])

    def test_missing_or_malformed_proof_get_returns_actionable_read_only_review(self):
        (self.folder/'活会话归属.json').write_text('{bad',encoding='utf8')
        state=self.other.get(self.tid)
        self.assertFalse(state['orphan_review']['archive_eligible'])
        self.assertTrue(state['next_action']['arguments']['collect_evidence'])
        self.assertEqual(state['orphan_review']['CAD_calls'],0)
        with self.assertRaises(core.StopBatch):self.other.finish(self.tid,True)

    def test_historical_error_is_labeled_without_mutating_snapshot(self):
        task=self.other.tasks[self.tid]
        task.update(phase='failed',native_stage='restored',error={'code':'CAD_TIMEOUT','native_unknown':True,
            'next_action':{'tool':'get_recovery_state'}})
        self.other.save(task);before=core.digest(Path(task['directory'])/'任务状态.json')
        state=self.other.get(self.tid)
        self.assertEqual(state['error']['code'],'CAD_TIMEOUT')
        self.assertFalse(state['error_context']['current_get_request_failed'])
        self.assertEqual(state['historical_errors'][0]['error']['code'],'CAD_TIMEOUT')
        self.assertEqual(state['next_action']['tool'],'finish_mechanism_task')
        self.assertFalse(state['next_action']['arguments']['keep_result'])
        self.assertEqual(core.digest(Path(task['directory'])/'任务状态.json'),before)
        self.assertFalse(self.other.tasks[self.tid]['closed'])

    def test_restored_stage_alone_is_not_completed_close_proof(self):
        self.other.tasks[self.tid].update(native_stage='restored')
        self.assertTrue(self.other.finish(self.tid,True)['closed'])
        state=self.other.get(self.tid)
        self.assertIsNone(state['finish']['restoration']);self.assertFalse(state['finish']['session']['import_checkpoint_restored'])

    def test_prior_task_refusal_names_blocker_and_archive_route(self):
        from sw_mcp.task_errors import task_failure
        with self.assertRaises(core.StopBatch) as error:self.other.prepare(str(self.source))
        proof=error.exception.diagnostics
        self.assertEqual(proof['blocking_tasks'][0]['task_id'],self.tid)
        failure=task_failure(error.exception.code,str(error.exception),proof)
        self.assertEqual(failure['next_action']['arguments']['task_id'],self.tid)
        self.assertEqual(failure['next_action']['recovery_state_query']['tool'],'get_mechanism_task')
        self.assertFalse(failure['next_action']['archive_confirmation']['arguments']['keep_result'])

    def test_evidence_includes_only_bound_external_runtime_journal(self):
        from sw_mcp.conversation.evidence_bundle import collect
        import zipfile,json
        result=collect(self.other.work,self.tid)
        label='tasks/task-'+self.tid+'/external-runtime/旧执行器日志.json'
        with zipfile.ZipFile(result['zip_path']) as z:
            self.assertEqual(z.read(label),self.journal.read_bytes())
            manifest=json.loads(z.read('证据文件校验.json'))
            self.assertTrue(manifest['bound_runtime_journal_captures'][0]['binding_verified'])
            self.assertIn('tasks/task-'+self.tid+'/采集时资源核对.json',z.namelist())
        core.write(self.journal,{'status':'idle','executor_pid':999,'solidworks_pid':101})
        result=collect(self.other.work,self.tid)
        with zipfile.ZipFile(result['zip_path']) as z:self.assertNotIn(label,z.namelist())

    def test_stale_busy_snapshot_does_not_leave_closed_record_busy(self):
        self.other.tasks[self.tid].update(busy=True,phase='running',execution_consumed=True)
        self.other.save(self.other.tasks[self.tid])
        self.assertTrue(self.other.finish(self.tid,True)['closed'])
        self.assertFalse(self.other.tasks[self.tid]['busy'])

    def test_clean_never_started_native_case_requires_dead_owner_and_clean_history(self):
        t=self.other.tasks[self.tid];t['model_id']=None;self.other.save(t)
        self.ownership.update(model_id=None,CAD=None,executor=None)
        core.write(self.folder/'活会话归属.json',self.ownership)
        self.assertTrue(self.other.finish(self.tid,True)['closed'])
        self.assertFalse(self.other.get(self.tid)['finish']['native_exit']['native_started'])

    def test_unknown_bootstrap_missing_native_identity_stays_blocked(self):
        t=self.other.tasks[self.tid];t['model_id']=None;self.other.save(t)
        self.ownership.update(model_id=None,CAD=None,executor=None,native_unknown=True,in_flight={'operation':'boot'})
        core.write(self.folder/'活会话归属.json',self.ownership)
        with self.assertRaises(core.StopBatch) as error:self.other.finish(self.tid,True)
        self.assertEqual(error.exception.code,'ORPHAN_RESOURCE_IDENTITY_MISSING')
        self.assertFalse(t['closed'])

    def test_pid_reuse_does_not_unlock_foreign_executor(self):
        with patch('sw_mcp.conversation.orphan_close.same_process',return_value={'status':'pid_reused'}),patch('sw_mcp.conversation.startup_gate.observe',return_value={'status':'occupied'}):
            with self.assertRaises(core.StopBatch) as e:self.other.finish(self.tid,True)
        self.assertEqual(e.exception.code,'ORPHAN_EXECUTOR_GATE_NOT_IDLE')


if __name__=='__main__':unittest.main(verbosity=2)
