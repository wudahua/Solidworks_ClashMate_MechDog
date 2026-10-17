import json
import unittest
from pathlib import Path
from unittest.mock import patch

from sw_mcp.jobs import Jobs, verification_fields
from sw_mcp import job_payload
from test_service import temporary_workspace


class VerificationFieldsTests(unittest.TestCase):
    def test_scope_is_explicit_motion_only(self):
        for operation in ("run_user_study", "apply_mate", "probe_motion_compatibility", "reset_study_time"):
            for result in ({"result_validity": "verified"}, {"assertion": "pass"}, None):
                self.assertIsNone(verification_fields(operation, result)["verification_passed"])
        for status, expected in (("pass", True), ("fail", False), ("inconclusive", None)):
            self.assertIs(verification_fields("verify_motion_preservation", {"assertion": status})["verification_passed"], expected)
        self.assertIsNone(verification_fields("verify_motion_preservation", {"assertion": "pass"}, {"code": "RESTORE_FAILED"})["verification_passed"])

    def test_job_error_and_success_both_have_tri_state(self):
        class Bridge:
            cad_operation_state = "available"
            def request(self, operation, **params):
                if params.get("fail"):
                    raise RuntimeError("controlled failure")
                return {"result_validity": "verified"}
        with temporary_workspace() as directory:
            jobs = Jobs(Bridge(), Path(directory))
            ids = [jobs.submit("run_user_study", {"fail": failure})["job_id"] for failure in (True, False)]
            jobs._pool.shutdown(wait=True)
            for identifier in ids:
                record = jobs.get(identifier)
                self.assertIn("verification_passed", record)
                self.assertIsNone(record["verification_passed"])
                self.assertEqual(record["verification_status"], "not_requested")

    def test_orphan_job_is_readable_and_links_saved_request(self):
        class Bridge:
            cad_operation_state = "unknown"
            def get_request_result(self, request_id):
                assert request_id == "b" * 32
                return {"params": {"job_id": "a" * 32}, "operation": "run_user_study", "response": {"ok": True, "result": {"run_id": "c"*32}}}
        with temporary_workspace() as directory:
            root = Path(directory); folder = root / "runs/jobs"; folder.mkdir(parents=True)
            (folder / ("a" * 32 + ".json")).write_text(json.dumps({"job_id": "a"*32, "operation": "run_user_study", "status": "running"}), encoding="utf-8")
            (folder / ("a" * 32 + ".request.json")).write_text(json.dumps({"job_id": "a"*32, "operation": "run_user_study", "request_id": "b"*32}), encoding="utf-8")
            jobs = Jobs(Bridge(), root)
            record = jobs.get("a"*32); jobs._pool.shutdown(wait=True)
            self.assertTrue(record["historical_job_read_only"])
            self.assertEqual(record["status"], "running")
            self.assertEqual(record["late_execution_status"], "completed")
            self.assertFalse(record["automatically_resumed"])


class PayloadTests(unittest.TestCase):
    def test_budget_includes_real_sdk_optional_fields_and_rpc_reserve(self):
        from motion_server import packed
        with temporary_workspace() as directory:
            root = Path(directory)
            for count in range(20, 65):
                job = {"job_id": "a"*32, "status": "succeeded", "operation": "list_mate_references",
                       "result": {"native_%s" % i: "诊断"*25 for i in range(count)}}
                result = job_payload.bound(root, job)
                self.assertLessEqual(len(packed(result).model_dump_json().encode("utf-8"))+256, 16000)

    def test_large_errors_are_bounded_and_losslessly_pageable(self):
        with temporary_workspace() as directory:
            root = Path(directory)
            job = {"job_id": "a"*32, "status": "failed", "operation": "apply_mate", "verification_passed": None,
                   "error": {"code": "MATE_APPLY_ROLLED_BACK", "restoration_status": "restored", "diagnostics": {
                       "rollback_verified": True, "original_error": "MATE_REBUILD_FAILED", "original_failure": {"all_mates": ["原始错误" * 1000] * 100}}}}
            bounded = job_payload.bound(root, job)
            self.assertLessEqual(job_payload.wire_size(bounded), 16000)
            self.assertEqual(bounded["error"]["code"], job["error"]["code"])
            self.assertTrue(bounded["error"]["diagnostics"]["rollback_verified"])
            arguments = bounded["full_response_read"]["arguments"]; parts = []; offset = 0
            while True:
                part = job_payload.read(root, job["job_id"], arguments["response_artifact_id"], offset, 2000)
                self.assertLessEqual(job_payload.wire_size(part), 16000); parts.append(part["text"])
                if part["next_offset"] is None: break
                offset = part["next_offset"]
            self.assertEqual(json.loads("".join(parts)), job)
            path = root / "runs/job-responses" / job["job_id"] / (arguments["response_artifact_id"] + ".json")
            path.write_bytes(b"tampered")
            with self.assertRaises(ValueError): job_payload.read(root, job["job_id"], arguments["response_artifact_id"], 0, 2000)

    def test_no_artifact_for_small_response_and_invalid_reads_rejected(self):
        with temporary_workspace() as directory:
            root = Path(directory); job = {"job_id": "a"*32, "status": "succeeded", "result": {"ok": True}}
            self.assertEqual(job_payload.bound(root, job), job)
            for job_id, artifact, offset, limit in (("../bad", "b"*64, 0, 1), ("a"*32, "../bad", 0, 1), ("a"*32, "b"*64, -1, 1), ("a"*32, "b"*64, 0, 2001)):
                with self.assertRaises(ValueError): job_payload.read(root, job_id, artifact, offset, limit)


class QueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_face_offset_is_component_scoped_and_forwarded(self):
        import motion_server as server
        for name in ("list_mate_references", "list_drive_candidates"):
            tool = getattr(server, name)
            with patch.object(server, "enqueue", return_value={}) as enqueue:
                with self.assertRaises(Exception): await tool("m", face_offset=4, wait_for_completion=False)
                enqueue.assert_not_called()
                await tool("m", component_id="component", face_offset=4, wait_for_completion=False)
                self.assertEqual(enqueue.call_args.args[1]["face_offset"], 4)


if __name__ == "__main__": unittest.main()
