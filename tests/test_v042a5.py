import copy
import json
import time
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from sw_mcp import job_payload
from sw_mcp.jobs import Jobs
from sw_mcp.native_grid import require_grid
from test_service import temporary_workspace


class QueryAndDiagnosticsTests(unittest.TestCase):
    def test_short_grid_rejected_before_any_dispatch_with_working_alternatives(self):
        import motion_server
        for duration, fps in ((.1, 30), (.3, 30)):
            with self.assertRaisesRegex(ValueError, "OUTPUT_GRID_TOO_SPARSE"):
                require_grid(duration, fps)
        for duration, fps in ((.1, 100), (.5, 30), (1/3, 30)):
            require_grid(duration, fps)
        with patch("motion_server.enqueue") as enqueue:
            for call in (
                motion_server.create_motion_study("none", "test", "c", "e", "rotary", 10, duration_s=.1),
                motion_server.run_motion_study("none", "test", duration_s=.1),
                motion_server.verify_motion_preservation("none", "test", "c", "e", "rotary", 1, duration_s=.1),
                motion_server.preflight_motion("none", "test", compatibility_probe=True, probe_duration_s=.1),
            ):
                with self.assertRaisesRegex(ValueError, "OUTPUT_GRID_TOO_SPARSE"):
                    asyncio.run(call)
            enqueue.assert_not_called()

    def test_scoped_summary_retains_unknown_model_and_parent_queue_contract(self):
        result = {"next_cursor": None, "geometry_complete": False,
                  "scope_geometry_complete": True, "model_geometry_complete": None,
                  "query_scope": "single_component_from_face_offset",
                  "model_scan_state": "unknown_client_must_retain_parent_pending_queue",
                  "client_queue_contract": {"retain_parent_pending_queries": True},
                  "geometry_scan": {"pending_query_count": None, "scope_pending_query_count": 0},
                  "entities": [{"data": "x" * 9000}] * 4}
        with temporary_workspace() as folder:
            out = job_payload.bound(Path(folder), {"job_id": "a" * 32, "result": result})
            controls = out["query_controls"]
            self.assertFalse(controls["geometry_complete"])
            self.assertTrue(controls["scope_geometry_complete"])
            self.assertIsNone(controls["model_geometry_complete"])
            self.assertIsNone(controls["geometry_scan"]["pending_query_count"])
            self.assertTrue(controls["client_queue_contract"]["retain_parent_pending_queries"])
            self.assertLessEqual(job_payload.wire_size(out), 16000)

    def test_identical_late_error_uses_canonical_pointer(self):
        error = {"code": "WRAPPED", "details": {"original_failure": {"code": "NATIVE", "message": "失败", "details": {"stage": "add"}}}}
        job = {"job_id": "a"*32, "error": error,
               "late_response": {"response": {"error": copy.deepcopy(error)}}, "padding": "x"*10000}
        with temporary_workspace() as folder:
            root = Path(folder); out = job_payload.bound(root, job)
            self.assertEqual([r["code"] for r in out["failure_chain"]], ["WRAPPED", "NATIVE"])
            self.assertEqual(out["root_cause_path"], "/error/details/original_failure")
            args = out["root_cause_read"]["arguments"]
            data = job_payload.read(root, job["job_id"], args["response_artifact_id"], 0, 2000, args["response_json_pointer"])
            self.assertEqual(json.loads(data["text"])["code"], "NATIVE")

    def test_distinct_failures_with_same_code_and_message_not_collapsed(self):
        error = {"code": "NATIVE", "message": "same", "details": {"component": "a"}}
        other = {**error, "details": {"component": "b"}}
        rows = job_payload.failure_chain({"error": error, "late_response": {"response": {"error": other}}})
        self.assertEqual(len(rows), 2)

    def test_reset_warning_and_comparison_scope_survive_summary(self):
        with temporary_workspace() as folder:
            out = job_payload.bound(Path(folder), {"job_id": "a"*32, "result": {
                "warning_codes": ["RESET_CACHED_MEMORY_POSE_DEVIATION_SUPERSEDED_BY_VERIFIED_REOPEN"],
                "cached_memory_pose_deviation": {"maximum_translation_m": .4, "cached_memory_matches_reopened_file": False},
                "pose_change_scope": "pre_operation_live_vs_reopened_saved_document_not_zero_pose_oracle",
                "committed_pose_validation": {"within_pose_tolerance": True}, "data": "x"*20000}})
            self.assertTrue(out["result"]["warning_codes"])
            self.assertFalse(out["result"]["cached_memory_pose_deviation"]["cached_memory_matches_reopened_file"])
            self.assertTrue(out["result"]["committed_pose_validation"]["within_pose_tolerance"])

    def test_progress_wait_has_elapsed_without_inventing_fraction(self):
        class Bridge:
            cad_operation_state = "idle"
        with temporary_workspace() as folder:
            root = Path(folder); jobs = Jobs(Bridge(), root); job_id = "a"*32
            jobs._jobs[job_id] = {"job_id": job_id, "operation": "reset_study_time", "status": "running", "started_at": 100.0}
            p = root/"runs/progress"; p.mkdir(parents=True)
            (p/(job_id+".json")).write_text(json.dumps({"job_id": job_id, "stage": "waiting_owned_exit", "stage_started_at": 110.0, "completed": 0, "total": 0}))
            with patch("sw_mcp.jobs.time.time", return_value=120.0): out = jobs.get(job_id)
            self.assertEqual(out["progress"]["elapsed_s"], 20.0)
            self.assertEqual(out["progress"]["current_stage_elapsed_ms"], 10000.0)
            self.assertFalse(out["progress"]["fraction_known"])
            jobs._pool.shutdown(wait=True)


if __name__ == "__main__": unittest.main()
