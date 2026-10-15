import asyncio
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import shutil
import uuid
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge, CadError
from sw_mcp.replay_diagnostics import read
from sw_mcp.artifacts import ArtifactError


class WorkspaceTemporaryDirectory:
    def __init__(self,dir):
        self.boundary=Path(dir).resolve();self.path=self.boundary/uuid.uuid4().hex[:8];self.path.mkdir();self.name=str(self.path)
    def cleanup(self):
        if self.path.resolve().parent!=self.boundary or self.path.is_symlink():raise RuntimeError('Unsafe test cleanup path')
        shutil.rmtree(self.path)

class PublicQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_summary_ignores_observation_limit_and_labels_scope(self):
        import motion_server as server
        with patch.object(server.artifacts,'summary',return_value={'run_id':'a'*32}) as summary,patch.object(server.artifacts,'save_observations') as observations:
            result=await server.get_run_artifacts(run_id='a'*32,limit=3)
        data=json.loads(result.content[0].text);self.assertFalse(data['limit_applied']);self.assertEqual(data['query_scope'],'run_summary');summary.assert_called_once();observations.assert_not_called()
    async def test_run_summary_does_not_silently_ignore_semantic_arguments(self):
        import motion_server as server
        for values in ({'cursor':'other'},{'operation_id':'x'},{'include_file_hashes':True}):
            with patch.object(server.artifacts,'summary') as summary:
                with self.assertRaisesRegex(Exception,'run_id'):await server.get_run_artifacts(run_id='a'*32,**values)
                summary.assert_not_called()
    async def test_observation_pagination_keeps_actual_limit(self):
        import motion_server as server
        with patch.object(server.artifacts,'save_observations',return_value={'ok':True}) as method:
            await server.get_run_artifacts(model_id='user_'+'a'*32,limit=3)
        self.assertEqual(method.call_args.args[2],3)
    async def test_explicit_replay_pagination_is_offline(self):
        import motion_server as server
        with patch.object(server.artifacts,'replay_diagnostics',return_value={'ok':True}) as method,patch.object(server,'call') as cad:
            await server.get_run_artifacts(run_id='a'*32,replay_diagnostics=True,limit=20,cursor='test')
        method.assert_called_once_with('a'*32,20,'test');cad.assert_not_called()
    async def test_virtual_conversion_requires_explicit_option(self):
        import motion_server as server
        source=next((ROOT/'tests').glob('*.py'))
        with patch.object(server,'enqueue') as queue,patch.object(server.Path,'suffix',new_callable=unittest.mock.PropertyMock,return_value='.sldasm'):
            await server.import_assembly(str(source))
            self.assertFalse(queue.call_args.args[1]['materialize_virtual_components'])
            await server.import_assembly(str(source),materialize_virtual_components=True)
            self.assertTrue(queue.call_args.args[1]['materialize_virtual_components'])

class StartupSelectionTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'runs/kulisse-unit';base.mkdir(parents=True,exist_ok=True);self.temp=WorkspaceTemporaryDirectory(dir=base);self.root=Path(self.temp.name);self.bridge=Bridge(self.root)
    def tearDown(self):
        from transport_cleanup import drain_bridge
        drain_bridge(self.bridge);self.temp.cleanup()
    def test_selection_does_not_modify_parent_environment(self):
        with patch.dict(os.environ,{'SW_MCP_PROCESS_ID':'999'}):
            self.bridge.select_startup_session('auto');self.assertEqual(os.environ['SW_MCP_PROCESS_ID'],'999')
        self.assertEqual(self.bridge._selected_startup_pid,'auto');self.assertFalse(self.bridge._ever_dispatched)
    def test_invalid_selection_never_acquires_lease_or_writes(self):
        for selected in ('0','-1','2147483648','01','123abc',False):
            with self.assertRaises(CadError):self.bridge.select_startup_session(selected)
        self.assertFalse((self.root/'runs').exists())
    def test_prior_dispatch_and_unknown_journal_block_correction(self):
        self.bridge._ever_dispatched=True
        with self.assertRaises(CadError):self.bridge.select_startup_session('auto')
        self.bridge._ever_dispatched=False;(self.root/'runs').mkdir();path=self.root/'runs/executor-state.json';path.write_text('{"status":"unknown","request_id":"keep"}')
        before=path.read_bytes()
        with self.assertRaises(CadError):self.bridge.select_startup_session('auto')
        self.assertEqual(path.read_bytes(),before)
    def test_alive_and_successful_handshakes_are_not_reset(self):
        from unittest.mock import Mock
        self.bridge._process=Mock();self.bridge._process.poll.return_value=None
        with self.assertRaises(CadError):self.bridge.select_startup_session('auto')
        self.bridge._process.poll.return_value=0;self.bridge._startup.set_result({'protocol_version':1,'ready':True,'process_id':22})
        with self.assertRaises(CadError):self.bridge.select_startup_session('auto')
        self.bridge._process=None
    def test_explicit_correction_after_failed_handshake_dispatches_only_to_new_process(self):
        helper=self.root/'helper.py';helper.write_text('''import json,os,sys
if os.environ.get('SW_MCP_PROCESS_ID')!='auto':
 print(json.dumps({'protocol_version':1,'ready':False,'error':{'code':'COM_SESSION_ID_MISMATCH','message':'controlled'}}),flush=True);sys.exit(1)
print(json.dumps({'protocol_version':1,'ready':True,'process_id':22}),flush=True)
for line in sys.stdin:
 r=json.loads(line);print(json.dumps({'id':r['id'],'ok':True,'result':{'selected':'auto'}}),flush=True)
''',encoding='utf-8');exe=self.root/'executor/bin/SwExecutor.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'test marker')
        actual=subprocess.Popen
        with patch.dict(os.environ,{'SW_MCP_PROCESS_ID':'999'}),patch('sw_mcp.bridge.subprocess.Popen',side_effect=lambda *a,**kw:actual([sys.executable,str(helper)],**kw)):
            with self.assertRaises(CadError) as failure:self.bridge.request('get_environment')
            self.assertEqual(failure.exception.code,'COM_SESSION_ID_MISMATCH')
            self.bridge._process.wait(timeout=5);self.bridge.select_startup_session('auto');result=self.bridge.request('get_environment')
            self.assertEqual(result['selected'],'auto');self.assertTrue(self.bridge._ever_dispatched)
            with self.assertRaises(CadError):self.bridge.select_startup_session('23')

class ReplayArtifactTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'runs/kulisse-unit';base.mkdir(parents=True,exist_ok=True);self.temp=WorkspaceTemporaryDirectory(dir=base);self.root=Path(self.temp.name);self.run='a'*32;self.attempt='b'*32;self.folder=self.root/'runs'/self.run;self.folder.mkdir(parents=True)
        self.full=self.folder/f'replay-components-{self.attempt}.json';data={'schema_version':1,'run_id':self.run,'attempt_id':self.attempt,'frame':30,'components':[{'instance':str(i),'severity_tolerance_ratio':0} for i in range(6)]};self.full.write_text(json.dumps(data));meta={'run_id':self.run,'attempt_id':self.attempt,'frame':30,'checked_component_count':6,'within_pose_tolerance':True,'component_diagnostics_artifact':{'file':self.full.name,'sha256':hashlib.sha256(self.full.read_bytes()).hexdigest(),'component_count':6}};(self.folder/'replay-check.json').write_text(json.dumps(meta))
    def tearDown(self):self.temp.cleanup()
    def test_small_assembly_full_rows_and_pagination(self):
        self.assertEqual(read(self.root,self.run,20)['returned_diagnostic_count'],6)
        first=read(self.root,self.run,3);second=read(self.root,self.run,3,first['next_cursor']);self.assertEqual([r['instance'] for r in first['components']+second['components']],[str(i) for i in range(6)]);self.assertIsNone(second['next_cursor'])
    def test_modified_data_never_returns_verified_rows(self):
        self.full.write_text('tampered')
        with self.assertRaises(ArtifactError):read(self.root,self.run)
    def test_cursor_binds_exact_replay_hash(self):
        page=read(self.root,self.run,3);data=json.loads(self.full.read_text());data['components'][0]['instance']='changed';self.full.write_text(json.dumps(data));p=self.folder/'replay-check.json';meta=json.loads(p.read_text());meta['component_diagnostics_artifact']['sha256']=hashlib.sha256(self.full.read_bytes()).hexdigest();p.write_text(json.dumps(meta))
        with self.assertRaises(ArtifactError):read(self.root,self.run,3,page['next_cursor'])
    def test_legacy_replay_missing_full_rows_is_explicit(self):
        (self.folder/'replay-check.json').write_text(json.dumps({'run_id':self.run,'components':[]}))
        with self.assertRaises(ArtifactError) as e:read(self.root,self.run)
        self.assertEqual(e.exception.code,'REPLAY_DIAGNOSTICS_NOT_RECORDED')

if __name__=='__main__':unittest.main()
