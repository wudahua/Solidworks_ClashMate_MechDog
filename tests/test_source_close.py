"""Frozen CAD sources and completed native-close retirement; no CAD in fixtures."""
import os,time,uuid,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from sw_mcp.conversation import core,source_integrity,completed_close
from sw_mcp.conversation.task_engine import TaskEngine
from test_conversation_tasks import FakeSession

ROOT=Path(__file__).resolve().parents[1]


class SourceCloseTests(unittest.TestCase):
    def setUp(self):
        self.root=ROOT/'runs/source-close-tests'/uuid.uuid4().hex[:8]
        self.source=self.root/'models/case.SLDASM';self.source.parent.mkdir(parents=True);self.source.write_bytes(b'assembly')
        self.part=self.source.parent/'part.SLDPRT';self.part.write_bytes(b'part')
        (self.source.parent/'notes.md').write_text('not a CAD source')
        self.engine=TaskEngine(self.root,self.root/'work',self.root/'runtime',FakeSession)
        self.addCleanup(self.engine.shutdown)
    def wait(self,engine,tid):
        for _ in range(500):
            value=engine.get(tid)
            if not value['busy']:return value
            time.sleep(.005)
        self.fail('timeout')
    def prepared(self):
        tid=self.engine.prepare(str(self.source))['task_id'];self.assertEqual(self.wait(self.engine,tid)['phase'],'proposal_ready')
        return tid,self.engine.tasks[tid]
    def completed_failure(self):
        tid,t=self.prepared();s=self.engine.sessions[tid];s.ended=True;s.unknown=True
        t.update(phase='failed',execution_consumed=True,error={'code':'SOURCE_CHANGED'},verification={'declared_scope_passed':True})
        self.engine.save(t);runtime=self.root/'retired-runtime';f=Path(t['directory'])/'session'
        ownership={'owner':{'pid':t['server_pid'],'created':'owner'},'CAD':{'pid':101,'created':'CAD'},
            'executor':{'pid':102,'created':'executor'},'runtime':str(runtime),'model_id':t['model_id'],'checkpoint_id':'checkpoint',
            'native_unknown':True,'ended':True,'in_flight':{},'committed':False}
        core.write(f/'活会话归属.json',ownership)
        core.write(f/'会话收尾.json',{'ended':True,'import_checkpoint_restored':True,'finish_mode':'restored_then_closed',
            'model_id':t['model_id'],'checkpoint_id':'checkpoint','runtime':str(runtime)})
        core.write(f/'exit.json',{'owned_pid':101,'native_process_exited':True,'normal_zero_exit':True,'exit_code':0})
        core.write(f/'执行器收尾.json',{'executor_pid':102,'confirmed':True,'executor_exit_code':0})
        core.write(runtime/'runs/executor-state.json',{'status':'idle','recovery_required':False,'executor_pid':102,'solidworks_pid':101})
        return tid,t,s,ownership
    def observations(self,same_owner):
        return patch('sw_mcp.conversation.completed_close.same_process',side_effect=lambda identity:
            {'status':'same' if same_owner and identity['pid']==os.getpid() else 'exited'})
    def test_non_CAD_additions_and_changes_do_not_break_finish_or_second_round(self):
        tid,t=self.prepared();self.assertNotIn('notes.md',t['source_hashes'])
        (self.source.parent/'notes.md').write_text('host memory changed')
        out=self.source.parent/'out2';out.mkdir();(out/'curve.csv').write_text('0,0')
        self.engine.finish(tid);state=self.wait(self.engine,tid)
        self.assertTrue(state['closed']);self.assertTrue(state['finish']['source_files_unchanged']);self.assertIsNone(self.engine.active)
        self.assertIn('out2/curve.csv',[v['path'] for v in state['finish']['source_integrity']['added']])
        self.assertNotIn('notes.md',[v['path'] for v in state['finish']['source_integrity']['added']])
        self.assertTrue(self.engine.finish(tid)['closed'])
        self.assertNotEqual(self.prepared()[0],tid)
    def test_legacy_workspace_baseline_ignores_new_non_CAD_files(self):
        tid,t=self.prepared();t['source_hashes']=core.fixture_hashes(self.source)
        (self.source.parent/'extra.csv').write_text('0,0')
        self.assertTrue(source_integrity.review(t)['unchanged'])
    def test_actual_changed_missing_inputs_have_hash_diagnostics_and_close_receipt(self):
        tid,t=self.prepared();before=core.digest(self.source)
        self.source.write_bytes(b'changed assembly');self.part.unlink()
        self.engine.finish(tid);state=self.wait(self.engine,tid)
        self.assertTrue(state['closed']);self.assertEqual(state['phase'],'closed_source_changed')
        self.assertEqual(state['error']['code'],'SOURCE_CHANGED');self.assertIsNone(self.engine.active)
        proof=state['finish'];self.assertTrue(proof['session']['ended']);self.assertTrue(proof['native_exit']['normal_zero_exit'])
        self.assertFalse(proof['source_files_unchanged']);self.assertFalse(proof['next_round_allowed'])
        diff=state['error']['diagnostics'];self.assertEqual(diff['changed'][0]['before_sha256'],before)
        self.assertEqual(diff['changed'][0]['after_sha256'],core.digest(self.source));self.assertEqual(len(diff['missing']),1)
    def test_exact_import_dependencies_include_external_and_no_unrelated_CAD(self):
        tid,t=self.prepared();s=self.engine.sessions[tid];s.model='user_'+'a'*32;s.runtime=self.root/'native'
        external=self.root/'external.SLDPRT';external.write_bytes(b'external')
        data={'source_hashes':{str(self.source):core.digest(self.source),str(external):core.digest(external)}}
        core.write(s.runtime/'experiments/user_assemblies'/('a'*32)/'import-evidence.json',data)
        source_integrity.bind(t,s);self.part.write_bytes(b'unrelated')
        self.assertTrue(source_integrity.review(t)['unchanged'])
        external.write_bytes(b'changed');self.assertEqual(len(source_integrity.review(t)['changed']),1)
    def test_import_binding_cannot_rebase_changed_assembly(self):
        tid,t=self.prepared();s=self.engine.sessions[tid];s.model='user_'+'b'*32;s.runtime=self.root/'native'
        self.source.write_bytes(b'changed')
        core.write(s.runtime/'experiments/user_assemblies'/('b'*32)/'import-evidence.json',{'source_hashes':{str(self.source):core.digest(self.source)}})
        with self.assertRaises(core.StopBatch) as error:source_integrity.bind(t,s)
        self.assertEqual(error.exception.code,'SOURCE_CHANGED');self.assertNotIn('source_dependency_hashes',t)
    def test_native_hyphenated_uppercase_hashes_are_canonicalized_strictly(self):
        tid,t=self.prepared();s=self.engine.sessions[tid];s.model='user_'+'c'*32;s.runtime=self.root/'native'
        digest=core.digest(self.source);native='-'.join(digest[i:i+2].upper() for i in range(0,64,2))
        core.write(s.runtime/'experiments/user_assemblies'/('c'*32)/'import-evidence.json',{'source_hashes':{str(self.source):native}})
        source_integrity.bind(t,s);self.assertEqual(t['source_dependency_hashes'][str(self.source)],digest)
        self.assertTrue(source_integrity.review(t)['unchanged'])
        for bad in ('-'.join(digest),native+'-',native[:-1],digest+'00',None):
            self.assertIsNone(source_integrity.normalized_hash(bad))
    def test_post_close_audit_exception_retains_receipts_and_releases_active(self):
        tid,t=self.prepared()
        with patch('sw_mcp.conversation.source_integrity.review',side_effect=OSError('fixture inaccessible')):
            self.engine.finish(tid);state=self.wait(self.engine,tid)
        self.assertTrue(state['closed']);self.assertTrue(state['finish']['session']['ended'])
        self.assertFalse(state['finish']['source_files_unchanged']);self.assertIsNone(self.engine.active)
    def test_get_does_not_latch_native_unknown_after_already_completed_close(self):
        tid,t,s,_=self.completed_failure();s.unknown=False;s.require_live_idle=Mock(side_effect=AssertionError('must not inspect dead connection'))
        state=self.engine.get(tid);s.require_live_idle.assert_not_called()
        self.assertFalse(s.unknown);self.assertEqual(state['connection_status'],'closed_receipts_pending_review')
    def test_same_owner_explicit_archive_does_not_replay_native_and_allows_next_prepare(self):
        tid,t,s,_=self.completed_failure()
        with self.assertRaises(core.StopBatch):self.engine.finish(tid)
        with self.observations(True),patch('sw_mcp.conversation.startup_gate.observe',return_value={'status':'available'}),patch.object(s,'restore') as restore,patch.object(s,'close') as close:
            self.assertTrue(self.engine.finish(tid,True)['closed']);restore.assert_not_called();close.assert_not_called()
        state=self.engine.get(tid);self.assertTrue(state['verification']['declared_scope_passed'])
        self.assertFalse(state['finish']['previous_task_passed']);self.assertEqual(state['original_failure']['code'],'SOURCE_CHANGED')
        self.assertTrue((Path(t['directory'])/'关闭前原任务状态.json').exists());self.assertIsNone(self.engine.active)
        self.assertNotEqual(self.prepared()[0],tid)
    def test_new_owner_can_archive_executed_task_only_with_complete_close_proof(self):
        tid,t,s,_=self.completed_failure();other=TaskEngine(self.root,self.root/'work',self.root/'runtime',FakeSession);self.addCleanup(other.shutdown)
        with self.observations(False),patch('sw_mcp.conversation.startup_gate.observe',return_value={'status':'available'}):
            self.assertTrue(other.finish(tid,True)['closed'])
        self.assertFalse(other.prior_unfinished);self.assertFalse(other.get(tid)['finish']['previous_task_passed'])
    def test_incomplete_or_mismatched_close_proof_never_unlocks_executed_task(self):
        tid,t,s,ownership=self.completed_failure();f=Path(t['directory'])/'session'
        mutations=[('native_unknown_only',None),('pending',{'operation':'run_motion_study'}),('model_mismatch',None)]
        for mode,pending in mutations:
            value=dict(ownership)
            if mode=='native_unknown_only':value['ended']=False
            if mode=='pending':value['in_flight']=pending
            if mode=='model_mismatch':value['model_id']='foreign'
            core.write(f/'活会话归属.json',value)
            with self.observations(True),patch('sw_mcp.conversation.startup_gate.observe',return_value={'status':'available'}):
                with self.assertRaises(core.StopBatch):self.engine.finish(tid,True)
            self.assertFalse(t['closed']);self.assertEqual(self.engine.active,tid)
    def test_live_or_unknown_resources_and_non_idle_journal_still_block(self):
        tid,t,s,ownership=self.completed_failure()
        for status in ('same','unknown'):
            with patch('sw_mcp.conversation.completed_close.same_process',return_value={'status':status}):
                with self.assertRaises(core.StopBatch):self.engine.finish(tid,True)
        core.write(Path(ownership['runtime'])/'runs/executor-state.json',{'status':'unknown','recovery_required':True})
        with self.observations(True):
            with self.assertRaises(core.StopBatch):self.engine.finish(tid,True)
        self.assertFalse(t['closed'])
    def test_keep_result_also_tolerates_workspace_additions_and_preserves_source_error(self):
        from sw_mcp.conversation.motion_tasks import MotionTaskEngine
        for changed in (False,True):
            with self.subTest(changed=changed):
                class ResultSession(FakeSession):
                    def close(s):
                        result=super().close();result.update(import_checkpoint_restored=False,committed_copy_preserved=True)
                        return result
                e=MotionTaskEngine(self.root,self.root/('keep-'+str(changed)),self.root/'runtime',ResultSession)
                self.addCleanup(e.shutdown)
                # The fake recommendation is a concentric fixture; here only
                # the verified-result finish branch is exercised without CAD.
                with patch('sw_mcp.conversation.startup_gate.require_idle'):
                    tid=e.prepare(str(self.source),task_kind='concentric')['task_id']
                self.wait(e,tid);t=e.tasks[tid];s=e.sessions[tid]
                t.update(phase='verified',task_kind='motion',verification={'declared_scope_passed':True})
                s.runtime=self.root/'result-runtime';result=s.runtime/(tid+'.SLDASM');result.parent.mkdir(exist_ok=True);result.write_bytes(b'owned result')
                core.write(s.folder/'导入.json',{'path':str(result)})
                (self.source.parent/'curve.csv').write_text('0,0')
                if changed:self.source.write_bytes(b'changed before closing')
                e.finish(tid,keep_result=True);state=self.wait(e,tid)
                self.assertTrue(state['closed']);self.assertIsNone(e.active)
                self.assertEqual(state['finish']['restoration_status'],'not_requested_result_preserved')
                self.assertEqual(state['finish']['source_files_unchanged'],not changed)
                self.assertEqual(state['finish']['result_assembly_sha256'],core.digest(result))
    def test_managed_recovery_refusal_identifies_blocking_task_and_phase(self):
        from types import SimpleNamespace
        from sw_mcp.conversation.formal_engine import FormalEngine
        from sw_mcp.conversation.owner_transport import fingerprint
        tid,t,s,_=self.completed_failure();e=FormalEngine.__new__(FormalEngine)
        e.tasks=self.engine;e.source_fingerprint=fingerprint();e.managed_upgrade_guard=False
        e.product=SimpleNamespace(bridge=SimpleNamespace(_process=None),jobs=SimpleNamespace(_jobs={}),artifacts=object())
        with self.assertRaises(core.StopBatch) as raised:e.tool('get_recovery_state',{})
        self.assertEqual(raised.exception.code,'MANAGED_RUNTIME_NOT_READY')
        self.assertEqual(raised.exception.diagnostics['task_id'],tid)
        self.assertEqual(raised.exception.diagnostics['phase'],'failed')
        self.assertEqual(raised.exception.diagnostics['next_tool'],'get_mechanism_task')


if __name__=='__main__':unittest.main(verbosity=2)
