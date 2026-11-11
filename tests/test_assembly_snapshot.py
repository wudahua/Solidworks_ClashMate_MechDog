"""Frozen task pages reduce dialogue payload without changing CAD admission."""
import asyncio,copy,json,os,subprocess,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp import assembly_connections as joints,assembly_overview as overview,assembly_assessment as assessment,connection_recommendations as drafts
from sw_mcp.conversation import assembly_snapshot as snapshots,core
from sw_mcp.conversation.motion_tasks import MotionTaskEngine
from tests.test_assembly_connections import survey
from tests.test_assembly_constraints import mate

ROOT=Path(__file__).resolve().parents[1]


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'runs/assembly-snapshot-unit'/uuid.uuid4().hex[:10];self.session_dir=self.folder/'session';self.session_dir.mkdir(parents=True)
        self.survey=survey([mate(1,'moving','body','cylindrical_axis')]);self.survey['model_id']='user_'+'c'*32
        for c in self.survey['components']:c['geometry_complete']=True
        self.session=SimpleNamespace(folder=self.session_dir,model=self.survey['model_id'],connection_survey=self.survey,bridge=Mock())
        self.task={'task_id':uuid.uuid4().hex,'directory':str(self.folder),'phase':'constraint_review_ready','busy':False,'closed':False,'task_kind':'assembly_constraints',
                   'connection_review':joints.review(self.survey),'next_action':{'tool':'plan_mechanism_task'}}
        review=self.task['connection_review'];draft=drafts.draft(self.survey,review)
        self.task['connection_draft']=draft
        self.task['assembly_assessment']=assessment.build(self.survey,review,overview.recommend(self.survey,review),draft)
        core.write(self.session_dir/'通用配合原生调查.json',self.survey)
    def publish(self):snapshots.publish_prepare(self.task,self.session);return self.task['assembly_prepare_snapshot']
    def collect(self,entry,kind):
        query=next(q for q in entry['queries'] if (':'+kind+':') in q['arguments']['snapshot_cursor'])
        cursor=query['arguments']['snapshot_cursor'];rows=[];seen=set()
        while cursor:
            self.assertNotIn(cursor,seen);seen.add(cursor)
            result=snapshots.page(self.task,cursor,True);self.assertLessEqual(len(snapshots.encoded(result)),snapshots.PAGE_BYTES)
            self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode('utf-8')),snapshots.PAGE_BYTES)
            page=result['snapshot_page'];self.assertEqual(page['range_start'],len(rows));rows+=page['rows']
            self.assertFalse(page['all_collections_read']);self.assertFalse(page['native_calls']);cursor=page['next_cursor']
        self.assertEqual(len(rows),entry['counts'][kind]);return rows
    def test_full_geometry_stays_bound_while_AI_rows_omit_native_bytes(self):
        entry=self.publish();rows=self.collect(entry,'geometry')
        self.assertEqual(len(rows),sum(len(c.get(k,[])) for c in self.survey['components'] for k in ('cylinders','planes','completion_planes')))
        self.assertNotIn('native_reference"',json.dumps(rows));self.assertTrue(any('native_reference_sha256' in r for r in rows))
        self.assertEqual(core.read(self.session_dir/'通用配合原生调查.json'),self.survey)
        self.session.bridge.request.assert_not_called()
    def test_geometry_truncation_and_search_truncation_are_independent(self):
        self.survey['components'][0]['geometry_complete']=False
        self.task['assembly_assessment']['candidate_search']['all_pair_ranges_read']=False
        core.write(self.session_dir/'通用配合原生调查.json',self.survey);self.publish();brief=self.task['assembly_brief']
        self.assertFalse(brief['geometry_complete_for_captured_scope']);self.assertFalse(brief['candidate_pair_search_complete'])
        self.assertFalse(brief['mechanical_intent_proven']);self.assertFalse(brief['motion_verified'])
    def test_child_fixed_observation_and_selected_coordinate_scope_are_preserved(self):
        c=self.survey['components'][0];c.update(parent_document_fixed_component=True,fixed_flag_observation_scope='parent_document_not_global',parent_component_id='parent')
        self.task['selected_assembly_layer']={'selected_instance':'parent/subasm'}
        core.write(self.session_dir/'通用配合原生调查.json',self.survey);entry=self.publish();rows=self.collect(entry,'components')
        self.assertTrue(rows[0]['parent_document_fixed_component']);self.assertEqual(rows[0]['fixed_flag_observation_scope'],'parent_document_not_global')
        self.assertEqual(self.task['assembly_brief']['selected_scope']['coordinate_frame'],'selected_assembly_document')
        self.assertEqual(self.task['assembly_brief']['selected_scope']['instance'],'parent/subasm')
    def test_large_collection_pages_are_strictly_bounded_and_do_not_drop_siblings(self):
        c=self.survey['components'][0];c['planes']=[{'axis_global':[0,0,1],'reference_point_global_m':[0,0,i*.001],'native_reference':'private'+str(i)} for i in range(77)]
        c['geometry_complete']=False;core.write(self.session_dir/'通用配合原生调查.json',self.survey)
        entry=self.publish();self.assertGreater(entry['counts']['geometry'],77)
        self.collect(entry,'geometry');self.collect(entry,'components')
        self.assertEqual(set(q['arguments']['snapshot_cursor'].split(':')[1] for q in entry['queries']),{k for k,v in entry['counts'].items() if v})
    def test_cached_page_boundaries_are_reused_but_evidence_hashes_still_checked(self):
        c=self.survey['components'][0];c['planes']=[{'axis_global':[0,0,1],'reference_point_global_m':[0,0,i]} for i in range(55)]
        core.write(self.session_dir/'通用配合原生调查.json',self.survey);entry=self.publish()
        with patch.object(snapshots,'_page_offsets',wraps=snapshots._page_offsets) as offsets:self.collect(entry,'geometry')
        self.assertEqual(offsets.call_count,len(entry['counts']))
        cursor=entry['queries'][0]['arguments']['snapshot_cursor'];first=snapshots.page(self.task,cursor)
        first['snapshot_page']['rows'][0]['instance']='caller mutation'
        self.assertNotEqual(snapshots.page(self.task,cursor)['snapshot_page']['rows'][0]['instance'],'caller mutation')
        (self.session_dir/'通用配合原生调查.json').write_bytes(b'changed after cache')
        with self.assertRaises(core.StopBatch):snapshots.page(self.task,cursor)
    def analytic(self):
        self.session.runtime=self.folder/'rt';self.session.runtime.mkdir()
        self.survey['reference_state_signature']='state-frozen'
        artifact=self.session.runtime/'geometry.json'
        core.write(artifact,{'model_id':self.session.model,'reference_state_signature':'state-frozen',
            'rows':[{'instance':'body','component_id':'body','axis_global':[0,0,1],'reference_point_global_m':[0,0,i],
                     'registration_status':'observation_only_not_native_write_reference'} for i in range(40)],
            'analytic_geometry_complete':True,'scope':'analytic_only'})
        self.survey['components'][0]['geometry_complete']=False
        self.survey['geometry_snapshot']={'path':str(artifact),'sha256':core.digest(artifact),'row_count':40}
        core.write(self.session_dir/'通用配合原生调查.json',self.survey)
        return artifact
    def test_complete_analytic_observation_does_not_expand_planner_reference_scope(self):
        self.analytic();entry=self.publish();brief=self.task['assembly_brief']
        self.assertTrue(brief['geometry_complete_for_captured_scope']);self.assertFalse(brief['planner_reference_geometry_complete'])
        self.assertFalse(brief['native_write_references_expanded']);self.assertEqual(brief['analytic_geometry_row_count'],40)
        self.assertEqual(sum(r['collection']=='analytic_faces' for r in self.collect(entry,'geometry')),40)
    def test_analytic_artifact_hash_path_and_copied_evidence_are_checked(self):
        artifact=self.analytic();self.survey['geometry_snapshot']['sha256']='0'*64
        with self.assertRaises(core.StopBatch):self.publish()
        self.survey['geometry_snapshot']['sha256']=core.digest(artifact);entry=self.publish()
        (self.session_dir/'原生批量几何观察.json').write_bytes(b'changed')
        with self.assertRaises(core.StopBatch):snapshots.page(self.task,entry['queries'][0]['arguments']['snapshot_cursor'])
    @unittest.skipUnless(os.name=='nt','Windows .NET compiler required')
    def test_actual_CSharp_world_coordinates_invalid_and_budget_policy(self):
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe';target=self.folder/'policy.exe'
        result=subprocess.run([str(compiler),'/nologo','/out:'+str(target),str(ROOT/'executor/AssemblyGeometrySnapshot.cs'),str(ROOT/'tests/AssemblyGeometrySnapshotTests.cs')],capture_output=True)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode(errors='replace'))
        result=subprocess.run([str(target)],capture_output=True)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode(errors='replace'))
        self.assertIn(b'4 analytic geometry snapshot policy cases passed',result.stdout)
    def test_cross_task_and_changed_source_never_regenerate_or_call_CAD(self):
        entry=self.publish();cursor=entry['queries'][0]['arguments']['snapshot_cursor']
        other=copy.deepcopy(self.task);other['task_id']=uuid.uuid4().hex
        with self.assertRaises(core.StopBatch):snapshots.page(other,cursor)
        self.survey['components'][0]['fixed_component']=False;core.write(self.session_dir/'通用配合原生调查.json',self.survey)
        with self.assertRaises(core.StopBatch) as error:snapshots.page(self.task,cursor)
        self.assertEqual(error.exception.code,'CONNECTION_EVIDENCE_FAILED');self.session.bridge.request.assert_not_called()
    def test_changed_snapshot_and_forged_offset_are_rejected(self):
        entry=self.publish();cursor=entry['queries'][0]['arguments']['snapshot_cursor']
        with self.assertRaises(core.StopBatch):snapshots.page(self.task,cursor[:-1]+'1')
        p=self.folder/entry['path'];snap=core.read(p);snap['collections']['components'][0]['instance']='changed';core.write(p,snap)
        with self.assertRaises(core.StopBatch):snapshots.page(self.task,cursor)
    def plan(self):
        self.publish();self.task.update(phase='awaiting_confirmation',plan_token=uuid.uuid4().hex)
        self.task['proposal']={'goals':[{'component_a':'moving','component_b':'body','kind':'revolute','axis_global':[0,0,1]}],
             'actions':[{'component_a':'moving','component_b':'body','kind':'distance','value':.025,
                         'reference_a':{'native_reference':'private-a','axis_global':[0,0,1]},'reference_b':{'native_reference':'private-b'}}],
             'expected_added_mates':1,'fixed_state_changes':[],'rigid_groups':[{'name':'rotor','anchor':'moving','members':['moving']}],
             'scope':'bounded_trial','completion_scope':'whole_assembly','batches':[{},{}]}
        snapshots.publish_plan(self.task,self.session);return self.task['assembly_plan_snapshot']
    def test_plan_review_contains_exact_change_and_group_membership_not_raw_reference(self):
        entry=self.plan();actions=self.collect(entry,'actions');self.assertEqual(actions[0]['value'],.025)
        self.assertEqual(actions[0]['exact_action_sha256'],snapshots.digest(self.task['proposal']['actions'][0]))
        self.assertNotIn('private-a',json.dumps(actions));self.assertEqual(self.collect(entry,'groups')[0]['member'],'moving')
        self.assertEqual(self.task['assembly_plan_review']['native_batch_count'],2)
    def test_historical_or_owner_lost_plan_page_is_not_current(self):
        entry=self.plan();cursor=entry['queries'][0]['arguments']['snapshot_cursor']
        self.assertFalse(snapshots.page(self.task,cursor)['snapshot_page']['plan_current'])
        self.assertTrue(snapshots.page(self.task,cursor,True)['snapshot_page']['plan_current'])
        self.task['phase']='closed';self.assertFalse(snapshots.page(self.task,cursor,True)['snapshot_page']['plan_current'])
        self.task['phase']='awaiting_confirmation';self.task['execution_consumed']=True
        self.assertFalse(snapshots.page(self.task,cursor,True)['snapshot_page']['plan_current'])
    def test_real_action_shape_keeps_flip_units_and_native_reference_identity_hashes(self):
        self.plan();a=self.task['proposal']['actions'][0]
        a.update(reference_a='native-base64-a',reference_b='native-base64-b',reference_kind_a='datum_plane',reference_kind_b='datum_plane',flip_dimension=True)
        self.task['proposal']['goals'][0]['reference_point_global_m']=[.1,.2,.3]
        snapshots.publish_plan(self.task,self.session);entry=self.task['assembly_plan_snapshot'];row=self.collect(entry,'actions')[0]
        self.assertTrue(row['flip_dimension']);self.assertEqual(row['value_unit'],'m');self.assertEqual(row['reference_kind_a'],'datum_plane')
        self.assertEqual(row['reference_a_sha256'],snapshots.digest('native-base64-a'))
        self.assertEqual(self.collect(entry,'goals')[0]['reference_point_global_m'],[.1,.2,.3])
    def test_summary_preserves_token_but_routes_confirmation_to_full_plan_review(self):
        self.plan();before=copy.deepcopy(self.task);result=snapshots.summary(self.task)
        self.assertEqual(result['plan_token'],self.task['plan_token']);self.assertIn('snapshot_cursor',result['next_action']['arguments'])
        self.assertFalse(result['native_calls']);self.assertEqual(self.task,before)
        self.assertLess(len(snapshots.encoded(result)),10000)
    def test_engine_summary_and_snapshot_need_no_native_session(self):
        entry=self.publish();engine=MotionTaskEngine.__new__(MotionTaskEngine)
        engine.lock=__import__('threading').RLock();engine.tasks={self.task['task_id']:self.task};engine.sessions={};engine.server_instance_id='new'
        result=engine.get(self.task['task_id'],summary_only=True);self.assertFalse(result['task_owner_available'])
        page=engine.get(self.task['task_id'],snapshot_cursor=entry['queries'][0]['arguments']['snapshot_cursor'])
        self.assertFalse(page['snapshot_page']['native_calls'])
        with self.assertRaises(core.StopBatch):engine.get(self.task['task_id'],summary_only=True,draft_cursor='bad')
    def test_large_finish_and_failure_details_remain_available_without_bloating_summary(self):
        self.publish();self.task.update(phase='closed',closed=True,
            error={'code':'CONNECTION_EVIDENCE_FAILED','message':'read saved detail','diagnostics':{'large':['x'*1000]*100}},
            verification={'declared_scope_passed':True,'completed_trials':41,'trials':[{'large':'x'*1000}]*100},
            finish={'cleanup_status':'pass','next_round_allowed':True,'source_files_unchanged':True,
                    'restoration':{'restoration_status':'restored','source_files_unchanged':True,'maximum_transform_delta':0,'large':['x'*1000]*100}})
        before=copy.deepcopy(self.task);result=snapshots.summary(self.task)
        self.assertLess(len(json.dumps(result,ensure_ascii=False).encode('utf-8')),10000)
        self.assertEqual(result['verification']['completed_trials'],41)
        self.assertEqual(result['finish']['restoration']['restoration_status'],'restored')
        self.assertEqual(result['next_action']['arguments'],{'task_id':self.task['task_id']});self.assertEqual(self.task,before)
    def test_frontend_does_not_route_conflicting_snapshot_options_to_evidence(self):
        from sw_mcp.conversation import frontend
        from sw_mcp.validation import StrictMCPServer
        client=SimpleNamespace(call=Mock(),evidence=Mock());mcp=StrictMCPServer('fixture')
        with patch.object(frontend,'OwnerClient',return_value=client):frontend.attach(mcp,ROOT)
        result=asyncio.run(mcp.tool_dispatcher('get_mechanism_task',{'task_id':self.task['task_id'],'collect_evidence':True,'summary_only':True}))
        self.assertTrue(result.is_error);self.assertEqual(result.structured_content['error']['code'],'CONNECTION_INTENT_INVALID')
        client.call.assert_not_called();client.evidence.assert_not_called()
    def test_public_schema_rejects_conflicting_modes_and_forwards_new_parameters(self):
        import motion_server as server
        engine=SimpleNamespace(tasks={self.task['task_id']:{}},get=Mock(return_value={'summary_only':True}))
        with patch.object(server,'_task_engine',engine):
            v=asyncio.run(server.mcp.call_tool('get_mechanism_task',{'task_id':self.task['task_id'],'summary_only':True}))
            self.assertFalse(v.is_error);self.assertTrue(engine.get.call_args.kwargs['summary_only'])
            v=asyncio.run(server.mcp.call_tool('get_mechanism_task',{'task_id':self.task['task_id'],'summary_only':True,'snapshot_cursor':'bad'}))
            self.assertTrue(v.is_error)
        self.assertEqual(engine.get.call_count,1)


