"""Alpha.9: cold PS5.1 startup, causal error selection, all-pass evidence budget."""
import asyncio
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from sw_mcp import job_payload
from sw_mcp.errors import operational_error
from sw_mcp.native_grid import GridAdmissionError
from test_service import temporary_workspace


class CausalSummaryTests(unittest.TestCase):
    def job(self):
        original = {'code': 'MATE_OVERDEFINED', 'message': 'native overdefined', 'details': {'stage': 'native_add_mate'}}
        native = {'code': 'MATE_APPLY_ROLLED_BACK', 'message': 'rolled back', 'diagnostics': {'details': {'original_failure': original}}}
        return {'job_id': 'c'*32, 'status': 'failed',
                'error': operational_error(native['code'], native['message'], 'restored', native['diagnostics'], job_created=True),
                'late_response': {'response': {'error': copy.deepcopy(native)}}, 'padding': 'x'*30000}

    def test_enriched_canonical_error_beats_late_outer_echo(self):
        with temporary_workspace() as directory:
            root = Path(directory); value = job_payload.bound(root, self.job())
            self.assertEqual(value['root_cause_code'], 'MATE_OVERDEFINED')
            self.assertEqual(value['root_cause_path'], '/error/diagnostics/details/original_failure')
            args = value['root_cause_read']['arguments']
            self.assertIn('MATE_OVERDEFINED', job_payload.read(root, args['job_id'], args['response_artifact_id'], 0, 2000, args['response_json_pointer'])['text'])

    def test_same_codes_distinct_causal_stages_are_not_deduplicated(self):
        job = self.job(); job['error']['diagnostics']['details']['original_failure']['code'] = 'MATE_APPLY_ROLLED_BACK'
        with temporary_workspace() as directory:
            value = job_payload.bound(Path(directory), job)
            self.assertEqual(value['root_cause_path'], '/error/diagnostics/details/original_failure')

    def test_original_timeout_is_not_rewritten_by_late_native_outcome(self):
        job = self.job(); job['error'] = operational_error('CAD_TIMEOUT', 'unknown completion', 'unknown')
        with temporary_workspace() as directory:
            value = job_payload.bound(Path(directory), job)
            self.assertEqual(value['root_cause_code'], 'CAD_TIMEOUT')
            self.assertEqual(value['root_cause_path'], '/error')
            self.assertTrue(any(row['path_role'] == 'archived_native_response' for row in value['failure_chain']))

    def test_archive_only_failure_is_still_readable(self):
        job = self.job(); del job['error']
        with temporary_workspace() as directory:
            value = job_payload.bound(Path(directory), job)
            self.assertEqual(value['root_cause_code'], 'MATE_OVERDEFINED')

    def test_second_compaction_retains_success_identity_and_typed_reads(self):
        drive = {'component_id': 'actual-component', 'Axis': [0,0,1], 'PointLocal': [.1,.2,.3],
                 'parameters': {'f'+str(i): '汉'*2000 for i in range(15)}}
        result = {'requested_drive': drive, 'native_motor_snapshot': {'parameters': {'AxisLocal': [1,0,0], 'native': 'x'*20000}},
                  'frames': 11, 'result_validity': 'verified', 'time_selection_audit': {'maximum_attempts_per_frame': 2, 'observed_total_attempts': 11, 'frames_with_retry': 0},
                  'sampling_performance': {'mean_frame_ms': 112.12, 'detail': {str(i):'x'*2000 for i in range(15)}},
                  'sampling_api_batch': {'property':'ISldWorks.CommandInProgress', 'component_reads_skipped':False},
                  'huge': {str(i): 'x'*2000 for i in range(30)}}
        job = {'job_id': 'd'*32, 'status':'succeeded', 'result':result}
        self.assertGreater(job_payload.wire_size(job_payload._summary(job)), 16000)
        with temporary_workspace() as directory:
            root = Path(directory); value = job_payload.bound(root, job)
            self.assertEqual(value['evidence']['requested_drive']['value']['Axis'], [0,0,1])
            self.assertEqual(value['evidence']['requested_drive']['value']['component_id'], 'actual-component')
            self.assertEqual(value['evidence']['time_selection_audit']['value']['observed_total_attempts'], 11)
            self.assertLessEqual(job_payload.wire_size(value), 16000)
            args = value['evidence']['native_motor_snapshot']['read']['arguments']
            page = job_payload.read(root, args['job_id'], args['response_artifact_id'], 0, 2000, args['response_json_pointer']+'/parameters/AxisLocal')
            self.assertEqual(json.loads(page['text']), [1,0,0])
            artifact = root/'runs/job-responses'/job['job_id']/(args['response_artifact_id']+'.json')
            artifact.write_bytes(artifact.read_bytes()+b'!')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                job_payload.read(root, args['job_id'], args['response_artifact_id'], 0, 2000)

    def test_second_compaction_keeps_failure_artifact_query_and_action(self):
        job = self.job()
        artifacts = {'run_id':'c'*32,'query':{'tool':'get_run_artifacts','arguments':{'run_id':'c'*32}},'poses_csv':None}
        job['error']['diagnostics'].update(artifacts=artifacts, large={str(i): 'x'*2000 for i in range(30)})
        with temporary_workspace() as directory:
            value = job_payload.bound(Path(directory), job)
            self.assertEqual(value['evidence']['artifacts']['value'], artifacts)
            self.assertFalse(value['error']['next_action']['automatic_retry'])
            self.assertIn('recovery_state_query', value['error']['next_action'])
            self.assertEqual(value['error']['restoration_status'], 'restored')
            self.assertLessEqual(job_payload.wire_size(value), 16000)


