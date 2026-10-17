"""Real MCP stdio regression with a recording dispatch double; never connects to CAD."""
import asyncio
import hashlib
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def check(source=ROOT, observe=False):
    folder = ROOT / 'runs/grid-protocol' / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    shutil.copyfile(source / 'motion_server.py', folder / 'motion_server.py')
    shutil.copytree(source / 'sw_mcp', folder / 'sw_mcp', ignore=shutil.ignore_patterns('__pycache__'))
    # Exercise the real entry point, SDK and JSON-RPC encoding. Only the final
    # CAD dispatch boundary is replaced, so accepted arguments can be inspected.
    (folder / 'launcher.py').write_text('''import json
from pathlib import Path
import motion_server as server
def record(operation, params):
    with Path("dispatch.jsonl").open("a",encoding="utf-8") as f:
        f.write(json.dumps({"operation":operation,"params":params})+"\\n")
    return {"dispatch_double":True,"operation":operation,"params":params}
server.jobs.submit=record
server.bridge.request=lambda operation, **params:record(operation,params)
server.mcp.run()
''', encoding='utf-8', newline='\n')
    journal = ROOT / 'runs/executor-state.json'
    before = hashlib.sha256(journal.read_bytes()).hexdigest() if journal.exists() else None
    report = {'all_passed': False, 'cad_connection_used': False, 'dispatch_boundary': 'recording_double', 'responses': []}
    log = folder / 'dispatch.jsonl'
    base = {'model_id': 'none', 'study': 'Grid Diagnostic'}
    cases = [
        ('create_motion_study', {**base, 'component_id': 'c', 'entity_id': 'e', 'motor_type': 'rotary', 'speed': 10}),
        ('run_motion_study', base),
        ('verify_motion_preservation', {**base, 'component_id': 'c', 'entity_id': 'e', 'expected_motion': 'rotary', 'minimum_travel': 1}),
        ('preflight_motion', {**base, 'compatibility_probe': True}),
    ]
    try:
        config = StdioServerParameters(command=sys.executable, args=[str(folder / 'launcher.py')], cwd=str(folder), env={**os.environ, 'SW_MCP_PROCESS_ID': '2147480000'})
        with (folder / 'stderr.log').open('w', encoding='utf-8') as err:
            async with stdio_client(config, errlog=err) as streams:
                async with ClientSession(*streams) as client:
                    hello = await client.initialize()
                    report['server'] = hello.server_info.model_dump()
                    tools = await client.list_tools()
                    assert len(tools.tools) == 24
                    for tool in tools.tools:
                        assert tool.input_schema['additionalProperties'] is False
                        response = await client.call_tool(tool.name, {'__unexpected_argument': True})
                        error = response.structured_content['error']
                        assert response.is_error and error['code'] == 'UNKNOWN_ARGUMENT'
                        assert error['diagnostics']['unknown_keys'] == ['__unexpected_argument']
                        assert set(error['diagnostics']['accepted_keys']) == set(tool.input_schema.get('properties', {}))
                        assert error['assertion'] == 'not_applicable' and error['restoration_status'] == 'not_required'
                        assert not log.exists()
                    for args in ({**base, 'compatibility_probe': True, 'duration_s': .05, 'output_fps': 100},
                                 {**base, 'compatibility_probe': True, 'probe_duration': .1}):
                        response = await client.call_tool('preflight_motion', args)
                        assert response.is_error and response.structured_content['error']['code'] == 'UNKNOWN_ARGUMENT'
                        assert not log.exists()
                    for name, args in cases:
                        duration_key = 'probe_duration_s' if name == 'preflight_motion' else 'duration_s'
                        for duration in (.1, .2, .3):
                            response = await client.call_tool(name, {**args, duration_key: duration})
                            report['responses'].append({'tool': name, 'duration': duration, 'response': response.model_dump(by_alias=True, exclude_none=True)})
                            if observe:
                                assert not log.exists()
                                continue
                            assert response.is_error, name
                            data = response.structured_content
                            assert data and not data['ok'], name + ': missing structured error'
                            error = data['error']; diag = error['diagnostics']
                            assert error['code'] == 'OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER'
                            assert error['code'] in response.content[0].text and '100' in response.content[0].text
                            assert diag['requested_duration_s'] == duration and diag['requested_output_fps'] == 30
                            assert diag['minimum_output_intervals'] == 10 and diag['minimum_output_frames'] == 11
                            assert diag['cad_dispatched'] is False and diag['automatic_duration_or_fps_change'] is False
                            assert diag['job_created'] is False and 'job_id' not in data
                            assert diag['example'] == error['next_action']['options'][0]
                            assert error['next_action']['automatic_retry'] is False
                            for option in error['next_action']['options']:
                                assert option['tool'] == name
                                a = option['arguments']; d = a.get('probe_duration_s', a.get('duration_s')); f = a.get('probe_output_fps', a.get('output_fps'))
                                assert a['model_id'] == 'none' and a['study'] == base['study']
                                assert 5 <= f <= 120 and d > 0 and d * f >= 10 - 1e-8
                                assert abs(d * f - round(d * f)) <= 1e-8
                            assert not log.exists(), 'Rejected request was dispatched'
                    if observe:
                        return folder, report
                    for sync in (False, True):
                        for plan in ('', 'bad', 'A' * 32, '../plan'):
                            response = await client.call_tool('apply_mate', {'plan_id': plan, 'confirmed': True, 'wait_for_completion': sync})
                            assert response.is_error and response.structured_content['error']['code'] == 'INVALID_MATE_PLAN_ID'
                            assert not log.exists()
                    control = await client.call_tool('create_motion_study', {**cases[0][1], 'duration_s': 40})
                    assert control.is_error and '1801' in control.content[0].text
                    assert control.structured_content['error']['code'] == 'DURATION_OR_FPS_OUT_OF_RANGE'
                    assert not log.exists()
                    for name, args in cases:
                        dk, fk = ('probe_duration_s', 'probe_output_fps') if name == 'preflight_motion' else ('duration_s', 'output_fps')
                        response = await client.call_tool(name, {**args, dk: .09, fk: 112})
                        error = response.structured_content['error']
                        assert response.is_error and error['code'] == 'OUTPUT_GRID_NOT_FRAME_ALIGNED'
                        assert error['diagnostics']['minimum_fps_at_requested_duration'] is None
                        assert not error['diagnostics']['minimum_fps_within_supported_range']
                        assert not log.exists()
                    # Positive controls prove valid inputs still reach the exact
                    # operation/arguments, without implying a native solve pass.
                    for name, args in cases:
                        for d, f in ((.1, 100), (1 / 3, 30), (.5, 30)):
                            dk, fk = ('probe_duration_s', 'probe_output_fps') if name == 'preflight_motion' else ('duration_s', 'output_fps')
                            response = await client.call_tool(name, {**args, dk: d, fk: f})
                            assert not response.is_error
                            data = response.structured_content
                        assert data['dispatch_double'] and data['params']['duration_s'] == d and data['params']['output_fps'] == f
                    for sync in (False, True):
                        response = await client.call_tool('create_motion_study', {**cases[0][1], 'duration_s': .1, 'output_fps': 100, 'wait_for_completion': sync})
                        assert not response.is_error
                        response = await client.call_tool('apply_mate', {'plan_id': 'a' * 32, 'confirmed': True, 'wait_for_completion': sync})
                        assert not response.is_error
        assert not (folder / 'runs/executor-state.json').exists()
        assert not (folder / 'executor').exists()
        assert (hashlib.sha256(journal.read_bytes()).hexdigest() if journal.exists() else None) == before
        report.update(all_passed=True, primary_journal_unchanged=True, rejected_grid_calls=12, rejected_plan_calls=8, accepted_dispatch_double_calls=16)
    finally:
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    return folder, report


if __name__ == '__main__':
    folder, report = asyncio.run(check(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT))
    print(json.dumps({'all_passed': report['all_passed'], 'directory': str(folder), 'rejected_grid_calls': report['rejected_grid_calls'], 'cad_connection_used': False}))
