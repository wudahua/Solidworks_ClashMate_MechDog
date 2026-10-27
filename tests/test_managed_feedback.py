"""Upgrade refusals and task presentation retain actionable, unmodified evidence."""
import hashlib,json,uuid,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from scripts.upgrade import package_files,UpgradeFailure,idle_installation
from sw_mcp.conversation.task_views import present
from sw_mcp.conversation.task_engine import TaskEngine,core
from transport_cleanup import remove_test_root
from test_alpha5 import contents

ROOT=Path(__file__).resolve().parents[1]


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.base=ROOT/'runs/managed-feedback-tests';self.root=self.base/uuid.uuid4().hex[:8];self.root.mkdir(parents=True)
        self.addCleanup(remove_test_root,self.root,self.base)

    def package(self,extra=0,root='Solidworks_ClashMate_MechDog'):
        p=self.root/'source.zip';files=contents()
        for i in range(extra):files[f'发布说明_v0.1-alpha.{i}.md']=b'historical note'
        with zipfile.ZipFile(p,'w') as z:
            for name,data in files.items():z.writestr(root+'/'+name,data)
        p.with_suffix('.zip.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  source.zip\n')
        return p

    def test_historical_tag_extras_are_listed_and_never_silently_admitted(self):
        p=self.package(46);before=p.read_bytes()
        with self.assertRaises(UpgradeFailure) as caught:package_files(p)
        value=caught.exception.payload();self.assertEqual(value['code'],'UPGRADE_PACKAGE_INVALID')
        d=value['error']['diagnostics'];self.assertEqual(d['unlisted_count'],46)
        self.assertEqual(len(d['unlisted_files']),10);self.assertTrue(d['unlisted_files_truncated'])
        self.assertIn('Assets',value['error']['next_action']['instruction']);self.assertEqual(p.read_bytes(),before)

    def test_auto_generated_root_points_to_release_asset_without_extracting(self):
        p=self.package(root='Solidworks_ClashMate_MechDog-0.4.3-alpha.22')
        with self.assertRaises(UpgradeFailure) as caught:package_files(p)
        self.assertIn('Unexpected ZIP root',str(caught.exception));self.assertFalse(caught.exception.diagnostics['embedded_validator_executed'])
        self.assertEqual(set(x.name for x in self.root.iterdir()),{'source.zip','source.zip.sha256'})

    def test_exact_manifest_package_still_admitted(self):
        manifest,data,digest=package_files(self.package())
        self.assertEqual(set(data),{x['path'] for x in manifest['files']}|{'发布清单.json'})
        self.assertEqual(len(digest),64)

    def test_access_error_adds_existing_journal_hint_without_claiming_holder(self):
        runs=self.root/'runs';runs.mkdir();path=runs/'executor-state.json'
        original=b'{"executor_pid":2147480000,"status":"idle","dispatch_state":"completed","restoration_status":"restored"}';path.write_bytes(original)
        error=PermissionError('fixture access denied');error.winerror=5
        with patch('scripts.upgrade.open_lease_file',side_effect=error):
            with self.assertRaises(UpgradeFailure) as caught:
                with idle_installation(self.root):self.fail('held lock must not admit upgrade')
        d=caught.exception.payload()['error']['next_action']['read_only_executor_review']
        self.assertEqual(d['record']['executor_pid'],2147480000);self.assertFalse(d['holder_identity_proven'])
        self.assertIn('finish_motion_session',d['instruction']);self.assertEqual(path.read_bytes(),original)

    def test_scope_compaction_preserves_all_components_and_every_execution_action(self):
        scope={'pair_issues':[{'input':'a','output':'b','code':'SCOPE','message':'review','diagnostics':{'repeated':['large']*5000}}],
               'constraint_inventory':{'components':[{'component_id':str(i),'instance':'part-'+str(i),'fixed_component':False,'remaining_DOF':None,'constraint_state':{'native_name':'swUnderConstrained'},'mate_links':['detail']*500} for i in range(80)]},
               'stationary_preparation':{'candidates':[{'instance':'part-'+str(i)} for i in range(73)]},'write_dispatched':False}
        value={'directory':str(self.root),'phase':'scope_review_required','scope_review':scope,'requires_stationary_scope_review':True}
        original=json.loads(json.dumps(value));out=present(json.loads(json.dumps(value)))
        self.assertLess(len(json.dumps(out)),40000);self.assertEqual(len(out['scope_review']['constraint_inventory']['components']),80)
        self.assertEqual(len(out['scope_review']['stationary_preparation']['candidate_instances']),73)
        self.assertEqual(value,original)
        actions=[{'kind':'parallel','part':str(i)} for i in range(44)]
        value.update(phase='awaiting_confirmation',plan_token='a'*32,requires_stationary_scope_review=False,
            proposal={'actions':actions,'recommendation':{'constraint_completion':{'actions':actions,'uncompleted_components':[]}}})
        out=present(json.loads(json.dumps(value)));self.assertEqual(out['proposal']['actions'],actions)
        self.assertEqual(out['plan_token'],'a'*32);self.assertFalse(out['scope_review']['active_blocker'])

    def test_planning_old_block_is_labelled_historical_not_current_failure(self):
        out=present({'directory':str(self.root),'phase':'planning','blocking_code':'EXTERNAL_GEAR_SCOPE_UNSUPPORTED'})
        self.assertNotIn('blocking_code',out);self.assertEqual(out['prior_scope_blocking_code'],'EXTERNAL_GEAR_SCOPE_UNSUPPORTED')

    def test_unwatched_planning_query_has_fresh_clock_and_no_previous_wait(self):
        from sw_mcp.conversation.task_progress import current_view
        from types import SimpleNamespace
        import time
        s=SimpleNamespace(folder=self.root,pending_native_response=None)
        core.write(self.root/'活会话归属.json',{'in_flight':{'operation':'_survey_external_gear_pair','started':time.time()-5}})
        value={'phase':'planning','busy':True,'progress':{'operation':'_import_gear_assembly','operation_elapsed_s':80,
            'operation_started_at':time.time()-100,'original_request_wait':{'request_id':'old'}}}
        first=current_view(s,json.loads(json.dumps(value)));time.sleep(.01);second=current_view(s,json.loads(json.dumps(value)))
        self.assertEqual(first['progress']['operation'],'_survey_external_gear_pair')
        self.assertGreater(second['progress']['operation_elapsed_s'],first['progress']['operation_elapsed_s'])
        self.assertEqual(second['progress']['original_request_wait'],{})
        self.assertFalse(second['progress']['native_progress_observed']);self.assertFalse(second['progress']['heartbeat_proves_native_progress'])
        self.assertEqual(value['progress']['operation'],'_import_gear_assembly')

    def test_fresh_clock_preserves_bound_native_sampling_observation(self):
        from sw_mcp.conversation.task_progress import current_view
        from types import SimpleNamespace
        import time
        started=time.time()-5;s=SimpleNamespace(folder=self.root,pending_native_response=None)
        core.write(self.root/'活会话归属.json',{'in_flight':{'operation':'run_user_study','started':started}})
        value={'progress':{'operation':'run_user_study','operation_started_at':started,'stage':'capture_solver_poses',
            'stage_started_at':started+1,'completed_frames':10,'total_frames':51,'sampling_fraction':10/51,'native_progress_observed':True}}
        out=current_view(s,value)
        self.assertEqual(out['progress']['stage'],'capture_solver_poses');self.assertEqual(out['progress']['completed_frames'],10)
        self.assertTrue(out['progress']['native_progress_observed']);self.assertIsNone(out['progress']['estimated_remaining_s'])

    def test_live_progress_uses_committed_memory_without_opening_ownership_file(self):
        from sw_mcp.conversation.task_progress import current_view
        from sw_mcp.conversation.task_engine import ConversationSession
        from types import SimpleNamespace
        import time
        s=SimpleNamespace(folder=self.root,pending_native_response=None,
            current_call_for_observation={'operation':'inspect_model','started':time.time()-3})
        with patch('sw_mcp.conversation.task_progress.core.read',side_effect=AssertionError('poll must not open writer target')):
            out=current_view(s,{'busy':True})
            self.assertEqual(out['progress']['operation'],'inspect_model')
            self.assertTrue(out['progress']['current_native_call'])
            s.current_call_for_observation={}
            out=current_view(s,{'busy':False,'progress':{'original_request_wait':{'request_id':'finished'}}})
            self.assertEqual(out['progress']['original_request_wait'],{})
            self.assertFalse(out['progress']['current_native_call'])
        # The observer must never advance beyond evidence that failed to commit.
        session=object.__new__(ConversationSession)
        session.folder=self.root;session.runtime=self.root/'runtime'
        session.current_call_for_observation={}
        with patch('sw_mcp.conversation.task_engine.core.write',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):session.persist_ownership({'operation':'new_call','started':time.time()})
        self.assertEqual(session.current_call_for_observation,{})

    def test_late_single_solve_never_promotes_whole_task_verified(self):
        from types import SimpleNamespace
        e=TaskEngine(self.root,self.root/'work',self.root/'runtime');self.addCleanup(e.shutdown)
        tid='a'*32;folder=e.work/('task-'+tid);folder.mkdir()
        t={'task_id':tid,'directory':str(folder),'source':'fixture','phase':'failed','busy':False,'closed':False,
           'server_instance_id':e.server_instance_id,'error':{'code':'CAD_TIMEOUT','native_unknown':True}}
        e.tasks[tid]=t;e.active=tid
        proof={'native_state_known':True,'response_ok':True,'whole_task_verified':False}
        s=SimpleNamespace(pending_native_response={'request_id':'b'*32},model='model',late_response_reconciled=proof,require_live_idle=lambda:{'journal_idle':True})
        e.sessions[tid]=s
        with patch('sw_mcp.conversation.managed_wait.reconcile',side_effect=lambda s:setattr(s,'pending_native_response',None)):
            out=e.get(tid)
        self.assertEqual(out['phase'],'incomplete_after_late_response');self.assertNotIn('error',out)
        self.assertEqual(out['original_failure']['code'],'CAD_TIMEOUT');self.assertEqual(out['next_action']['tool'],'finish_mechanism_task')
        self.assertEqual(out['connection_status'],'attached');self.assertNotIn('verification',out)


if __name__=='__main__':unittest.main()
