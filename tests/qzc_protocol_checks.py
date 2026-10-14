"""Real MCP stdio: operation history and saved native BMPs in quarantine."""
import argparse, asyncio, hashlib, json, shutil, sys
from pathlib import Path
from mcp import Client,StdioServerParameters
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sw_mcp.bridge import Bridge


async def main(directory):
    directory=Path(directory).resolve();directory.relative_to(ROOT/'runs/mechanism-feedback-audit')
    native=json.loads((directory/'qzc-native.json').read_text(encoding='utf-8-sig'));assert native['completed']
    steps={s['name']:s['data'] for s in native['steps']};model=steps['import']['model_id'];run=native['run_id'];operation=steps['drive']['save_observation']['operation_id']
    protected=hashlib.sha256((ROOT/'runs/executor-state.json').read_bytes()).hexdigest()
    shutil.copyfile(ROOT/'motion_server.py',directory/'motion_server.py');(directory/'sw_mcp').mkdir(exist_ok=True)
    for source in (ROOT/'sw_mcp').glob('*.py'):shutil.copyfile(source,directory/'sw_mcp'/source.name)
    bridge=Bridge(directory);bridge._journal({'status':'unknown','model_id':model,'owner_id':'protocol_test','executor_pid':None,'solidworks_pid':None});bridge.close()
    report={'all_passed':False,'native_root':str(directory),'run_id':run,'model_id':model}
    async with Client(StdioServerParameters(command=sys.executable,args=[str(directory/'motion_server.py')],cwd=directory)) as client:
        tools={tool.name:tool for tool in (await client.list_tools()).tools};assert len(tools)==24
        assert 'saved_image_only' in tools['replay_motion_frame'].input_schema['properties']
        assert 'operation_id' in tools['get_run_artifacts'].input_schema['properties']
        state=(await client.call_tool('get_recovery_state',{})).structured_content;assert state['status']=='unknown' and state['current_request_state']=='unconfirmed'
        records=(await client.call_tool('get_run_artifacts',{'model_id':model,'operation_id':operation})).structured_content
        assert records['scope']=='recorded_stages_of_one_operation' and records['returned']==steps['drive']['save_observation']['stage_count']
        assert all('file_hashes' not in r and r['artifact_integrity']=='verified' for r in records['stages'])
        full=(await client.call_tool('get_run_artifacts',{'model_id':model,'operation_id':operation,'include_file_hashes':True})).structured_content;assert all('file_hashes' in r for r in full['stages'])
        summary=(await client.call_tool('get_run_artifacts',{'run_id':run})).structured_content
        assert summary['saved_frame_images']['total']==3 and summary['current_model_validity']=='not_checked_offline'
        saved=(await client.call_tool('replay_motion_frame',{'run_id':run,'frame':15,'saved_image_only':True})).structured_content['result']
        assert saved['artifact_integrity']=='verified' and saved['fresh_cad_replay_performed'] is False and Path(saved['image_path']).is_file()
        missing=await client.call_tool('replay_motion_frame',{'run_id':run,'frame':1,'saved_image_only':True});assert missing.is_error and missing.structured_content['error']['code']=='SAVED_FRAME_IMAGE_NOT_FOUND'
        guarded=await client.call_tool('replay_motion_frame',{'run_id':run,'frame':15});assert guarded.is_error and guarded.structured_content['error']['code']=='RECOVERY_REQUIRED'
        report.update(all_passed=True,tool_count=len(tools),save_stage_count=records['returned'],save_response_bytes=len(json.dumps(records,ensure_ascii=False).encode()),saved_images=3,saved_image_read_without_COM=True,unknown_state_guard_kept=True,missing_image_not_synthesized=True,source_root_journal_unchanged=hashlib.sha256((ROOT/'runs/executor-state.json').read_bytes()).hexdigest()==protected)
    assert report['source_root_journal_unchanged']
    (directory/'qzc-protocol.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('native_root');args=parser.parse_args();asyncio.run(main(args.native_root))
