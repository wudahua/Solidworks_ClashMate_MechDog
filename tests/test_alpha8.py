import sys,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
class MovementBudgetPublicTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_binds_explicit_budget(self):
        import motion_server
        with patch.object(motion_server,'call',new_callable=AsyncMock) as call:
            await motion_server.preview_mate('m','a','b','concentric',maximum_translation_mm=20,maximum_rotation_deg=3)
            self.assertEqual(call.call_args.kwargs['maximum_translation_mm'],20)
            self.assertEqual(call.call_args.kwargs['maximum_rotation_deg'],3)
    async def test_invalid_budget_is_rejected_before_cad_dispatch(self):
        import motion_server
        for mm,deg in [(float('nan'),1),(1,float('inf')),(-1,1),(1,181)]:
            with patch.object(motion_server,'call',new_callable=AsyncMock) as call:
                with self.assertRaises(Exception):await motion_server.preview_mate('m','a','b','concentric',maximum_translation_mm=mm,maximum_rotation_deg=deg)
                call.assert_not_called()
class IdentityRegressionTests(unittest.TestCase):
    def test_probe_journal_stays_bound_to_parent(self):
        import json
        from io import StringIO
        from types import SimpleNamespace
        from concurrent.futures import Future
        from sw_mcp.bridge import Bridge
        from test_service import temporary_workspace
        with temporary_workspace() as folder:
            bridge=Bridge(Path(folder));bridge._startup.set_result({'ready':True,'protocol_version':1,'process_id':22})
            bridge._process=SimpleNamespace(pid=900001,poll=lambda:None,stdin=StringIO())
            future=Future();future.set_result({'ok':True,'result':{'model_id':'user_'+'a'*32}})
            with patch.object(bridge,'_acquire_lease'),patch.object(bridge,'_start'),patch('sw_mcp.bridge.concurrent.futures.Future',return_value=future),patch.object(bridge,'_journal') as journal:
                bridge.request('probe_motion_compatibility',model_id='user_'+'a'*32,run_id='b'*32,checkpoint_id='c'*32)
                self.assertEqual(journal.call_args.args[0]['model_id'],'user_'+'a'*32)
    def test_probe_history_request_journal_uses_saved_parent_model(self):
        import json
        from io import StringIO
        from types import SimpleNamespace
        from concurrent.futures import Future
        from sw_mcp.bridge import Bridge
        from test_service import temporary_workspace
        with temporary_workspace() as folder:
            run=Path(folder)/'runs'/('b'*32);run.mkdir(parents=True)
            (run/'solve.json').write_text(json.dumps({'model_id':'user_'+'c'*32,'parent_model_id':'user_'+'a'*32,'probe_input_scope':'explicit_checkpoint_snapshot_not_current_unsaved_memory'}),encoding='utf-8')
            bridge=Bridge(Path(folder));bridge._startup.set_result({'ready':True,'protocol_version':1,'process_id':22});bridge._process=SimpleNamespace(pid=900001,poll=lambda:None,stdin=StringIO())
            future=Future();future.set_result({'ok':True,'result':{}})
            with patch.object(bridge,'_acquire_lease'),patch.object(bridge,'_start'),patch('sw_mcp.bridge.concurrent.futures.Future',return_value=future),patch.object(bridge,'_journal') as journal:
                bridge.request('get_motion_summary',run_id='b'*32)
                self.assertEqual(journal.call_args.args[0]['model_id'],'user_'+'a'*32)
    def test_probe_terminal_progress_preserves_requested_checkpoint(self):
        from sw_mcp.jobs import Jobs
        from test_service import temporary_workspace
        class Fake:
            cad_operation_state='available'
            def request(self,*args,**kwargs):return {'model_id':kwargs['model_id']}
        with temporary_workspace() as folder:
            jobs=Jobs(Fake(),Path(folder));submitted=jobs.submit('probe_motion_compatibility',{'model_id':'user_'+'a'*32,'checkpoint_id':'c'*32})
            jobs._pool.shutdown(wait=True);job=jobs.get(submitted['job_id'])
            self.assertEqual(job['progress']['checkpoint_id'],'c'*32)
            self.assertEqual(job['progress']['model_id'],'user_'+'a'*32)
if __name__=='__main__':unittest.main()
