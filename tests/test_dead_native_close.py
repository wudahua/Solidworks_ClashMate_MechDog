import copy,os,pathlib,threading,tempfile,subprocess,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp.conversation import dead_native_close as d,core

class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);folder=pathlib.Path(self.temp.name);runtime=folder/'native'
        self.cad=SimpleNamespace(pid=101,poll=Mock(return_value=1));self.executor=SimpleNamespace(pid=202,poll=Mock(return_value=None))
        self.state={'request_id':'a'*32,'last_response_request_id':'a'*32,'owner_id':'owner','executor_pid':202,'solidworks_pid':101,'model_id':'model','operation':'inspect_model','journal_derived_fields_consistent':True,'status':'unknown'}
        self.record={'request_id':'a'*32,'owner_id':'owner','model_id':'model','operation':'inspect_model','response_sha256':'recorded_hash'}
        self.bridge=SimpleNamespace(_process=self.executor,_state_lock=threading.RLock(),_pending={},_quarantined_request=None,_owner_id='owner',recovery_state=lambda:copy.deepcopy(self.state),get_request_result=lambda rid:copy.deepcopy(self.record))
        self.session=SimpleNamespace(proc=self.cad,bridge=self.bridge,folder=folder,runtime=runtime,model='model',checkpoint='cp',current_call_for_observation={},pending_native_response=None,persist_ownership=Mock(),unknown=True,ended=False,import_restored=False)
        self.task={'task_id':'b'*32,'model_id':'model','server_pid':os.getpid(),'busy':False,'error':{'code':'RESTORATION_FAILED'}}
        self.ownership={'owner':{'pid':os.getpid(),'created':'1'},'CAD':{'pid':101,'created':'2'},'executor':{'pid':202,'created':'3'},'model_id':'model','runtime':str(runtime),'in_flight':{}}
        self.write();self.identity=patch.object(d,'same_process',side_effect=lambda v:{'status':'exited' if v['pid']==101 or v['pid']==202 and self.executor.poll() is not None else 'same'});self.identity.start();self.addCleanup(self.identity.stop)
    def write(self):core.write(self.session.folder/'活会话归属.json',self.ownership)
    def review(self):return d.review(self.task,self.session)
    def test_completed_failure_and_retained_cad_exit_are_eligible_without_restore(self):
        r=self.review();self.assertTrue(r['eligible']);self.assertEqual(r['CAD_exit_code'],1);self.assertFalse(r['restoration_verified']);self.assertEqual(r['CAD_calls'],0)
    def test_running_cad_must_not_be_closed(self):self.cad.poll.return_value=None;self.assertFalse(self.review()['eligible'])
    def test_busy_task_is_not_retired(self):self.task['busy']=True;self.assertFalse(self.review()['eligible'])
    def test_pending_request_is_not_retired(self):self.bridge._pending={'inflight':object()};self.assertFalse(self.review()['eligible'])
    def test_quarantined_request_is_not_retired(self):self.bridge._quarantined_request='pending';self.assertFalse(self.review()['eligible'])
    def test_session_late_response_is_not_abandoned(self):self.session.pending_native_response={'request_id':'a'*32};self.assertFalse(self.review()['eligible'])
    def test_wrong_model_cannot_reuse_another_task_response(self):self.record['model_id']='foreign';self.assertFalse(self.review()['eligible'])
    def test_absent_response_hash_is_not_completion(self):self.record.pop('response_sha256');self.assertFalse(self.review()['eligible'])
    def test_last_response_must_match_current_request(self):self.state['last_response_request_id']='c'*32;self.assertFalse(self.review()['eligible'])
    def test_owner_must_match_original_process(self):self.ownership['owner']['pid']+=1;self.write();self.assertFalse(self.review()['eligible'])
    def test_missing_creation_identity_is_not_pid_ownership(self):self.ownership['executor'].pop('created');self.write();self.assertFalse(self.review()['eligible'])
    def test_reused_executor_pid_is_not_signalled(self):
        with patch.object(d,'same_process',side_effect=lambda v:{'status':'pid_reused' if v['pid']==202 else 'exited' if v['pid']==101 else 'same'}):self.assertFalse(self.review()['eligible'])
    def test_reused_cad_pid_is_not_closed_or_contacted(self):
        with patch.object(d,'same_process',side_effect=lambda v:{'status':'pid_reused' if v['pid']==101 else 'same'}):self.assertTrue(self.review()['eligible'])
    def test_ownership_inflight_must_be_empty(self):self.ownership['in_flight']={'operation':'write'};self.write();self.assertFalse(self.review()['eligible'])
    def test_unknown_process_observation_blocks_eof(self):
        with patch.object(d,'same_process',return_value={'status':'unknown'}):self.assertFalse(self.review()['eligible'])
    def test_false_derived_state_blocks_eof(self):self.state['journal_derived_fields_consistent']=False;self.assertFalse(self.review()['eligible'])
    def test_finish_only_calls_normal_executor_release_and_preserves_failure(self):
        engine=SimpleNamespace(_source_review=Mock(return_value={'unchanged':True}),_settle_closed=Mock(),save=Mock())
        with patch('sw_mcp.conversation.task_engine.release_executor',return_value={'confirmed':True,'executor_exit_code':0}) as eof:
            d.finish(engine,self.task,self.session)
        eof.assert_called_once_with(self.bridge,self.session.folder);self.assertIsNone(self.session.bridge);self.assertIsNone(self.session.proc)
        self.assertEqual(self.task['phase'],'closed_unverified');self.assertEqual(self.task['original_failure']['code'],'RESTORATION_FAILED')
        finish=engine._settle_closed.call_args.args[1];self.assertEqual(finish['restoration_status'],'not_verified');self.assertFalse(finish['previous_task_passed']);self.assertEqual(finish['CAD_calls'],0)
    def test_unconfirmed_executor_exit_keeps_lease_and_task_active(self):
        engine=SimpleNamespace(_source_review=Mock(),_settle_closed=Mock(),save=Mock())
        with patch('sw_mcp.conversation.task_engine.release_executor',side_effect=core.StopBatch('EXECUTOR_EXIT_UNCONFIRMED')):
            with self.assertRaises(core.StopBatch):d.finish(engine,self.task,self.session)
        self.assertIs(self.session.bridge,self.bridge);engine._settle_closed.assert_not_called()
    def released(self):
        self.executor.poll.return_value=0;self.session.bridge=None;self.session.released_executor_bridge=self.bridge
        self.receipt={'executor_pid':202,'ownership':'retained_Bridge_Popen','confirmed':True,'executor_exit_code':0,'force_kill':False}
        core.write(self.session.folder/'执行器收尾.json',self.receipt)
    def test_already_eof_executor_and_later_cad_exit_are_retirable(self):
        self.released();r=self.review();self.assertTrue(r['eligible']);self.assertTrue(r['executor_already_released']);self.assertEqual(r['CAD_calls'],0)
    def test_receipt_cannot_replace_original_retained_executor_handle(self):
        self.released();self.session.released_executor_bridge=None;self.assertFalse(self.review()['eligible'])
    def test_released_but_running_executor_is_not_retired(self):
        self.released();self.executor.poll.return_value=None;self.assertFalse(self.review()['eligible'])
    def test_nonzero_or_unconfirmed_or_foreign_exit_receipt_is_refused(self):
        for key,value in [('executor_exit_code',1),('confirmed',False),('executor_pid',999),('force_kill',True),('ownership','lookup_PID')]:
            with self.subTest(key=key):
                self.released();self.receipt[key]=value;core.write(self.session.folder/'执行器收尾.json',self.receipt);self.assertFalse(self.review()['eligible'])
    def test_missing_released_receipt_cannot_be_inferred_from_process_exit(self):
        self.released();(self.session.folder/'执行器收尾.json').unlink();self.assertFalse(self.review()['eligible'])
    def test_released_executor_does_not_skip_bound_response_validation(self):
        self.released();self.record['model_id']='foreign';self.assertFalse(self.review()['eligible'])
    def test_released_executor_process_identity_must_be_confirmed_exited(self):
        self.released()
        with patch.object(d,'same_process',side_effect=lambda v:{'status':'exited' if v['pid']==101 else 'same'}):self.assertFalse(self.review()['eligible'])
    def test_finish_after_eof_does_not_signal_or_reopen_executor(self):
        self.released();engine=SimpleNamespace(_source_review=Mock(return_value={'unchanged':True}),_settle_closed=Mock(),save=Mock())
        with patch('sw_mcp.conversation.task_engine.release_executor') as eof:d.finish(engine,self.task,self.session)
        eof.assert_not_called();self.assertIsNone(self.session.released_executor_bridge);self.assertEqual(self.task['phase'],'closed_unverified')
        self.assertEqual(engine._settle_closed.call_args.args[1]['executor_exit'],self.receipt)
