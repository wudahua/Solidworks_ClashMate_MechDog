import copy,pathlib,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from sw_mcp.conversation import core,constraint_inventory as inv


def component(i):
    return {'component_id':'c'+str(i),'instance':'零件-'+str(i),'transform':[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0],
            'fixed_component':i==0,'document_type':1,'parent_component_id':None,'loaded':True,'suppressed':False}


def inspection(n=150):
    return {'components':[component(i) for i in range(n)],'mates':[{'native_feature_id':i} for i in range(30)],
            'mate_health':{'error_count':0},'source_files_unchanged':True,'configuration':'Default'}


def layers(n=2):
    return {'inventory_complete':True,'source_files_unchanged':True,
            'layers':[{'component_id':'c'+str(i),'instance':'子组-'+str(i),'document_path':'copy/'+str(i)+'.SLDASM',
                       'scope_selectable':False,'native_rigid':i!=0,'internal_direct_components':3} for i in range(n)]}


class AdmissionTests(unittest.TestCase):
    def test_exact_write_limit_retains_existing_geometric_workflow(self):
        self.assertEqual(inv.blockers({'components':128,'blockers':[]}),[])
    def test_large_count_is_readonly_without_raising_write_limit(self):
        row=inv.blockers({'components':150})[0]
        self.assertEqual(row['observed_nodes'],150);self.assertEqual(row['write_limit'],128)
    def test_flexible_is_readonly_even_when_small(self):
        b=inv.blockers({'components':12,'blockers':['FLEXIBLE_SUBASSEMBLY_NOT_VALIDATED 滑台-1']})
        self.assertEqual(b[0]['code'],'FLEXIBLE_SUBASSEMBLY_WRITE_UNVALIDATED')
    def test_unrelated_preflight_blockers_are_not_silently_reclassified(self):
        self.assertEqual(inv.blockers({'components':10,'blockers':['MATE_ERROR']}),[])


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=core.no_links(pathlib.Path(self.temp.name));self.folder=self.root/'task'/'session';self.folder.mkdir(parents=True)
        self.s=SimpleNamespace(folder=self.folder,model='user_'+'a'*32,call=Mock())
        self.pre={'components':150,'blockers':['FLEXIBLE_SUBASSEMBLY_NOT_VALIDATED 滑台-1'],'mate_health':{'error_count':0}}
        self.original=inspection();self.native=layers();self.s.call.side_effect=[self.original,self.native]
        self.t={'task_id':'a'*32,'directory':str(self.folder.parent),'phase':'constraint_review_ready','task_kind':'assembly_constraints'}
    def discover(self):
        value=inv.discover(self.s,self.pre)
        self.t.update(connection_review=value['connection_review'])
        inv.publish(SimpleNamespace(),self.t,value)
        return value
    def test_readonly_calls_only_full_inspection_and_layer_observation(self):
        self.discover()
        self.assertEqual([c.args[0] for c in self.s.call.call_args_list],['inspect_model','_survey_connection_layers'])
        self.assertEqual(self.s.call.call_args_list[0].kwargs['detail_level'],'full')
    def test_restore_baseline_is_exact_full_native_frame_not_compact_page(self):
        self.discover();self.assertIs(self.s.initial_inspection,self.original)
        self.assertEqual(len(self.s.initial_inspection['mates']),30)
        self.assertEqual(len(self.s.initial_inspection['components']),150)
    def test_health_is_not_mate_sufficiency_or_write_permission(self):
        value=self.discover();r=value['connection_review']
        self.assertFalse(r['write_scope_allowed']);self.assertFalse(r['complete']);self.assertIsNone(r['all_mates_sufficient'])
        self.assertEqual(r['native_mate_health']['error_count'],0)
        self.assertFalse(value['connection_draft']['candidate_search_performed'])
    def test_all_frozen_components_can_be_paged_without_native_calls(self):
        value=self.discover();self.s.call.reset_mock();page=value['constraint_structure']['pages']['components']
        rows=list(page['rows']);seen=set()
        while page['next_cursor']:
            cursor=page['next_cursor'];self.assertNotIn(cursor,seen);seen.add(cursor)
            page=inv.page(self.t,cursor)['constraint_structure_page'];rows.extend(page['rows'])
        self.assertEqual(len(rows),150);self.assertEqual(len({r['component_id'] for r in rows}),150)
        self.assertFalse(page['all_structure_pages_completed']);self.s.call.assert_not_called()
    def test_component_last_page_does_not_consume_layer_sibling_queue(self):
        self.native['layers']=layers(40)['layers'];value=self.discover()
        pending=value['constraint_structure']['pending_queries']
        self.assertEqual(len(pending),2);layer_cursor=pending[1]['arguments']['structure_cursor']
        cursor=pending[0]['arguments']['structure_cursor']
        while cursor:
            page=inv.page(self.t,cursor)['constraint_structure_page'];cursor=page['next_cursor']
        other=inv.page(self.t,layer_cursor)['constraint_structure_page']
        self.assertEqual(other['collection'],'layers');self.assertEqual(other['range_start'],16)
        self.assertEqual(other['total_count'],40);self.assertFalse(other['all_structure_pages_completed'])
    def test_cursor_cannot_cross_tasks(self):
        value=self.discover();cursor=value['constraint_structure']['pages']['components']['next_cursor']
        other=copy.deepcopy(self.t);other['directory']=str(self.root/'other');(self.root/'other/session').mkdir(parents=True)
        core.write(self.root/'other/session'/inv.SNAPSHOT,core.read(self.folder/inv.SNAPSHOT))
        with self.assertRaises(core.StopBatch):inv.page(other,cursor)
    def test_changed_snapshot_does_not_rebind_to_new_cursor(self):
        value=self.discover();cursor=value['constraint_structure']['pages']['components']['next_cursor']
        snapshot=core.read(self.folder/inv.SNAPSHOT);snapshot['components'][0]['instance']='changed';core.write(self.folder/inv.SNAPSHOT,snapshot)
        with self.assertRaises(core.StopBatch) as e:inv.page(self.t,cursor)
        self.assertEqual(e.exception.code,'CONNECTION_EVIDENCE_FAILED')
    def test_missing_snapshot_returns_structured_evidence_refusal(self):
        value=self.discover();cursor=value['constraint_structure']['pages']['components']['next_cursor'];(self.folder/inv.SNAPSHOT).unlink()
        with self.assertRaises(core.StopBatch) as e:inv.page(self.t,cursor)
        self.assertEqual(e.exception.code,'CONNECTION_EVIDENCE_FAILED')
    def test_invalid_offsets_and_draft_cursor_are_not_accepted(self):
        value=self.discover();sid=value['constraint_structure']['snapshot_id']
        for cursor in (sid+':components:0',sid+':components:17',sid+':components:160',sid+':16',sid+':unknown:16','bad'):
            with self.subTest(cursor=cursor),self.assertRaises(core.StopBatch):inv.page(self.t,cursor)
    def test_oversized_or_unobserved_count_stops_before_native_inspection(self):
        for n in (501,0,None,True,'150'):
            self.pre['components']=n
            with self.subTest(n=n),self.assertRaises(core.StopBatch):inv.discover(self.s,self.pre)
        self.s.call.assert_not_called()
    def test_mismatched_count_and_duplicate_identity_are_not_inventoried_complete(self):
        for original in (inspection(149),inspection(150)):
            if len(original['components'])==150:original['components'][1]['component_id']='c0'
            self.s.call.side_effect=[original,self.native]
            with self.assertRaises(core.StopBatch):inv.discover(self.s,self.pre)
    def test_layer_outside_component_set_is_rejected(self):
        self.native['layers'][0]['component_id']='foreign'
        with self.assertRaises(core.StopBatch):self.discover()
    def test_changed_source_or_incomplete_layer_set_is_rejected(self):
        for changes in ({'source_files_unchanged':False},{'inventory_complete':False}):
            native=layers();native.update(changes);self.s.call.side_effect=[inspection(),native]
            with self.assertRaises(core.StopBatch):self.discover()
    def test_fixed_flags_do_not_collapse_into_world_fixed(self):
        self.original['components'][1].update(parent_component_id='c0',fixed_component=False,parent_document_fixed_component=True)
        value=self.discover();c=value['constraint_structure']['pages']['components']['rows'][1]
        self.assertFalse(c['fixed_component']);self.assertTrue(c['parent_document_fixed_component'])
    def test_no_default_confirmation_for_readonly_inventory(self):
        self.discover();self.assertFalse(self.t['confirmation_required'])
        self.assertNotIn('plan_token',self.t);self.assertEqual(self.t['next_action']['tool'],'get_mechanism_task')
    def test_write_guard_rejects_readonly_task(self):
        self.discover()
        with self.assertRaises(core.StopBatch) as e:inv.require_write_scope(self.t)
        self.assertEqual(e.exception.code,'CONNECTION_SCOPE_UNSUPPORTED')
    def test_ordinary_task_is_not_reclassified_by_guard(self):
        inv.require_write_scope({'connection_review':{'complete':True}})
    def test_sequence_start_rejected_before_native_session_check(self):
        from sw_mcp.conversation import assembly_sequence
        self.discover();engine=SimpleNamespace(_require_session=Mock())
        with self.assertRaises(core.StopBatch):assembly_sequence.start(engine,self.t)
        engine._require_session.assert_not_called()
    def test_execute_rejected_before_token_consumption(self):
        from sw_mcp.conversation import connection_task
        self.discover();engine=SimpleNamespace(_require_session=Mock())
        with self.assertRaises(core.StopBatch):connection_task.execute(engine,self.t,'invented',True,True,False)
        engine._require_session.assert_not_called();self.assertNotIn('execution_consumed',self.t)
    def test_plan_cannot_select_layer_or_form_geometric_goals(self):
        from sw_mcp.conversation import connection_task
        self.discover();engine=SimpleNamespace(_require_session=Mock(),sessions={self.t['task_id']:self.s})
        for options in ({'assembly_scope_hint':'子组-1'},{'intents':[{'component_a':'a','component_b':'b','kind':'rigid'}]}):
            with self.assertRaises(core.StopBatch):connection_task.propose(engine,self.t,**({'intents':None}|options))
    def test_plan_without_goals_can_only_read_saved_structure(self):
        from sw_mcp.conversation import connection_task
        self.discover();engine=SimpleNamespace(_require_session=Mock(),sessions={self.t['task_id']:self.s});self.s.call.reset_mock()
        value=connection_task.propose(engine,self.t,None)
        self.assertTrue(value['readonly_structure']);self.assertFalse(value['confirmation_token_created']);self.s.call.assert_not_called()
    def test_subclass_get_cursor_bypasses_native_get_and_dispatch(self):
        from sw_mcp.conversation.motion_tasks import MotionTaskEngine
        value=self.discover();cursor=value['constraint_structure']['pages']['components']['next_cursor']
        engine=SimpleNamespace(tasks={self.t['task_id']:self.t});self.s.call.reset_mock()
        result=MotionTaskEngine.get(engine,self.t['task_id'],structure_cursor=cursor)
        self.assertEqual(result['constraint_structure_page']['range_start'],16);self.s.call.assert_not_called()

    def test_discovery_branch_does_not_start_geometry_for_large_or_flexible_input(self):
        from sw_mcp.conversation import connection_task
        self.s.import_preflight=self.pre;self.s.state=Mock()
        value=connection_task.discover(self.s)
        self.assertEqual(value['connection_review']['mode'],'readonly_structure')
        self.assertNotIn('_survey_assembly_connections',[c.args[0] for c in self.s.call.call_args_list])

    def test_task_publication_retains_readonly_next_action_and_false_write_permission(self):
        from sw_mcp.conversation.motion_tasks import MotionTaskEngine
        value=inv.discover(self.s,self.pre);engine=SimpleNamespace(sessions={self.t['task_id']:self.s})
        with patch('sw_mcp.conversation.connection_task.source_integrity.bind'):
            MotionTaskEngine._proposals(engine,self.t,value)
        self.assertEqual(self.t['phase'],'constraint_review_ready');self.assertFalse(self.t['connection_review']['write_scope_allowed'])
        self.assertEqual(self.t['next_action']['arguments']['task_id'],self.t['task_id'])
        self.assertIn('structure_cursor',self.t['next_action']['arguments'])

    def test_sequence_after_prepare_cannot_select_readonly_child_scope(self):
        from sw_mcp.conversation import assembly_sequence as sequence
        self.discover();sid='b'*32;self.t.update(assembly_sequence_id=sid,assembly_sequence_step=0)
        engine=SimpleNamespace(work=self.root,save=Mock())
        core.write(sequence._path(engine,sid),{'sequence_id':sid,'current_step':0,'status':'preparing_layer',
            'steps':[{'task_id':self.t['task_id'],'instance':'子组-1'}]})
        with patch('sw_mcp.conversation.connection_task.select_scope') as selected:
            sequence.after_prepare(engine,self.t,self.s)
        selected.assert_not_called();value,_=sequence._load(engine,self.t)
        self.assertEqual(value['status'],'blocked_readonly_layer')

    def test_draft_cursor_is_not_reused_as_structure_cursor(self):
        from sw_mcp.conversation.task_engine import TaskEngine
        self.discover();engine=SimpleNamespace(tasks={self.t['task_id']:self.t})
        with self.assertRaises(core.StopBatch) as e:TaskEngine.get(engine,self.t['task_id'],draft_cursor='invented')
        self.assertEqual(e.exception.code,'CONNECTION_SCOPE_UNSUPPORTED')


if __name__=='__main__':unittest.main()
