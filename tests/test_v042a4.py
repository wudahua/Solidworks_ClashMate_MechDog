import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from sw_mcp import job_payload
from test_service import temporary_workspace
from scripts.install_preflight import resolve_solidworks, DLLS


class DiagnosticContractTests(unittest.TestCase):
    def test_deep_root_failure_is_visible_and_directly_readable(self):
        job = {"job_id": "a"*32, "status": "failed", "error": {"code": "RESET_BRANCH_FAILED", "diagnostics": {"details": {
            "original_failure": {"code": "ISOLATED_PROBE_FAILED", "details": {"worker": {"failure": {
                "code": "MODEL_PREFLIGHT_FAILED", "message": "重建失败", "details": {"stage": "reset_branch_rebuild_preflight", "features": ["错误"*200]*100}}}}}}}}}
        with temporary_workspace() as directory:
            root = Path(directory); out = job_payload.bound(root, job)
            self.assertEqual(out["root_cause_code"], "MODEL_PREFLIGHT_FAILED")
            args = out["root_cause_read"]["arguments"]
            page = job_payload.read(root, job["job_id"], args["response_artifact_id"], 0, 2000, args["response_json_pointer"])
            self.assertIn('"code":"MODEL_PREFLIGHT_FAILED"', page["text"])
            self.assertLessEqual(job_payload.wire_size(out), 16000)
            self.assertEqual(page["total_unicode_characters"], page["total_characters"])

    def test_control_cursor_is_never_shortened_in_summary(self):
        token = "abcDEF012_-"*150
        job = {"job_id": "a"*32, "status": "succeeded", "result": {"next_cursor": token, "geometry_complete": False,
               "geometry_scan": {"next_queries": [{"component_id": str(i), "face_offset": i} for i in range(5)]}, "entities": [{"diagnostic": "x"*2000}]*20}}
        with temporary_workspace() as directory:
            out = job_payload.bound(Path(directory), job)
            self.assertEqual(out["query_controls"]["next_cursor"], token)
            self.assertEqual(len(out["query_controls"]["geometry_scan"]["next_queries"]), 5)
            self.assertNotIn("full value", out["query_controls"]["next_cursor"])
            self.assertLessEqual(job_payload.wire_size(out), 16000)

    def test_json_pointer_escaping_and_missing_path(self):
        job = {"job_id": "a"*32, "result": {"a/b~c": {"code": "native", "text": "汉"*20000}}}
        with temporary_workspace() as directory:
            root = Path(directory); out = job_payload.bound(root, job); sha = out["full_response_sha256"]
            page = job_payload.read(root, job["job_id"], sha, 0, 2000, "/result/a~1b~0c/code")
            self.assertEqual(json.loads(page["text"]), "native")
            for pointer in ("/missing", "/result/a~1b~0c/text/2", "not-a-pointer"):
                with self.assertRaises(ValueError): job_payload.read(root, job["job_id"], sha, 0, 10, pointer)

    def test_indivisible_oversize_token_has_explicit_lossless_read(self):
        token = "原始令牌"*6000
        job = {"job_id": "a"*32, "result": {"next_cursor": token}}
        with temporary_workspace() as directory:
            root = Path(directory); out = job_payload.bound(root, job)
            self.assertTrue(out["query_controls"]["controls_require_artifact_read"])
            self.assertNotIn("next_cursor", out.get("result", {}))
            args = out["query_controls"]["arguments"]; parts = []; offset = 0
            while True:
                page = job_payload.read(root, job["job_id"], args["response_artifact_id"], offset, 2000, args["response_json_pointer"])
                parts.append(page["text"])
                if page["next_offset"] is None: break
                offset = page["next_offset"]
            self.assertEqual(json.loads("".join(parts)), token)

    def test_sdk_wire_size_for_root_failure_and_controls(self):
        from motion_server import packed
        job = {"job_id": "a"*32, "error": {"code": "FAILED", "diagnostics": {"original_failure": {"code": "NATIVE", "message": "错"*20000}}}, "result": {"next_cursor": "a"*1000, "data": ["汉"*2000]*20}}
        with temporary_workspace() as directory:
            out = job_payload.bound(Path(directory), job)
            self.assertLessEqual(len(packed(out).model_dump_json().encode()) + 256, 16000)
            self.assertEqual(out["root_cause_code"], "NATIVE")


class InstallationDiscoveryTests(unittest.TestCase):
    def test_nondefault_directory_auto_discovery_and_explicit_precedence(self):
        with temporary_workspace() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory); redist = root/"api/redist"; redist.mkdir(parents=True)
            for name in DLLS: (redist/name).write_bytes(b"interop")
            with patch("scripts.install_preflight.installed_solidworks_candidates", return_value=[str(root), str(root)]):
                self.assertEqual(resolve_solidworks(), root.resolve())
                self.assertEqual(resolve_solidworks(str(root/"bad_explicit")), (root/"bad_explicit").resolve())

    def test_ambiguous_installations_require_explicit_selection(self):
        with temporary_workspace() as directory, patch.dict(os.environ, {}, clear=True):
            roots = [Path(directory)/str(i) for i in range(2)]
            for root in roots:
                (root/"api/redist").mkdir(parents=True)
                for name in DLLS: (root/"api/redist"/name).write_bytes(b"interop")
            with patch("scripts.install_preflight.installed_solidworks_candidates", return_value=list(map(str, roots))):
                with self.assertRaisesRegex(ValueError, "AMBIGUOUS"): resolve_solidworks()


if __name__ == "__main__": unittest.main()
