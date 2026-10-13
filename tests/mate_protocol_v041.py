"""Exercise new tools through an actual MCP client; native CAD is opt-in."""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]


async def main(native_report, unmated_source=None):
    report = {'all_passed': False}
    env = {k: os.environ[k] for k in ('SW_MCP_PROCESS_ID',) if k in os.environ}
    async with Client(StdioServerParameters(command=sys.executable, args=[str(ROOT/'motion_server.py')], cwd=ROOT, env=env)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert len(names) == 24
        report['tools'] = sorted(names)
        invalid = [
            ('list_mate_references', {'model_id': 'none', 'limit': 0}),
            ('preview_mate', {'model_id': 'none', 'entity_a': 'a', 'entity_b': 'b', 'mate_type': 'distance', 'distance_mm': -1}),
            ('preview_mate', {'model_id': 'none', 'entity_a': 'a', 'entity_b': 'b', 'mate_type': 'parallel', 'lock_rotation': True}),
            ('apply_mate', {'plan_id': 'none', 'confirmed': False}),
            ('verify_motion_preservation', {'model_id': 'none', 'study': 'none', 'component_id': 'none', 'entity_id': 'none', 'expected_motion': 'linear', 'minimum_travel': 0}),
            ('verify_motion_preservation', {'model_id': 'none', 'study': 'none', 'component_id': 'none', 'entity_id': 'none', 'expected_motion': 'linear', 'minimum_travel': 1, 'duration_s': 6}),
        ]
        for name, params in invalid:
            response = await client.call_tool(name, params)
            assert response.is_error, name
        report['invalid_requests_rejected'] = len(invalid)
        if native_report:
            evidence = json.loads(Path(native_report).read_text(encoding='utf-8'))
            assert evidence['all_passed']
            # Positive import/preview/apply round trip, not only schema inspection.
            source = unmated_source or evidence.get('protocol_unmated_source')
            if source:
                imported_job = (await client.call_tool('import_assembly', {'path': source})).structured_content['job_id']
                start = time.monotonic()
                while True:
                    imported = (await client.call_tool('get_job', {'job_id': imported_job})).structured_content
                    if imported['status'] not in ('queued', 'running'):
                        break
                    assert time.monotonic()-start < 120
                    await asyncio.sleep(.2)
                assert imported['status'] == 'succeeded', imported
                copied = imported['result']['model_id']
                refs = (await client.call_tool('list_mate_references', {'model_id': copied})).structured_content['result']['entities']
                fa = next(r for r in refs if r['fixed_component'] and r['kind'] == 'cylindrical_axis')
                fb = next(r for r in refs if not r['fixed_component'] and r['kind'] == 'cylindrical_axis')
                planned = await client.call_tool('preview_mate', {'model_id': copied, 'entity_a': fa['entity_id'], 'entity_b': fb['entity_id'], 'mate_type': 'concentric'})
                assert not planned.is_error
                applied = await client.call_tool('apply_mate', {'plan_id': planned.structured_content['result']['plan_id'], 'confirmed': True, 'wait_for_completion': True})
                assert not applied.is_error and applied.structured_content['result']['native_parameters']['verified'], applied
                report['public_mate_creation'] = applied.structured_content['result']
            identifier = evidence['protocol_model_id']
            drive = evidence['protocol_drive']
            response = await client.call_tool('list_mate_references', {'model_id': identifier})
            assert not response.is_error and response.structured_content['result']['entities']
            rows = response.structured_content['result']['entities']
            a = next(r for r in rows if r['fixed_component'] and r['kind'] == 'cylindrical_axis')
            b = next(r for r in rows if not r['fixed_component'] and r['kind'] == 'cylindrical_axis')
            response = await client.call_tool('preview_mate', {'model_id': identifier, 'entity_a': a['entity_id'], 'entity_b': b['entity_id'], 'mate_type': 'concentric'})
            assert not response.is_error
            report['preview'] = response.structured_content['result']
            response = await client.call_tool('verify_motion_preservation', {'model_id': identifier, 'study': 'Public_rotary', 'component_id': drive['component_id'], 'entity_id': drive['entity_id'], 'expected_motion': 'rotary', 'minimum_travel': 5})
            assert not response.is_error
            job_id = response.structured_content['job_id']
            start = time.monotonic()
            while True:
                job = (await client.call_tool('get_job', {'job_id': job_id})).structured_content
                if job['status'] not in ('queued', 'running'):
                    break
                assert time.monotonic()-start < 120
                await asyncio.sleep(.2)
            assert job['status'] == 'succeeded' and job['result']['assertion'] == 'pass', job
            assert job['params']['run_id'] == job_id and job['result']['run_id'] == job_id
            assert job['progress']['terminal'] and job['progress']['cad_operation_finished']
            report['native_job'] = job
            offline = await client.call_tool('get_run_artifacts', {'run_id': job_id})
            assert not offline.is_error and offline.structured_content['motion_validation']['assertion'] == 'pass'
            report['offline_run_readable'] = True
            listed = await client.call_tool('list_motion_studies', {'model_id': identifier})
            assert not listed.is_error
            row = next(s for s in listed.structured_content['result']['studies'] if s['name'] == 'Public_rotary')
            assert row['last_run']['motion_validation_assertion'] == 'pass'
            report['history_motion_assertion_readable'] = True
    report['all_passed'] = True
    (ROOT/'runs').mkdir(exist_ok=True)
    (ROOT/'runs/mate-protocol-v041.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'all_passed': True, 'tools': len(names), 'invalid_requests': len(invalid), 'real_com': bool(native_report)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-report')
    parser.add_argument('--unmated-source')
    args = parser.parse_args()
    asyncio.run(main(args.native_report, args.unmated_source))