class GuidanceTests(unittest.TestCase):
    def test_normal_completed_job_does_not_duplicate_native_response(self):
        from sw_mcp.jobs import Jobs
        class Bridge:
            cad_operation_state = 'idle'
            def get_request_result(self, request_id):
                raise AssertionError('Normal completion must not reattach an archived duplicate')
        with temporary_workspace() as directory:
            root = Path(directory); folder = root/'runs/jobs'; folder.mkdir(parents=True)
            identifier = 'f'*32
            (folder/(identifier+'.json')).write_text(json.dumps({'job_id':identifier,'operation':'run_user_study','status':'succeeded','result':{'frames':11}}),encoding='utf-8')
            (folder/(identifier+'.request.json')).write_text(json.dumps({'job_id':identifier,'operation':'run_user_study','request_id':'a'*32}),encoding='utf-8')
            jobs = Jobs(Bridge(), root)
            try:
                value = jobs.get(identifier)
                self.assertNotIn('late_response', value)
                self.assertEqual(value['status'], 'succeeded')
            finally:
                jobs._pool.shutdown()

    def test_all_typed_evidence_reads_fit_with_long_cursors_and_failure_chain(self):
        job = CausalSummaryTests().job()
        job['result'] = {'next_cursor':'令牌'*3000, **{key:{'Axis':[0,0,1], 'blob':'x'*18000} for key in job_payload.EVIDENCE_KINDS}}
        with temporary_workspace() as directory:
            root=Path(directory); value=job_payload.bound(root,job)
            self.assertEqual(set(value['evidence']),set(job_payload.EVIDENCE_KINDS))
            self.assertEqual(value['root_cause_code'],'MATE_OVERDEFINED')
            self.assertLessEqual(job_payload.wire_size(value),16000)
            for key in job_payload.EVIDENCE_KINDS:
                args=value['evidence'][key]['read']['arguments']
                page=job_payload.read(root,args['job_id'],args['response_artifact_id'],0,2000,args['response_json_pointer']+'/Axis')
                self.assertEqual(json.loads(page['text']),[0,0,1])

    def test_nested_action_token_and_sync_contract(self):
        from sw_mcp.validation import refuse
        error = operational_error('FAILED','failure','restored',{'details':{'next_action':'review_axis'}})
        self.assertEqual(error['next_action']['action_code'], 'review_axis')
        self.assertEqual(error['diagnostics']['next_action_code'], 'review_axis')
        sync = refuse('INVALID_ARGUMENT', 'bad').structured_content['error']
        for key in ('automatic_retry','options','options_status','recovery_state_query','instruction'):
            self.assertIn(key, sync['next_action'])
        self.assertFalse(sync['diagnostics']['cad_dispatched'])

    def test_unverified_history_choices_are_exact_diagnostic_calls(self):
        import motion_server as server
        from sw_mcp.artifacts import ArtifactError
        with patch.object(server.artifacts, 'summary', side_effect=ArtifactError('RESULTS_UNVERIFIED', 'unverified')), patch.object(server.bridge, 'request') as request:
            result = asyncio.run(server.mcp.call_tool('get_motion_summary', {'run_id':'e'*32})).structured_content
        action = result['error']['next_action']
        self.assertEqual(action['options'][1]['arguments'], {'run_id':'e'*32, 'allow_unverified_history':True})
        self.assertFalse(action['automatic_retry']); request.assert_not_called()

    def test_mate_plan_guidance_does_not_fabricate_missing_entity_ids(self):
        import motion_server as server
        value = asyncio.run(server.mcp.call_tool('apply_mate', {'plan_id':'bad','confirmed':True})).structured_content
        action = value['error']['next_action']
        self.assertEqual(action['tool'], 'preview_mate')
        self.assertEqual(action['options_status'], 'tool_identified_arguments_require_user_input')
        self.assertEqual(action['options'], [])

    def test_grid_message_does_not_offer_unavailable_hardcoded_example(self):
        error = GridAdmissionError(.09, 30, aligned=False)
        self.assertNotIn('例如0.1s/100fps', str(error))
        self.assertAlmostEqual(error.diagnostics['requested_intervals'], 2.7)

    def test_upgrade_wrapper_is_explicit_offline_entry_and_receipt_schema(self):
        from run_offline_policies import SUITES
        self.assertIn('upgrade_powershell_checks', SUITES)
        import test_alpha5 as fixtures
        from contextlib import nullcontext
        import sys
        fixture = fixtures.ReleaseUpgradeTests(); fixture.setUp()
        try:
            fixture.write_zip()
            with patch('scripts.upgrade.idle_installation', return_value=nullcontext()):
                receipt = fixtures.upgrade(fixture.package, fixture.target, sys.executable, install=False)
            self.assertEqual(receipt['schema_version'], 2)
            self.assertEqual(receipt['stage'], 'completed')
            self.assertTrue(receipt['committed'])
        finally:
            fixture.doCleanups()


if __name__ == '__main__': unittest.main()
