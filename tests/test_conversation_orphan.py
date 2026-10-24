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
        self.ownership={'owner':{'pid':state['server_pid'],'created':'old-owner'},'CAD':{'pid':101,'created':'old-CAD'},
            'executor':{'pid':102,'created':'old-executor'},'runtime':str(self.runtime),'model_id':state['model_id'],
            'native_unknown':False,'in_flight':{},'committed':False}
        core.write(self.folder/'活会话归属.json',self.ownership)
        self.journal=self.runtime/'runs/executor-state.json'
        core.write(self.journal,{'status':'idle','recovery_required':False,'executor_pid':102,'solidworks_pid':101})
        self.other=TaskEngine(self.root,self.root/'work',HERE.parents[1]/'runs/cr',FakeSession)
        self.observer=patch('sw_mcp.conversation.process_identity.same_process',return_value={'status':'exited'});self.observer.start()
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
            with patch('sw_mcp.conversation.process_identity.same_process',return_value={'status':status}):
                with self.assertRaises(core.StopBatch) as e:self.other.finish(self.tid,True)
            self.assertEqual(e.exception.code,'ORPHAN_RESOURCE_NOT_CONFIRMED_EXITED')
        self.assertFalse(self.other.get(self.tid)['closed'])

    def test_pending_or_previously_executed_work_remains_blocked(self):
        self.ownership['in_flight']={'operation':'import_assembly'};core.write(self.folder/'活会话归属.json',self.ownership)
        with self.assertRaises(core.StopBatch):self.other.finish(self.tid,True)
        self.ownership['in_flight']={};core.write(self.folder/'活会话归属.json',self.ownership)
        self.other.tasks[self.tid]['execution_consumed']=True
        with self.assertRaises(core.StopBatch):self.other.finish(self.tid,True)

    def test_changed_source_or_unknown_journal_remains_blocked(self):
        self.source.write_bytes(b'changed')
        with self.assertRaises(core.StopBatch) as e:self.other.finish(self.tid,True)
        self.assertEqual(e.exception.code,'SOURCE_CHANGED')
        self.source.write_bytes(b'fixture source')
        core.write(self.journal,{'status':'unknown','recovery_required':True,'executor_pid':102,'solidworks_pid':101})
        with self.assertRaises(core.StopBatch):self.other.finish(self.tid,True)

    def test_pid_reuse_does_not_unlock_foreign_executor(self):
        with patch('sw_mcp.conversation.process_identity.same_process',return_value={'status':'pid_reused'}),patch('sw_mcp.conversation.startup_gate.observe',return_value={'status':'occupied'}):
            with self.assertRaises(core.StopBatch) as e:self.other.finish(self.tid,True)
        self.assertEqual(e.exception.code,'ORPHAN_EXECUTOR_GATE_NOT_IDLE')


if __name__=='__main__':unittest.main(verbosity=2)
