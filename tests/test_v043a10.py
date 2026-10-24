"""Task semantics at every boundary; no synthetic fixture is called a CAD test."""
import ast
import asyncio
import json
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import motion_server
from sw_mcp.conversation import core, evidence_bundle
from sw_mcp.conversation.frontend import transport_refusal
from sw_mcp.conversation.task_engine import TaskEngine
from sw_mcp.errors import NATIVE_ACTION_CLASSES
from sw_mcp.task_errors import CONFIRMATION_CODES, TASK_ACTION_CLASSES, task_failure
from sw_mcp.validation import refuse
from test_conversation_tasks import FakeSession

ROOT = Path(__file__).resolve().parents[1]


def task_codes():
    codes=set()
    for file in (ROOT/'sw_mcp/conversation').glob('*.py'):
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8-sig'))):
            if not isinstance(node,ast.Call):continue
            func=node.func
            if not (isinstance(func,ast.Attribute) and func.attr=='StopBatch' or isinstance(func,ast.Name) and func.id=='StopBatch'):continue
            if node.args and isinstance(node.args[0],ast.Constant):codes.add(node.args[0].value)
    return codes


class ErrorPolicyTests(unittest.TestCase):
    def test_every_literal_exit_including_bare_core_calls_has_deliberate_classification(self):
        codes=task_codes()
        self.assertGreaterEqual(len(codes),144)
        for code in codes:
            with self.subTest(code=code):
                self.assertTrue(code in TASK_ACTION_CLASSES or code in NATIVE_ACTION_CLASSES or code.startswith('HOST_') or code=='EXECUTOR_ALREADY_RUNNING',code)
                e=transport_refusal(core.StopBatch(code)).structured_content['error']
                self.assertNotIn(e['next_action']['options_status'],{
                    'tool_identified_arguments_require_user_input','no_safe_parameter_change_inferred_from_error_code'})
                self.assertFalse(e['next_action']['automatic_retry'])
                self.assertNotIn(e['restoration_status'],{'restored','not_required'})

    def test_all_confirmation_codes_outrank_tools_and_selection_hints(self):
        self.assertEqual(len(CONFIRMATION_CODES),5)
        for code in CONFIRMATION_CODES:
            for hints in ({'tool':'get_mechanism_task','arguments':{}},{'options':[{'value':'unsafe-default'}]}):
                e=refuse(code,code,next_action=hints).structured_content['error']
                self.assertEqual(e['next_action']['options_status'],'explicit_human_confirmation_required')
                self.assertIn('不得自行',e['next_action']['instruction'])
            e=transport_refusal(core.StopBatch(code)).structured_content['error']
            self.assertEqual(e['next_action']['options_status'],'explicit_human_confirmation_required')

    def test_parameters_are_distinct_from_observed_pose_evidence(self):
        for code in ('INVALID_MOTION_PARAMETERS','INVALID_INITIAL_STATE','INCOMPATIBLE_FINISH_CHOICES'):
            self.assertEqual(task_failure(code,code)['next_action']['options_status'],'user_parameter_correction_required')
        for code in ('INVALID_INITIAL_POSE','INITIAL_POSE_MISMATCH','INITIAL_FRAME_INVALID'):
            self.assertEqual(task_failure(code,code)['next_action']['options_status'],'mechanical_evidence_review_required_no_parameter_change')

    def test_unknown_outcome_never_claims_predispatch_or_restoration(self):
        for code in ('NATIVE_STATE_UNKNOWN','TASK_OWNER_REQUEST_UNCONFIRMED','ORPHAN_NATIVE_OUTCOME_UNCONFIRMED','EXECUTOR_EXIT_UNCONFIRMED','FUTURE_UNCLASSIFIED_ERROR'):
            e=task_failure(code,code,{'cad_dispatched':False,'job_created':False,'original_failure':{'code':'INNER'}})
            self.assertIsNone(e['diagnostics']['cad_dispatched']);self.assertIsNone(e['diagnostics']['job_created'])
            self.assertEqual(e['assertion'],'inconclusive');self.assertEqual(e['restoration_status'],'unknown')
            self.assertEqual(e['diagnostics']['original_failure']['code'],'INNER')

    def test_async_input_looking_code_does_not_claim_no_CAD_call(self):
        e=task_failure('INVALID_ASSEMBLY_PATH','fixture',asynchronous=True)
        self.assertIsNone(e['diagnostics']['cad_dispatched']);self.assertEqual(e['restoration_status'],'unknown')

    def test_host_failure_offline_route_and_native_taxonomy_survive(self):
        for code in ('HOST_CONTEXT_REQUIRED','HOST_TASK_COLLISION','TASK_OWNER_LOST','INVALID_OWNER_RESPONSE'):
            e=task_failure(code,code)
            self.assertEqual(e['next_action']['arguments'],{'collect_evidence':True})
            self.assertEqual(e['next_action']['options_status'],'host_infrastructure_review_required_no_parameter_change')
        for code,(status,_) in NATIVE_ACTION_CLASSES.items():
            self.assertEqual(task_failure(code,code)['next_action']['options_status'],status)
        e=task_failure('LEGACY_SESSION_REQUIRES_FINISH','x')
        self.assertEqual(e['next_action']['tool'],'finish_motion_session')

    def test_low_level_prerequisite_still_names_preview_without_granting_confirmation(self):
        e=refuse('INVALID_MATE_PLAN_ID','x',next_action={'tool':'preview_mate','arguments':{}}).structured_content['error']
        self.assertEqual(e['next_action']['options_status'],'tool_identified_arguments_require_user_input')

    def test_invalid_ID_human_message_and_query_do_not_repeat_bad_ID(self):
        e=task_failure('INVALID_TASK_ID','INVALID_TASK_ID',task_id='bad')
        self.assertIn('32位小写十六进制',e['message']);self.assertEqual(e['next_action']['arguments'],{})
        with self.assertRaises(core.StopBatch) as raised:evidence_bundle.collect(ROOT/'runs','bad')
        self.assertIn('32位小写十六进制',str(raised.exception))

    def test_owner_SDK_and_frontend_preserve_identical_semantic_classes(self):
        tid='a'*32
        for code in task_codes():
            engine=SimpleNamespace(tasks={tid:{}},execute=Mock(side_effect=core.StopBatch(code,'fixture')))
            with self.subTest(code=code),patch.object(motion_server,'_task_engine',engine):
                result=asyncio.run(motion_server.mcp.call_tool('execute_mechanism_task',{'task_id':tid,'plan_token':'p'})).structured_content
                expected=transport_refusal(core.StopBatch(code,'fixture')).structured_content
                self.assertEqual(result['error']['next_action']['options_status'],expected['error']['next_action']['options_status'])
                self.assertFalse(result['ok'])

    def test_owner_evidence_and_legacy_exit_are_not_masked_or_parameterized(self):
        engine=SimpleNamespace(tasks={},work=ROOT/'runs')
        with patch.object(motion_server,'_task_engine',engine):
            value=asyncio.run(motion_server.mcp.call_tool('get_mechanism_task',{'task_id':'bad','collect_evidence':True})).structured_content
        self.assertEqual(value['error']['code'],'INVALID_TASK_ID')
        self.assertEqual(value['error']['next_action']['options_status'],'user_parameter_correction_required')
        with patch.object(motion_server,'_formal_engine',SimpleNamespace(finish_legacy=Mock(side_effect=core.StopBatch('NATIVE_STATE_UNKNOWN')))):
            value=asyncio.run(motion_server.mcp.call_tool('finish_motion_session',{})).structured_content
        self.assertIsNone(value['error']['diagnostics']['cad_dispatched'])
        self.assertEqual(value['error']['next_action']['options_status'],'native_outcome_review_required_no_write_retry')

    def test_async_failure_persists_same_envelope_and_one_attempt(self):
        class Failing(FakeSession):
            def discover(s,path):raise core.StopBatch('INVALID_INITIAL_POSE','observed nonfinite pose')
        folder=ROOT/'runs'/('a10-fixture-'+uuid.uuid4().hex[:8]);(folder/'models').mkdir(parents=True)
        source=folder/'models/model.SLDASM';source.write_bytes(b'fixture, not CAD')
        engine=TaskEngine(ROOT,folder/'work',folder/'runtime',Failing)
        try:
            tid=engine.prepare(str(source))['task_id']
            for _ in range(500):
                state=engine.get(tid)
                if not state['busy']:break
                time.sleep(.005)
            self.assertEqual(state['phase'],'failed')
            e=state['error'];self.assertEqual(e['next_action'],state['next_action'])
            self.assertEqual(e['next_action']['options_status'],'mechanical_evidence_review_required_no_parameter_change')
            self.assertIsNone(e['diagnostics']['cad_dispatched']);self.assertFalse(e['retry_write_allowed'])
            saved=core.read(Path(state['directory'])/'任务状态.json')
            self.assertEqual(saved['error'],e)
            self.assertEqual(core.read(Path(state['directory'])/'失败诊断.json')['error'],e)
        finally:engine.shutdown()

    def test_contract_documents_each_task_status_and_is_publicly_packaged(self):
        text=(ROOT/'CONTRACT.md').read_text(encoding='utf8')
        for status,_ in set(TASK_ACTION_CLASSES.values()):self.assertIn('`'+status+'`',text)
        for status,_ in set(NATIVE_ACTION_CLASSES.values()):self.assertIn('`'+status+'`',text)
        self.assertIn('CONTRACT.md',(ROOT/'README.md').read_text(encoding='utf8'))
        from scripts.verify_release import allowed_release_path
        self.assertTrue(allowed_release_path('CONTRACT.md'))
        self.assertIn('CONTRACT.md',(ROOT/'scripts/build_release.py').read_text(encoding='utf8'))

    def test_backup_wrapper_resolves_own_scripts_not_TargetDir_scripts(self):
        text=(ROOT/'upgrade.ps1').read_text(encoding='utf8')
        self.assertIn("Join-Path $PSScriptRoot 'scripts\\upgrade.py'",text)
        self.assertNotIn("Join-Path $TargetDir 'scripts\\upgrade.py'",text)


if __name__=='__main__':unittest.main(verbosity=2)