class DraftContextTests(unittest.TestCase):
    def sample(self):
        s=survey([]);template=s['components'][1]
        for i in range(7):
            c=copy.deepcopy(template);c.update(component_id='other'+str(i),instance='other'+str(i));s['components'].append(c)
        return s
    def test_multiple_pages_match_original_queries_with_one_pair_graph(self):
        s=self.sample();review=joints.review(s)
        with patch.object(drafts,'MAX_CANDIDATES',1):
            with patch.object(drafts.constraint_graph,'model',wraps=drafts.constraint_graph.model) as graph:
                context=drafts.prepare_context(s,review,'task');cursor='';cached=[]
                for _ in range(8):
                    page=drafts.draft(s,review,cursor=cursor,binding='task',context=context);cached.append(page)
                    cursor=page['next_cursor']
                    if not cursor:break
                self.assertEqual(graph.call_count,1)
            cursor='';uncached=[]
            for _ in range(len(cached)):
                page=drafts.draft(s,review,cursor=cursor,binding='task');uncached.append(page);cursor=page['next_cursor']
        self.assertEqual(cached,uncached);self.assertGreater(len(cached),1)
    def test_changed_snapshot_or_binding_cannot_reuse_context(self):
        s=survey([]);review=joints.review(s);context=drafts.prepare_context(s,review,'first')
        with self.assertRaisesRegex(ValueError,'context_snapshot'):drafts.draft(s,review,binding='second',context=context)
        s['components'][0]['fixed_component']=False
        with self.assertRaisesRegex(ValueError,'context_snapshot'):drafts.draft(s,review,binding='first',context=context)


if __name__=='__main__':unittest.main()
