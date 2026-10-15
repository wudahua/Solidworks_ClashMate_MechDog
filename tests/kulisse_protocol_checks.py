"""Real SDK checks against copied sources and isolated native evidence.

--solidworks-pid opts into read-only connection correction on an existing instance.
Historical checks remain offline; no model is opened, saved or calculated.
"""
import argparse,asyncio,hashlib,json,os,shutil,sys
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1]
def unpack(result):return json.loads(result.content[0].text)
async def run(root,selected):
    native=json.loads((root/'native.json').read_text(encoding='utf-8-sig'));steps={r['name']:r['data'] for r in native['steps']};run_id=steps['motion_61_frames']['run_id']
    shutil.copyfile(ROOT/'motion_server.py',root/'motion_server.py');(root/'sw_mcp').mkdir(exist_ok=True)
    for p in (ROOT/'sw_mcp').glob('*.py'):shutil.copyfile(p,root/'sw_mcp'/p.name)
    if selected:
        target=root/'executor/bin';target.mkdir(parents=True,exist_ok=True)
        for p in (ROOT/'executor/bin').iterdir():
            if p.is_file():shutil.copyfile(p,target/p.name)
    journal=ROOT/'runs/executor-state.json';before=hashlib.sha256(journal.read_bytes()).hexdigest();report={'all_passed':False,'checks':[],'run_id':run_id};env={**os.environ,'SW_MCP_PROCESS_ID':'2147480000'}
    config=StdioServerParameters(command=sys.executable,args=[str(root/'motion_server.py')],cwd=str(root),env=env)
    def checked(name,data):report['checks'].append({'name':name,'data':data})
    with (root/'sdk-stderr.log').open('w',encoding='utf-8') as err:
        async with stdio_client(config,errlog=err) as streams:
            async with ClientSession(*streams) as client:
                hello=await client.initialize();tools=await client.list_tools();assert len(tools.tools)==24;checked('handshake',{'server':hello.server_info.model_dump(),'tools':len(tools.tools)})
                summary=unpack(await client.call_tool('get_run_artifacts',{'run_id':run_id,'limit':3}));assert summary['query_scope']=='run_summary' and summary['limit_applied'] is False and summary['component_motion_overview']['checked_component_count']==6;checked('run_summary_limit_three',{'scope':summary['query_scope'],'overview':summary['component_motion_overview']})
                page=unpack(await client.call_tool('get_run_artifacts',{'run_id':run_id,'replay_diagnostics':True,'limit':3}));page2=unpack(await client.call_tool('get_run_artifacts',{'run_id':run_id,'replay_diagnostics':True,'limit':3,'cursor':page['next_cursor']}));assert len(page['components'])+len(page2['components'])==6 and page2['next_cursor'] is None;checked('full_six_diagnostics_offline',{'first':page,'second':page2})
                invalid=await client.call_tool('get_run_artifacts',{'run_id':run_id,'cursor':'not-an-observation-page'});message=' '.join(c.text for c in invalid.content if hasattr(c,'text'));assert invalid.is_error and 'run_id' in message;checked('wrong_summary_cursor_rejected',message)
                if selected:
                    failure=unpack(await client.call_tool('get_environment',{}));assert failure['ok'] is False and failure['error']['code']=='COM_SESSION_ID_MISMATCH';checked('stale_pid_handshake_rejected',failure)
                    for _ in range(10):
                        corrected=unpack(await client.call_tool('get_environment',{'solidworks_pid':selected}))
                        if corrected.get('ok'):break
                        assert corrected['error']['code']=='COM_CONNECTION_PENDING';await asyncio.sleep(.25)
                    assert corrected['ok'] and corrected['result']['solidworks_process_id']==int(selected);checked('explicit_pre_dispatch_correction',corrected)
                    blocked=unpack(await client.call_tool('get_environment',{'solidworks_pid':'auto'}));assert not blocked['ok'] and blocked['error']['code']=='STARTUP_SELECTION_NOT_ALLOWED';checked('post_dispatch_retarget_rejected',blocked)
                    restored=unpack(await client.call_tool('get_recovery_state',{}));assert not restored['recovery_required']
                own_journal=root/'runs/executor-state.json'
                assert not own_journal.exists() or json.loads(own_journal.read_text())['status']=='idle'
                own_journal.parent.mkdir(exist_ok=True);own_journal.write_text('{"status":"unknown","request_id":"offline-verification-test"}',encoding='utf-8');saved=own_journal.read_bytes()
                quarantine=unpack(await client.call_tool('get_run_artifacts',{'run_id':run_id,'replay_diagnostics':True,'limit':20}));assert quarantine['returned_diagnostic_count']==6;assert own_journal.read_bytes()==saved;checked('offline_diagnostics_preserve_unknown',quarantine)
    assert hashlib.sha256(journal.read_bytes()).hexdigest()==before;report.update(all_passed=True,primary_journal_unchanged=True,cad_models_opened=False,cad_calculate_called=False);(root/'protocol.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'all_passed':True,'checks':len(report['checks']),'root':str(root),'primary_journal_unchanged':True}))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('root');parser.add_argument('--solidworks-pid',default='');args=parser.parse_args();root=Path(args.root).resolve();boundary=(ROOT/'runs/virtual-import-acceptance').resolve()
    if root.parent!=boundary or not (root/'native.json').is_file():raise ValueError('Use a completed isolated native acceptance directory')
    session=json.loads((root/'session.json').read_text(encoding='utf-8'));assert session['completed'] and session['helper_exit']==0 and session.get('owned_exit_code') is not None
    # ExitApp may return a nonzero application code after successful native checks.
    # Retain that code in session evidence; require the owned process to have exited.
    asyncio.run(run(root,args.solidworks_pid))
if __name__=='__main__':main()
