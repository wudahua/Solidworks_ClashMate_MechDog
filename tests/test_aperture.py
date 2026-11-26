from pathlib import Path
from types import SimpleNamespace
import asyncio
import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from sw_mcp.conversation import aperture, core
from sw_mcp.bridge import CadError


def sample(frame, stroke, gaps, collisions=None):
    return {'frame': frame, 'time_s': frame / 10, 'input_mm': stroke, 'gaps_mm': gaps,
            'tip_radii_mm': dict.fromkeys(('a', 'b', 'c', 'd'), gaps[0] / 2), 'interferences_mm3': collisions or {}}


class ApertureTests(unittest.TestCase):
    def setUp(self):
        self.session = SimpleNamespace(model='model', folder=Path('test-not-written'), state=Mock(), call=Mock())
        self.proposal = {'aperture_validation': {'target_openings_mm': [30, 40], 'scope': 'test'},
                         'direction_binding': {'native_reverse_direction': False, 'expected_sign_about_selected_native_axis': 1}}
        self.drive = {'component_id': 'drive', 'entity_id': 'face', 'axis_global': [0, 0, 1]}
        self.reference = {'component_id': 'support'}

    def test_targets_are_both_required_and_parameter_type_is_strict(self):
        self.assertFalse(aperture.reached(sample(20, 15, [29, 41]), [30, 40]))
        import motion_server
        engine = SimpleNamespace(tasks={'a' * 32: {}}, plan=Mock(return_value={'accepted': True}))
        with patch.object(motion_server, '_task_engine', engine):
            valid = asyncio.run(motion_server.mcp.call_tool('plan_mechanism_task', {'task_id': 'a' * 32, 'target_openings_mm': [30, 40]}))
            self.assertFalse(valid.is_error)
            self.assertEqual(engine.plan.call_args.kwargs['target_openings_mm'], [30, 40])
            engine.plan.reset_mock()
            invalid = asyncio.run(motion_server.mcp.call_tool('plan_mechanism_task', {'task_id': 'a' * 32, 'target_openings_mm': [True, 40]}))
            self.assertTrue(invalid.is_error)
            engine.plan.assert_not_called()

    def test_probe_collision_reports_safe_stroke_and_stops_expansion(self):
        initial = sample(0, 0, [70, 80])
        safe = sample(10, 2.5, [65, 75])
        collision = sample(15, 4.3, [40, 50], {'clip|rod': 6})
        inaccessible = sample(20, 5, [29, 39])
        self.session.call.return_value = {'run_id': 'b' * 32}
        with patch.object(aperture, 'samples', return_value=([initial, safe, collision, inaccessible], {})), patch.object(core, 'write'):
            result = aperture.run(self.session, self.proposal, self.drive, self.reference)
        self.assertFalse(result['declared_scope_passed'])
        self.assertEqual(result['first_sample_with_interference'], collision)
        self.assertEqual(result['last_clear_probe_sample'], safe)
        self.assertFalse(result['native_study_saved'])
        self.session.call.assert_called_once()
        self.assertEqual(self.session.call.call_args.kwargs['stroke_mm'], 5)

    def test_dense_scan_vetoes_saving_when_return_leg_hits(self):
        first = sample(0, 0, [70, 80])
        accepted = sample(20, 5, [30, 40])
        new_interference = sample(24, 4.5, [34, 44], {'guide|neighbor': 2})
        rows = [dict(first, frame=i) for i in range(41)]
        rows[20], rows[24] = accepted, new_interference
        self.session.call.side_effect = [{'run_id': 'b' * 32}, {'run_id': 'c' * 32, 'Study': 'temporary'}, {'saved': False}]
        with patch.object(aperture, 'samples', side_effect=[([first, accepted], {}), (rows, {})]), patch.object(core, 'write'):
            result = aperture.run(self.session, self.proposal, self.drive, self.reference)
        self.assertEqual(result['first_sample_with_interference'], new_interference)
        self.assertFalse(result['declared_scope_passed'])
        self.session.call.assert_called_with('_finish_aperture_cycle', model_id='model', study='temporary', keep=False)

    def test_suppressed_mates_bind_the_discard_checkpoint_before_sampling(self):
        self.session.initial_inspection = {'mates': [{'suppressed': True}]}
        checkpoint = 'd' * 32
        self.session.call.side_effect = [{'checkpoint_id': checkpoint}, {'run_id': 'b' * 32}]
        initial = sample(0, 0, [70, 80])
        collision = sample(10, 2.5, [55, 60], {'clip|rod': 6})
        with patch.object(aperture, 'samples', return_value=([initial, collision], {})), patch.object(core, 'write'):
            result = aperture.run(self.session, self.proposal, self.drive, self.reference)
        self.assertFalse(result['declared_scope_passed'])
        calls = self.session.call.call_args_list
        self.assertEqual(calls[0].args, ('create_model_checkpoint',))
        self.assertEqual(calls[1].kwargs['discard_checkpoint'], checkpoint)

    def test_endpoint_failure_stops_the_sweep_and_preserves_cleanup_status_in_views(self):
        from sw_mcp.conversation import assembly_snapshot, task_progress
        for failure_code, restoration in (('CONNECTION_EVIDENCE_FAILED','restored'),('RESTORATION_FAILED','unknown')):
            def rejected(operation, **args):
                details={'reason':'aperture_cycle_did_not_return_to_saved_pose','run_id':args['run_id'],
                    'endpoint':{'frame':40,'maximum_translation_m':.04672,'maximum_rotation_rad':.38515}}
                if failure_code=='RESTORATION_FAILED':
                    details={'original_failure':{'details':details}}
                raise CadError(failure_code,'endpoint failure',restoration,{'details':details})
            self.session.call.reset_mock(side_effect=True)
            self.session.call.side_effect=rejected
            with self.subTest(failure_code=failure_code), self.assertRaises(CadError) as raised:
                aperture.run(self.session,self.proposal,self.drive,self.reference)
            self.session.call.assert_called_once()
            self.assertEqual(raised.exception.code,failure_code)
            endpoint=raised.exception.diagnostics['aperture_endpoint']
            self.assertEqual(endpoint['maximum_translation_m'],.04672)
            self.assertEqual(endpoint['trial_restoration_status'],restoration)
            task={'task_id':'a'*32,'phase':'failed','error':{'code':failure_code,'diagnostics':raised.exception.diagnostics}}
            self.assertEqual(assembly_snapshot.summary(task)['error']['aperture_endpoint'],endpoint)
            self.assertEqual(task_progress.compact_status(task,None,'owner')['aperture_endpoint'],endpoint)

    @unittest.skipUnless(os.name=='nt','Windows .NET Framework compiler required')
    def test_production_endpoint_diagnostics_retain_strict_thresholds_and_rank_both_axes(self):
        root=Path(__file__).resolve().parents[1]
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        scratch=root/'runs/aperture-endpoint-tests'
        scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            exe=Path(directory)/'aperture.exe'
            files=('executor/AperturePoseReview.cs','executor/PoseValidation.cs','executor/CadFault.cs','executor/AtomicMetadata.cs',
                   'tests/AperturePoseReviewTests.cs')
            result=subprocess.run([str(compiler),'/nologo','/out:'+str(exe),'/reference:System.Web.Extensions.dll',
                                   *(str(root/file) for file in files)],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode(errors='replace'))
            result=subprocess.run([str(exe),directory],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,(result.stdout+result.stderr).decode(errors='replace'))

    def test_endpoint_connections_only_name_observed_links_between_ranked_outliers(self):
        inspection={'components':[{'component_id':'a','instance':'jaw'}, {'component_id':'b','instance':'link','fixed_component':True},
                                  {'component_id':'c','instance':'outside'}]}
        def mate(name,a,b,suppressed=False):
            return {'name':name,'suppressed':suppressed,'error':0,'entities':[{'component_id':a},{'component_id':b}]}
        inspection['mates']=[mate('healthy','a','b'),mate('hidden','a','b',True),mate('outside','a','c')]
        endpoint={'allowed_translation_m':1e-7,'allowed_rotation_rad':1e-6,
                  'worst_translation_components':[{'instance':'jaw','translation_m':.0467}],
                  'worst_rotation_components':[{'instance':'link','rotation_rad':.385}]}
        note=aperture.endpoint_connections(inspection,endpoint)
        self.assertEqual(note['fixed_affected_instances'],['link'])
        self.assertEqual([m['name'] for m in note['observed_links']],['healthy'])
        self.assertFalse(note['root_cause_proven'])


if __name__ == '__main__':
    unittest.main()
