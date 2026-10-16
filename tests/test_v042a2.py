import unittest
from pathlib import Path
from unittest.mock import patch


class QueryAndReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_queries_can_return_job_without_waiting_on_com(self):
        import motion_server as server
        with patch.object(server, "enqueue", return_value={"job_id": "test"}) as enqueue, patch.object(server, "call") as call:
            await server.inspect_model("model", detail_level="components", wait_for_completion=False)
            self.assertEqual(enqueue.call_args.args, ("inspect_model", {"model_id": "model", "detail_level": "components"}))
            await server.list_mate_references("model", component_id="component", wait_for_completion=False)
            self.assertEqual(enqueue.call_args.args[1]["component_id"], "component")
            await server.list_drive_candidates("model", component_id="component", wait_for_completion=False)
            self.assertEqual(enqueue.call_args.args[0], "list_drive_candidates")
            call.assert_not_called()

    async def test_snapshot_replay_is_explicit_and_can_be_queued(self):
        import motion_server as server
        with patch.object(server, "enqueue", return_value={}) as enqueue, patch.object(server, "call") as call:
            await server.replay_motion_frame("run", 15, use_input_snapshot=True, wait_for_completion=False)
            self.assertTrue(enqueue.call_args.args[1]["use_input_snapshot"])
            call.assert_not_called()
        with patch.object(server, "enqueue") as enqueue:
            with self.assertRaises(Exception):
                await server.replay_motion_frame("run", 15, saved_image_only=True, use_input_snapshot=True)
            enqueue.assert_not_called()

    async def test_fps_override_requires_new_model_and_explicit_calculation(self):
        import motion_server as server
        with patch.object(server, "enqueue", return_value={}) as enqueue:
            for options in ({}, {"create_new_model": True}, {"allow_recalculate": True}):
                with self.assertRaises(Exception):
                    await server.reset_study_time("model", "study", reset_output_fps=30, **options)
            enqueue.assert_not_called()
            await server.reset_study_time("model", "study", reset_output_fps=30, create_new_model=True, allow_recalculate=True, checkpoint_id="a"*32)
            self.assertEqual(enqueue.call_args.args[1]["reset_output_fps"], 30)
            self.assertTrue(enqueue.call_args.args[1]["create_new_model"])

    async def test_default_replay_retains_current_input_validation_mode(self):
        import motion_server as server
        async def fake(*args, **kwargs):
            return kwargs
        with patch.object(server, "call", side_effect=fake):
            result = await server.replay_motion_frame("run", 0)
        self.assertFalse(result["use_input_snapshot"])


class VerificationJobTests(unittest.TestCase):
    def test_only_explicit_queued_queries_get_the_long_wait_budget(self):
        from sw_mcp.bridge import Bridge
        bridge = Bridge(Path(__file__).resolve().parents[1], timeout=180, motion_scan_timeout=600)
        for operation in bridge.ASYNC_QUERIES:
            self.assertEqual(bridge._wait_budget(operation, {}), 180)
            self.assertEqual(bridge._wait_budget(operation, {"job_id": "a" * 32}), 600)
            self.assertEqual(bridge._wait_budget(operation, {"job_id": "invalid"}), 180)

    def test_execution_completion_does_not_turn_inconclusive_into_pass(self):
        from test_service import temporary_workspace
        from sw_mcp.jobs import Jobs
        class Bridge:
            cad_operation_state = "available"
            def request(self, operation, **params):
                return {"verification_status": "inconclusive", "assertion": "inconclusive"}
        with temporary_workspace() as directory:
            jobs = Jobs(Bridge(), Path(directory))
            submitted = jobs.submit("verify_motion_preservation", {})
            jobs._pool.shutdown(wait=True)
            job = jobs.get(submitted["job_id"])
            self.assertEqual(job["status"], "succeeded")
            self.assertIsNone(job["verification_passed"])
            self.assertTrue(job["execution_succeeded"])
            self.assertFalse(job["service_observation_is_native_progress"])


if __name__ == "__main__":
    unittest.main()
