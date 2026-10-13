"""Start one owned SOLIDWORKS only after a real MCP call failed with no SW running.

Requires an otherwise idle development desktop. Never closes existing CAD processes.
Leaves the owned instance running for subsequent tests.
"""
import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]

def running_solidworks():
    output = subprocess.check_output(['powershell', '-NoProfile', '-Command', '$swTestIds=@(Get-Process SLDWORKS -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id); ConvertTo-Json -InputObject $swTestIds -Compress'], text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(output)

async def main(executable):
    report = {'all_passed': False, 'existing_solidworks_pids': running_solidworks(), 'owned_solidworks_pid': None}
    assert not report['existing_solidworks_pids'], 'Existing SOLIDWORKS detected; this test never closes it.'
    executable = Path(executable).resolve(strict=True)
    assert executable.name.lower() == 'sldworks.exe'
    journal = ROOT/'runs/executor-state.json'
    before = journal.read_bytes() if journal.exists() else None
    output = ROOT/'runs/motion-startup-retry-v04.json'
    output.parent.mkdir(exist_ok=True)
    try:
        async with Client(StdioServerParameters(command=os.sys.executable, args=[str(ROOT/'motion_server.py')], cwd=ROOT, env={'PYTHONIOENCODING': 'utf-8'})) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 20
            failed = await client.call_tool('get_environment', {})
            assert failed.is_error and failed.structured_content['error']['code'] == 'COM_SESSION_NOT_FOUND', failed
            assert (journal.read_bytes() if journal.exists() else None) == before
            assert not running_solidworks(), 'A user instance started; abort without launching another.'
            report['initial_error'] = failed.structured_content
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            owned = subprocess.Popen([str(executable)], startupinfo=startup)
            report['owned_solidworks_pid'] = owned.pid
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print('MCP_INITIAL_NO_SESSION PASS; OWNED_SW_PID', owned.pid, flush=True)
            deadline = time.monotonic()+180
            attempts = []
            while True:
                assert owned.poll() is None, 'Owned SOLIDWORKS exited during startup'
                response = await client.call_tool('get_environment', {})
                if not response.is_error:
                    environment = response.structured_content['result']
                    assert environment['solidworks_process_id'] == owned.pid, environment
                    report['environment'] = environment
                    break
                code = response.structured_content['error']['code']
                attempts.append(code)
                assert code in {'COM_SESSION_NOT_FOUND', 'COM_SESSION_UNAVAILABLE', 'COM_CONNECTION_PENDING'}, response
                assert time.monotonic() < deadline, 'Startup deadline exceeded'
                await asyncio.sleep(2)
            report['retry_errors'] = attempts
            report['same_mcp_client_session'] = True
        report['solidworks_alive_after_disconnect'] = owned.poll() is None
        assert report['solidworks_alive_after_disconnect']
        report['all_passed'] = True
    except Exception as exc:
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('REAL_MCP_START_BEFORE_SOLIDWORKS_RETRY PASS', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--solidworks-executable', required=True)
    asyncio.run(main(parser.parse_args().solidworks_executable))
