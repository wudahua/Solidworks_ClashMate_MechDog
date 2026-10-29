"""Observe a real retained child exit; refuse unrelated/unfinished native state."""
import copy
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp.conversation import core,late_close
from sw_mcp.conversation.task_engine import TaskEngine,ConversationSession


class LateCloseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.work=Path(self.temp.name);self.folder=self.work/'task-test/session'
        self.folder.mkdir(parents=True);self.runtime=self.work/'runtime';self.runtime.mkdir()
        self.child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(.15)'])
        self.addCleanup(self.child.wait)
        self.s=SimpleNamespace(proc=self.child,pending_close_process=self.child,bridge=None,unknown=True,ended=False,
            model='m',checkpoint='c',folder=self.folder,runtime=self.runtime,import_restored=True,committed=False,
            pending_owned_close={'pid':self.child.pid,'model_id':'m','checkpoint_id':'c','import_restored':True,'committed':False},
            persist_ownership=Mock(),pending_native_response=None,require_live_idle=Mock(side_effect=AssertionError('no COM or reconnect')))
        restored={'restoration_status':'restored','source_files_unchanged':True,'maximum_transform_delta':0}
        self.t={'task_id':'a'*32,'directory':str(self.folder.parent),'source':'source.SLDASM','closed':False,'busy':False,
            'phase':'failed','server_instance_id':'owner','task_kind':'assembly_constraints',
            'error':{'code':'OWNED_CAD_EXIT_PENDING_NO_TERMINATION'},'finish':{'restoration':restored}}
        self.engine=TaskEngine.__new__(TaskEngine);e=self.engine
        e.work=self.work;e.server_instance_id='owner';e.tasks={self.t['task_id']:self.t};e.sessions={self.t['task_id']:self.s}
        e.active=self.t['task_id'];e.prior_unfinished=[];e.lock=threading.RLock();e._source_review=Mock(return_value={'unchanged':True})
        self.records={'活会话归属.json':{'CAD':{'pid':self.child.pid},'executor':{'pid':777},'model_id':'m','checkpoint_id':'c','in_flight':{},'pending_native_response':{}},
            '执行器收尾.json':{'executor_pid':777,'confirmed':True,'executor_exit_code':0,'force_kill':False},
            'exit-control-exit.json':{'expected_sw_pid':self.child.pid,'helper_exit_code':0,'termination_performed':False},
            'exit-control.json':{'ok':True,'result':{'pid':self.child.pid,'exit_requested':True}},
            '恢复独立核对.json':{'passed':True}}
        self.write_records()
    def write_records(self):
        for name,value in self.records.items():core.write(self.folder/name,value)
    def run_review(self):return late_close.reconcile(self.engine,self.t,self.s)
    def test_real_retained_child_finishes_original_restore_without_native_replay(self):
        self.child.wait();self.assertTrue(self.run_review())
        self.assertTrue(self.t['closed']);self.assertIsNone(self.engine.active)
        self.assertTrue(self.t['finish']['late_exit_observation']);self.assertEqual(self.t['previous_failure']['code'],'OWNED_CAD_EXIT_PENDING_NO_TERMINATION')
        self.assertEqual(self.t['finish']['native_exit']['exit_code'],0)
        self.s.require_live_idle.assert_not_called();self.assertFalse(self.run_review())
    def test_alive_child_remains_pending_with_no_exit_receipt(self):
        self.child.poll=Mock(return_value=None)
        self.assertFalse(self.run_review());self.assertFalse(self.t['closed']);self.assertFalse((self.folder/'exit.json').exists())
        del self.child.poll
    def test_same_pid_replacement_handle_is_not_authority(self):
        self.s.proc=SimpleNamespace(pid=self.child.pid,poll=Mock(return_value=0))
        self.assertFalse(self.run_review());self.s.proc.poll.assert_not_called()
    def test_only_original_pending_exit_error_and_same_owner_are_eligible(self):
        for key,value in [('server_instance_id','other'),('busy',True),('error',{'code':'CAD_TIMEOUT'})]:
            old=self.t[key];self.t[key]=value;self.assertFalse(self.run_review());self.t[key]=old
        self.s.pending_owned_close=None;self.assertFalse(self.run_review())
    def test_missing_or_mismatched_native_proofs_do_not_clear_unknown(self):
        self.child.wait()
        for name,key,value in [('活会话归属.json','in_flight',{'operation':'apply'}),
                ('执行器收尾.json','executor_pid',888),('执行器收尾.json','executor_exit_code',1),
                ('exit-control-exit.json','expected_sw_pid',999),('exit-control-exit.json','termination_performed',True),
                ('exit-control.json','ok',False),('恢复独立核对.json','passed',False)]:
            original=copy.deepcopy(self.records[name]);self.records[name][key]=value;self.write_records()
            self.assertFalse(self.run_review());self.assertTrue(self.s.unknown)
            self.records[name]=original
        self.write_records();self.s.pending_native_response={'request_id':'x'};self.assertFalse(self.run_review())
    def test_nonzero_exit_preserves_warning_and_source_failure_remains_separate(self):
        self.child.wait()
        exited=subprocess.Popen([sys.executable,'-c','raise SystemExit(7)']);exited.wait()
        self.s.proc=exited;self.s.pending_close_process=exited;self.s.pending_owned_close['pid']=exited.pid
        self.records['活会话归属.json']['CAD']['pid']=exited.pid
        self.records['exit-control-exit.json']['expected_sw_pid']=exited.pid
        self.records['exit-control.json']['result']['pid']=exited.pid;self.write_records()
        self.engine._source_review.return_value={'unchanged':False}
        self.assertTrue(self.run_review());self.assertEqual(self.t['phase'],'closed_source_changed')
        self.assertFalse(self.t['finish']['next_round_allowed']);self.assertEqual(self.t['finish']['native_exit']['exit_code'],7)
        self.assertEqual(self.t['error']['code'],'SOURCE_CHANGED')
    def test_verified_kept_copy_is_bound_to_runtime_and_independent_pose_proof(self):
        self.child.wait();self.s.committed=True;self.s.import_restored=False
        self.s.pending_owned_close.update(committed=True,import_restored=False)
        self.t.update(verification={'declared_scope_passed':True})
        self.t['finish']={'restoration_status':'not_requested_result_preserved','result_checkpoint_restore':{'restoration_status':'restored','source_files_unchanged':True,'maximum_transform_delta':0}}
        model=self.runtime/'copy.SLDASM';model.write_bytes(b'owned copy')
        core.write(self.folder/'导入.json',{'path':str(model)})
        core.write(self.folder/'保留成果核对.json',{'passed':False})
        self.assertFalse(self.run_review());core.write(self.folder/'保留成果核对.json',{'passed':True})
        self.assertTrue(self.run_review());self.assertEqual(self.t['finish']['result_assembly_sha256'],core.digest(model))
        self.assertFalse(self.t['finish']['includes_test_motion_study']);self.assertFalse(self.t['finish']['session']['import_checkpoint_restored'])
    def test_get_integrates_late_exit_and_returns_closed_record(self):
        self.child.wait();value=self.engine.get(self.t['task_id'])
        self.assertTrue(value['closed']);self.assertEqual(value['connection_status'],'closed_record')
        self.s.require_live_idle.assert_not_called()
    def test_get_of_pending_exit_requests_only_observation_not_recovery(self):
        with patch.object(self.child,'poll',return_value=None):value=self.engine.get(self.t['task_id'])
        self.assertTrue(value['native_close_pending']);self.assertFalse(value['closed'])
        self.assertEqual(value['connection_status'],'original_native_exit_pending')
        self.assertNotIn('recovery_action',value);self.s.require_live_idle.assert_not_called()
    def test_finish_can_collect_late_receipt_without_a_second_close(self):
        self.child.wait();value=self.engine.finish(self.t['task_id'])
        self.assertTrue(value['closed']);self.assertFalse(value['replayed'])
        self.s.require_live_idle.assert_not_called()
    def test_close_remembers_original_popen_only_after_specific_wait_expiry(self):
        s=ConversationSession.__new__(ConversationSession);s.__dict__.update(self.s.__dict__)
        s.unknown=False;s.bridge=None
        s.persist_ownership=Mock()
        with patch('sw_mcp.conversation.mate_worker.Session.close',side_effect=core.StopBatch('OWNED_CAD_EXIT_PENDING_NO_TERMINATION')):
            with self.assertRaises(core.StopBatch):ConversationSession.close(s)
        self.assertIs(s.pending_close_process,self.child)
        self.assertEqual(s.pending_owned_close['pid'],self.child.pid)


if __name__=='__main__':unittest.main()
