"""Prepare input errors stay independent of a real occupied installation lease."""
import asyncio
import inspect
import json
import uuid
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch

from sw_mcp.bridge import Bridge,CadError
from sw_mcp.conversation import core,motion_tasks
from sw_mcp.conversation.formal_engine import FormalEngine
from sw_mcp.conversation.frontend import transport_refusal
from sw_mcp.conversation.owner_transport import fingerprint
from sw_mcp.validation import packed

ROOT=Path(__file__).resolve().parents[1]


class PrepareAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.folder=ROOT/'runs/prepare-admission-tests'/uuid.uuid4().hex[:8]
        self.folder.mkdir(parents=True)
        self.assembly=self.folder/'fixture.SLDASM';self.assembly.write_bytes(b'No CAD fixture; never dispatched')
        self.holder=Bridge(self.folder);self.bridge=Bridge(self.folder)
        self.addCleanup(self.holder.close);self.addCleanup(self.bridge.close)
        self.engine=FormalEngine.__new__(FormalEngine)
        self.engine.source_fingerprint=fingerprint();self.engine.managed_upgrade_guard=False
        self.engine.tasks=SimpleNamespace(active=None,prior_unfinished=[],sessions={},tasks={},work=self.folder/'work')
        self.sdk=AsyncMock(return_value=packed({'ok':True,'result':{'scope':'offline_no_CAD_handler_fixture'}}))
        self.engine.product=SimpleNamespace(bridge=self.bridge,jobs=SimpleNamespace(_jobs={}),
            mcp=SimpleNamespace(call_tool=self.sdk),artifacts=object())

    def invalid_cases(self):
        bad=self.folder/'part.SLDPRT';bad.write_bytes(b'wrong extension')
        return [({'duration_s':6},'INVALID_MOTION_PARAMETERS'),
                ({'motion':'linear','speed':501},'INVALID_MOTION_PARAMETERS'),
                ({'minimum_travel':73},'INVALID_MINIMUM_TRAVEL'),
                ({'duration_s':.1},'OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER'),
                ({'duration_s':.5,'output_fps':31},'OUTPUT_GRID_NOT_FRAME_ALIGNED'),
                ({'task_kind':'concentric','speed':13},'CONCENTRIC_FIXED_CARD_PARAMETERS'),
                ({'assembly_path':'relative.SLDASM'},'INVALID_ASSEMBLY_PATH'),
                ({'assembly_path':str(self.folder/'missing.SLDASM')},'INVALID_ASSEMBLY_PATH'),
                ({'assembly_path':str(bad)},'INVALID_ASSEMBLY_PATH')]

    def test_invalid_inputs_do_not_touch_lease_SDK_startup_gate_or_task_state(self):
        self.holder._acquire_lease()
        rows=[]
        with patch.object(self.bridge,'_acquire_lease',wraps=self.bridge._acquire_lease) as acquire,patch.object(motion_tasks.startup_gate,'require_idle') as gate:
            for changes,code in self.invalid_cases():
                with self.subTest(changes=changes):
                    try:self.engine.tool('prepare_mechanism_task',{'assembly_path':str(self.assembly),**changes})
                    except Exception as error:
                        self.assertEqual(getattr(error,'code',None),code)
                        # Owner transport preserves codes for both StopBatch and grid errors.
                        response=transport_refusal(core.StopBatch(code,str(error),getattr(error,'diagnostics',None))).structured_content
                        self.assertEqual(response['error']['code'],code)
                        self.assertFalse(response['error']['diagnostics']['cad_dispatched'])
                        self.assertFalse(response['error']['diagnostics']['job_created'])
                        self.assertNotEqual(response['error']['next_action']['options_status'],'manual_service_disconnect_required_no_parameter_change')
                    else:self.fail('Invalid input accepted')
                    acquire.assert_not_called();gate.assert_not_called();self.sdk.assert_not_called()
                    self.assertIsNone(self.bridge._lease);self.assertIsNotNone(self.holder._lease)
                    self.assertFalse(self.engine.managed_upgrade_guard);self.assertIsNone(self.engine.tasks.active)
                    self.assertEqual(self.engine.tasks.tasks,{})
                    rows.append({'arguments':changes,'code':code})
        core.write(self.folder/'held-lease-invalid-inputs.json',{'cases':rows,'CAD_calls':0,'task_created':False})

    def test_valid_request_still_refuses_real_occupied_lease_without_dispatch(self):
        self.holder._acquire_lease()
        for task_kind in ('motion','concentric'):
            with self.subTest(task_kind=task_kind):
                with self.assertRaises(CadError) as error:
                    self.engine.tool('prepare_mechanism_task',{'assembly_path':str(self.assembly),'task_kind':task_kind})
                self.assertEqual(error.exception.code,'MCP_OWNER_ALREADY_RUNNING')
                self.assertEqual(Path(error.exception.diagnostics['lease_path']),self.folder/'runs/executor-owner.lock')
                self.sdk.assert_not_called();self.assertIsNone(self.engine.tasks.active)
                self.assertIsNotNone(self.holder._lease);self.assertIsNone(self.bridge._lease)

    def test_available_lease_reaches_handler_and_idle_result_releases_guard(self):
        for motion in ('rotary','linear'):
            with self.subTest(motion=motion):
                self.sdk.reset_mock()
                result=self.engine.tool('prepare_mechanism_task',{'assembly_path':str(self.assembly),'motion':motion})
                self.assertTrue(result['structuredContent']['ok']);self.sdk.assert_awaited_once()
                self.assertIsNone(self.bridge._lease);self.assertFalse(self.engine.managed_upgrade_guard)
        self.assertIsNone(self.bridge._process)

    def test_public_defaults_match_shared_input_defaults(self):
        import motion_server
        tool=next(t for t in asyncio.run(motion_server.mcp.list_tools()) if t.name=='prepare_mechanism_task')
        schema=tool.input_schema['properties'];shared=inspect.signature(motion_tasks.prepare_inputs).parameters
        for name in ('task_kind','motion','speed','duration_s','output_fps','reverse_direction','minimum_travel'):
            self.assertEqual(schema[name]['default'],shared[name].default,name)
        assembly,settings=motion_tasks.validate_prepare_arguments({'assembly_path':str(self.assembly)})
        self.assertEqual(assembly,self.assembly);self.assertEqual(settings,motion_tasks.parameters('rotary',12,1,30,False,0))

    def test_direct_engine_reuses_validation_before_startup_or_task_creation(self):
        engine=motion_tasks.MotionTaskEngine(self.folder,self.folder/'direct-work',self.folder/'runtime',session_factory=Mock())
        with patch.object(motion_tasks,'prepare_inputs',wraps=motion_tasks.prepare_inputs) as validate,patch.object(motion_tasks.startup_gate,'require_idle') as gate:
            with self.assertRaises(core.StopBatch) as error:engine.prepare(str(self.assembly),duration_s=6)
        self.assertEqual(error.exception.code,'INVALID_MOTION_PARAMETERS');validate.assert_called_once();gate.assert_not_called()
        self.assertIsNone(engine.active);self.assertEqual(engine.tasks,{})


if __name__=='__main__':unittest.main(verbosity=2)
