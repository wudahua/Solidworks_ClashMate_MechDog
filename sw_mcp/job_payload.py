"""Bound the public job envelope; retain the exact large response for paged reads."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

BUDGET = 16000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def wire_size(value):
    # Match packed(): both the text and structured result are transmitted.
    return len(encoded({"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                        "structuredContent": value, "isError": False})) + 512


CONTROLS = {"next_cursor", "cursor", "face_offset", "job_id", "checkpoint_id", "plan_id", "model_id", "entity_id", "component_id", "run_id", "response_artifact_id", "next_queries", "next_action"}
EVIDENCE = {'Axis', 'AxisLocal', 'PointLocal', 'axis_global', 'reference_point_global_m', 'review_items'}
EVIDENCE_CONTAINERS = {'requested_drive', 'native_motor_snapshot', 'parameters', 'direction_reference', 'geometry'}


def _summary(value, depth=0, key=""):
    if key in CONTROLS or key in EVIDENCE:
        return value
    if isinstance(value, dict):
        return {k: _summary(v, depth + 1, k) for k, v in value.items()
                if k not in {"late_response", "native_diagnostics", "original_failure", "rollback_failure", "stage_timeline"}
                and (depth < 4 or not isinstance(v, (list, dict)) or k in CONTROLS or k in EVIDENCE or k in EVIDENCE_CONTAINERS)}
    if isinstance(value, list):
        return [_summary(v, depth + 1) for v in value[:8]]
    if isinstance(value, str) and len(value) > 800:
        return value[:800] + "…[full value in response artifact]"
    return value


def omitted_paths(original, summary, path=''):
    """Pointers into the exact artifact; a parent pointer covers omitted children."""
    rows = []
    if isinstance(original, dict) and isinstance(summary, dict):
        for key, value in original.items():
            pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
            rows.extend([pointer] if key not in summary else omitted_paths(value, summary[key], pointer))
    elif isinstance(original, list) and isinstance(summary, list):
        if len(original) > len(summary): rows.append(path)
        for index, value in enumerate(summary): rows.extend(omitted_paths(original[index], value, path + '/' + str(index)))
    elif original != summary: rows.append(path)
    return rows


def failure_chain(value, path="", rows=None, seen=None):
    """Bounded error pointers, never infer a mechanical cause from names."""
    rows = [] if rows is None else rows
    seen = set() if seen is None else seen
    if isinstance(value, dict):
        if isinstance(value.get("code"), str):
            # Deduplicate only identical error subtrees, never merely the same
            # code/message from distinct operations. Canonical /error is visited first.
            identity = encoded(value)
            if identity not in seen:
                seen.add(identity)
                rows.append({"code": value["code"][:120], "path": path,
                             "message": str(value.get("message", ""))[:240],
                             "stage": value.get("stage", value.get("details", {}).get("stage") if isinstance(value.get("details"), dict) else None)})
        for k in ("error", "diagnostics", "details", "original_failure", "failure", "worker", "cause_details", "original_details", "late_response", "response"):
            if k in value and len(rows) < 12:
                failure_chain(value[k], path + "/" + k, rows, seen)
    return rows


def bound(root: Path, job: dict):
    if wire_size(job) <= BUDGET:
        return job
    data = encoded({k: v for k, v in job.items() if k != "service_observed_at"})
    digest = hashlib.sha256(data).hexdigest()
    folder = root / "runs" / "job-responses" / job["job_id"]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (digest + ".json")
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
    result = _summary(job)
    result.update(response_summarized=True, payload_budget_bytes=BUDGET,
                  wire_budget_bytes=BUDGET, full_response_wire_bytes=wire_size(job),
                  payload_budget_scope='estimated_MCP_text_plus_structuredContent_and_512_byte_reserve',
                  full_response_bytes=len(data), full_response_sha256=digest,
                  full_response_read={"tool": "get_job", "arguments": {
                      "job_id": job["job_id"], "response_artifact_id": digest, "offset": 0, "limit": 2000}},
                  summary_omits_details=True)
    query = job.get("result", {})
    if isinstance(query, dict) and "next_cursor" in query:
        result["query_controls"] = {k: query[k] for k in ("next_cursor", "geometry_scan", "geometry_complete", "scope_geometry_complete", "model_geometry_complete", "query_scope", "model_scan_state", "client_queue_contract", "total_scope", "warning_codes", "query_completion_status", "client_next_action", "absence_of_kind_proven") if k in query}
    chain = failure_chain(job)
    if chain:
        result["failure_chain"] = chain
        result["root_cause_code"] = chain[-1]["code"]
        result["root_cause_path"] = chain[-1]["path"]
        result["root_cause_scope"] = "deepest_reported_failure_not_proven_mechanical_origin"
        result["root_cause_read"] = {"tool": "get_job", "arguments": {
            "job_id": job["job_id"], "response_artifact_id": digest,
            "response_json_pointer": chain[-1]["path"], "limit": 2000}}
    if wire_size(result) > BUDGET:
        keep = {"job_id", "operation", "status", "execution_status", "execution_succeeded",
                "verification_passed", "verification_status", "verification_scope", "historical_job_read_only",
                "cad_operation_state", "response_summarized", "payload_budget_bytes", "full_response_bytes",
                "full_response_sha256", "full_response_read", "summary_omits_details", "failure_chain",
                "root_cause_code", "root_cause_path", "root_cause_scope", "root_cause_read", "query_controls",
                "wire_budget_bytes", "full_response_wire_bytes", "payload_budget_scope"}
        result = {k: v for k, v in result.items() if k in keep or k in {"error", "result", "progress"}}
        for k in ("error", "result", "progress"):
            if isinstance(result.get(k), dict):
                result[k] = {n: v for n, v in result[k].items() if not isinstance(v, (list, dict))}
                if k == 'error' and isinstance(job[k].get('next_action'), dict):
                    result[k]['next_action'] = {'automatic_retry': False, 'options': [], 'instruction': '先读取完整失败信封与恢复状态，不自动重试。',
                        'error_read': {**result['full_response_read'], 'arguments': {**result['full_response_read']['arguments'], 'response_json_pointer': '/error'}}}
    if wire_size(result) > BUDGET:
        for key in ("result", "error", "progress"):
            if isinstance(result.get(key), dict):
                keep = {"code", "message", "restoration_status", "stage", "assertion", "verification_status",
                        "model_id", "run_id", "checkpoint_id", "plan_id", "original_error", "write_committed", "rollback_verified", "next_action"}
                result[key] = {k: v for k, v in result[key].items() if k in keep or k in CONTROLS}
    # An indivisible control token must either survive byte-for-byte or be explicitly
    # unavailable with a direct artifact query, never a callable-looking placeholder.
    if wire_size(result) > BUDGET:
        if "query_controls" in result and wire_size({"query_controls": result["query_controls"]}) > 7000:
            result["query_controls"] = {"controls_require_artifact_read": True, "tool": "get_job", "arguments": {"job_id": job["job_id"], "response_artifact_id": digest, "response_json_pointer": "/result/next_cursor", "limit": 2000}}
        result.pop("failure_chain", None)
        result.pop("progress", None)
        for key in ("result", "error"):
            if isinstance(result.get(key), dict):
                result[key] = {k: v for k, v in result[key].items() if k in {"code", "restoration_status", "next_action"}}
    if isinstance(job.get('error'), dict) and isinstance(job['error'].get('next_action'), dict):
        original_error = job['error']
        error_read = {'tool': 'get_job', 'arguments': {'job_id': job['job_id'], 'response_artifact_id': digest, 'response_json_pointer': '/error', 'limit': 2000}}
        contract = {key: original_error.get(key) for key in ('code', 'message', 'assertion', 'restoration_status', 'document_context_restoration_status')}
        contract['message'] = str(contract['message'] or '')[:800]
        contract['next_action'] = {'automatic_retry': False, 'instruction': '先读取完整失败诊断并核对 get_recovery_state，不自动重试。', 'options': [], 'error_read': error_read}
        contract['diagnostics'] = {key: original_error.get('diagnostics', {}).get(key) for key in ('cad_dispatched', 'job_created')}
        contract['diagnostics']['full_error_read'] = error_read
        current = result.get('error', {})
        # Preserve useful diagnostics when they fit; contract fields never vanish
        # merely because a deeper native error required compaction.
        result['error'] = {**contract, **current}
        if wire_size(result) > BUDGET: result['error'] = contract
    omitted = omitted_paths(job, result)
    result['summary_omitted_path_count'] = len(omitted)
    result['summary_omitted_paths'] = omitted[:16]
    result['summary_omitted_paths_truncated'] = len(omitted) > 16
    if wire_size(result) > BUDGET:
        result['summary_omitted_paths'] = ['/']
        result['summary_omitted_paths_truncated'] = True
    assert wire_size(result) <= BUDGET
    return result


def read(root: Path, job_id: str, artifact: str, offset: int, limit: int, json_pointer: str = ""):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id or "") or not re.fullmatch(r"[a-f0-9]{64}", artifact or ""):
        raise ValueError("需要完整 job_id 和响应中返回的 response_artifact_id。")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 2000:
        raise ValueError("offset 须为非负字符位置，limit 须在 1–2000。")
    path = root / "runs" / "job-responses" / job_id / (artifact + ".json")
    current = path
    while current != root:
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise ValueError("拒绝链接响应工件路径。")
        current = current.parent
    try:
        data = path.read_bytes()
    except OSError:
        raise ValueError("未找到该任务的完整响应工件。") from None
    if hashlib.sha256(data).hexdigest() != artifact:
        raise ValueError("响应工件 SHA256 不符，拒绝返回。")
    text = data.decode("utf-8")
    if json_pointer:
        if not json_pointer.startswith("/") or len(json_pointer) > 2048:
            raise ValueError("response_json_pointer 须为 RFC6901 路径，最长2048字符。")
        value = json.loads(text)
        try:
            for token in json_pointer[1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if not re.fullmatch(r"0|[1-9][0-9]*", token):
                        raise ValueError("invalid array index")
                    value = value[int(token)]
                else:
                    value = value[token]
        except (KeyError, IndexError, ValueError, TypeError):
            raise ValueError("响应工件中不存在该 JSON 路径。") from None
        text = encoded(value).decode("utf-8")
    if offset > len(text):
        raise ValueError("offset 超出响应工件。")
    end = min(len(text), offset + limit)
    while True:
        result = {"job_id": job_id, "response_artifact_id": artifact, "artifact_integrity": "verified",
                  "offset": offset, "offset_unit": "unicode_characters", "text": text[offset:end],
                  "next_offset": end if end < len(text) else None, "total_characters": len(text),
                  "total_unicode_characters": len(text), "response_json_pointer": json_pointer,
                  "access": "offline_saved_response_no_COM", "current_model_validity": "not_checked_offline"}
        if wire_size(result) <= BUDGET:
            return result
        end = offset + max(1, (end - offset) // 2)
