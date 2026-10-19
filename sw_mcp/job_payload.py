"""Bound the public job envelope; retain the exact large response for paged reads."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

BUDGET = 16000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def wire_size(value):
    # Match packed(): both the text and structured result are transmitted.
    return len(encoded({"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                        "structuredContent": value, "isError": False})) + 512


CONTROLS = {"next_cursor", "cursor", "face_offset", "job_id", "checkpoint_id", "plan_id", "model_id", "entity_id", "component_id", "run_id", "response_artifact_id", "next_queries", "next_action", "mate_context_next_query"}
EVIDENCE = {'Axis', 'AxisLocal', 'PointLocal', 'axis_global', 'reference_point_global_m', 'review_items'}
EVIDENCE_CONTAINERS = {'requested_drive', 'native_motor_snapshot', 'parameters', 'direction_reference', 'geometry'}
EVIDENCE_KINDS = ('requested_drive', 'native_motor_snapshot', 'artifacts', 'time_selection_audit',
                  'sampling_performance', 'sampling_api_batch', 'drive_validation', 'review_items', 'solve_performance', 'component_name_resolution', 'baseline_candidate')
EVIDENCE_ALIASES = {'registered_native_motor_before_calculate': 'native_motor_snapshot',
                    'registered_drive_native_reference_observation': 'native_motor_snapshot'}
# Removal order is explicit: performance decoration before conclusions/warnings.
EVIDENCE_DROP_PRIORITY = ('sampling_api_batch','sampling_performance','solve_performance',
                          'time_selection_audit','review_items')
CONCLUSION_FIELDS = {'status','kind','requested','observed_signed','unit','absolute_magnitude_error',
                     'magnitude_tolerance','axis_change_deg','direction_verified','applicability_reason',
                     'native_motor_parameters_match','persistent_reference_error','persistent_reference_error_name',
                     'persistent_reference_resolved','identity_fallback_used','identity_source','inventory_complete',
                     'study_membership','native_feature_id','native_feature_name','component_id'}


def artifact_query(job_id, digest, pointer):
    return {'tool': 'get_job', 'arguments': {'job_id': job_id, 'response_artifact_id': digest,
            'response_json_pointer': pointer, 'offset': 0, 'limit': 2000}}


def evidence_projection(job, digest):
    """Stable typed reads survive every compaction pass; small evidence is inline.

    Never copy arbitrary native containers wholesale into the budget reserve.
    Exact values remain in the SHA-checked response artifact.
    """
    found = {}
    def visit(value, path, depth=0):
        if not isinstance(value, dict) or depth > 10:
            return
        for key, child in value.items():
            if key == 'late_response':
                continue
            pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
            kind = EVIDENCE_ALIASES.get(key, key)
            if kind in EVIDENCE_KINDS and kind not in found:
                found[kind] = (pointer, child)
            if isinstance(child, dict):
                visit(child, pointer, depth + 1)
    for key in ('result', 'error'):
        visit(job.get(key), '/' + key)
    rows = {}
    identity = {key: job.get('result', {}).get(key) for key in
                ('study', 'model_id', 'run_id', 'frames', 'components', 'result_validity', 'duration_s', 'output_fps',
                 'drive_validation_status','physics_validation_status','verification_status','verification_passed','assertion')
                if isinstance(job.get('result'), dict) and key in job['result']
                and not isinstance(job['result'][key], (dict, list)) and len(encoded(job['result'][key])) <= 160}
    if identity:
        rows['result_identity'] = {'path':'/result', 'read':artifact_query(job['job_id'],digest,'/result'), 'value':identity}
    for kind in EVIDENCE_KINDS:
        if kind not in found:
            continue
        pointer, value = found[kind]
        if len(pointer) > 512:
            # Deep, unusually named wrappers remain losslessly available from
            # the containing root. Never manufacture a truncated JSON Pointer.
            pointer, value = ('/error', job['error']) if pointer.startswith('/error/') else ('/result', job['result'])
        row = {'path': pointer, 'read': artifact_query(job['job_id'], digest, pointer)}
        inline = _summary(value)
        if kind == 'component_name_resolution':
            fields = ('schema_version', 'total_elapsed_ms', 'phase_elapsed_ms', 'phase_gap_ms', 'batch_enter_ms',
                      'extension_acquisition_ms', 'component_loop_ms', 'batch_restore_ms', 'export_and_assemble_ms', 'other_elapsed_ms')
            compact = {key: value[key] for key in fields if isinstance(value, dict) and key in value
                       and type(value[key]) in (int, float) and math.isfinite(value[key])}
            if compact and len(encoded(compact)) <= 600:
                row.update(value=compact, value_is_partial=True, value_scope='timing_scalars_only_full_rows_via_read')
            else:
                row['value_omitted_reason']='no_compact_timing_scalars_within_inline_budget'
            rows[kind] = row
            continue
        if wire_size(inline) <= 1600:
            row['value'] = inline
        elif isinstance(value, dict):
            # Axes/points and their owner are a mechanical input identity, not
            # an interpretation of intent. Copy only finite native observations.
            def identity(node, depth=0):
                if not isinstance(node, dict) or depth > 4:
                    return {}
                projected = {}
                for k, v in node.items():
                    if k in EVIDENCE and isinstance(v, list) and len(v) == 3 and all(type(n) in (int, float) and math.isfinite(n) for n in v):
                        projected[k] = v
                    elif k in ({'component_id', 'entity_id', 'study', 'type', 'speed', 'speed_rpm', 'speed_mm_s', 'name',
                                'ComponentId','EntityId','Study','Kind','Speed','Reverse','ReferenceComponentId','MeasurementVersion'} | CONCLUSION_FIELDS) and (v is None or isinstance(v, (str, int, float, bool))) and len(encoded(v)) <= 160 and (type(v) is not float or math.isfinite(v)):
                        projected[k] = v
                    elif isinstance(v, dict):
                        nested = identity(v, depth + 1)
                        if nested:
                            projected[k] = nested
                return projected
            small = identity(value)
            if small and wire_size(small) <= 1600:
                row['value'] = small
                row['value_is_partial'] = True
        rows[kind] = row
    # Critical conclusions and identity degradation flags are a separate small
    # semantic projection, not axes. Keep them even if other inline values go.
    for kind in ('drive_validation','native_motor_snapshot'):
        if kind in found and isinstance(found[kind][1],dict):
            decision={k:v for k,v in found[kind][1].items() if k in CONCLUSION_FIELDS and
                      (v is None or isinstance(v,(str,int,float,bool))) and len(encoded(v))<=160 and
                      (type(v) is not float or math.isfinite(v))}
            priority=('status','persistent_reference_resolved','identity_fallback_used','persistent_reference_error',
                      'persistent_reference_error_name','identity_source','inventory_complete','direction_verified',
                      'kind','unit','requested','observed_signed','magnitude_tolerance','axis_change_deg')
            if wire_size(decision)>2000:
                small={}
                for key in priority:
                    if key in decision and wire_size({**small,key:decision[key]})<=2000:small[key]=decision[key]
                decision=small
                rows[kind]['conclusion_is_partial']=True
            if decision:
                # One semantic projection, never duplicate its conclusion in value.
                rows[kind].pop('value',None)
                rows[kind].pop('value_is_partial',None)
                rows[kind]['conclusion']=decision
    if 'artifacts' in found and isinstance(found['artifacts'][1],dict):
        brief={k:v for k,v in found['artifacts'][1].items() if k in
               {'run_id','manifest_path','time_axis_file','solve_performance_file','solve_performance_sha256'}
               and (v is None or isinstance(v,str)) and len(encoded(v))<=700}
        if brief and wire_size(brief)<=2200 and 'value' not in rows['artifacts']:
            rows['artifacts']['value']=brief;rows['artifacts']['value_is_partial']=True
    # Trim decoration after forming conclusions. Mechanical input identity survives.
    for kind in EVIDENCE_DROP_PRIORITY:
        if wire_size(rows) <= 7500:break
        if kind in rows:
            rows[kind].pop('value',None);rows[kind].pop('value_is_partial',None)
    return rows


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
                             "path_role": "archived_native_response" if path.startswith('/late_response/') else "canonical_failure",
                             "message": str(value.get("message", ""))[:240],
                             "stage": value.get("stage") or (value['diagnostics'].get('stage') if isinstance(value.get('diagnostics'),dict) else None) or (value['details'].get('stage') if isinstance(value.get('details'),dict) else None)})
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
                  summary_omits_details=True, summary_degraded=True, summary_requires_artifact_read=True)
    query = job.get("result", {})
    if isinstance(query, dict) and "next_cursor" in query:
        result["query_controls"] = {k: query[k] for k in ("next_cursor", "geometry_scan", "geometry_complete", "scope_geometry_complete", "model_geometry_complete", "query_scope", "model_scan_state", "client_queue_contract", "total_scope", "warning_codes", "query_completion_status", "client_next_action", "absence_of_kind_proven", "mate_context_complete", "mate_context_scope", "mate_context_warning", "mate_context_next_query", "mate_context_incomplete_reason", "mate_context_incomplete_reasons", "pagination_snapshot", "offset", "returned", "total", "total_semantics", "next_offset", "next_offset_delta", "frozen_pages_complete") if k in query}
    chain = failure_chain(job)
    if chain:
        canonical = [row for row in chain if row['path'].startswith('/error')]
        cause = max(canonical or chain, key=lambda row: row['path'].count('/'))
        result["failure_chain"] = chain
        result["root_cause_code"] = cause["code"]
        result["root_cause_path"] = cause["path"]
        result["root_cause_scope"] = "deepest_reported_failure_not_proven_mechanical_origin"
        result["root_cause_read"] = {"tool": "get_job", "arguments": {
            "job_id": job["job_id"], "response_artifact_id": digest,
            "response_json_pointer": cause["path"], "limit": 2000}}
    if isinstance(query, dict) and isinstance(query.get('entities'), list) and 'next_cursor' in query:
        controls=result['query_controls']
        controls.update(page_data_requires_artifact_read=True, page_read=artifact_query(job['job_id'],digest,'/result'),
                        page_read_instruction='Read the full original page before advancing its cursor; summary rows are not a complete page.')
        # Never present a truncated entity array as a complete callable page.
        if isinstance(result.get('result'),dict):result['result'].pop('entities',None)
    evidence = evidence_projection(job, digest)
    compact_budget = BUDGET - wire_size(evidence) - 700
    if wire_size(result) > compact_budget:
        keep = {"job_id", "operation", "status", "execution_status", "execution_succeeded",
                "verification_passed", "verification_status", "verification_scope", "historical_job_read_only",
                "cad_operation_state", "response_summarized", "payload_budget_bytes", "full_response_bytes",
                "full_response_sha256", "full_response_read", "summary_omits_details", "failure_chain",
                "root_cause_code", "root_cause_path", "root_cause_scope", "root_cause_read", "query_controls",
                "wire_budget_bytes", "full_response_wire_bytes", "payload_budget_scope", "summary_degraded", "summary_requires_artifact_read"}
        result = {k: v for k, v in result.items() if k in keep or k in {"error", "result", "progress"}}
        for k in ("error", "result", "progress"):
            if isinstance(result.get(k), dict):
                result[k] = {n: v for n, v in result[k].items() if not isinstance(v, (list, dict))}
                if k == 'error' and isinstance(job[k].get('next_action'), dict):
                    result[k]['next_action'] = {'automatic_retry': False, 'options': [], 'instruction': '先读取完整失败信封与恢复状态，不自动重试。',
                        'error_read': {**result['full_response_read'], 'arguments': {**result['full_response_read']['arguments'], 'response_json_pointer': '/error'}}}
    if wire_size(result) > compact_budget:
        for key in ("result", "error", "progress"):
            if isinstance(result.get(key), dict):
                keep = {"code", "message", "restoration_status", "stage", "assertion", "verification_status",
                        "model_id", "run_id", "checkpoint_id", "plan_id", "original_error", "write_committed", "rollback_verified", "next_action"}
                result[key] = {k: v for k, v in result[key].items() if k in keep or k in CONTROLS}
    # An indivisible control token must either survive byte-for-byte or be explicitly
    # unavailable with a direct artifact query, never a callable-looking placeholder.
    if wire_size(result) > compact_budget:
        if "query_controls" in result and wire_size({"query_controls": result["query_controls"]}) > min(7000, compact_budget // 2):
            result["query_controls"] = {"controls_require_artifact_read": True, "tool": "get_job", "arguments": {"job_id": job["job_id"], "response_artifact_id": digest, "response_json_pointer": "/result/next_cursor", "limit": 2000}}
            if isinstance(query.get('entities'), list):
                result["query_controls"].update(page_data_requires_artifact_read=True, page_read=artifact_query(job['job_id'],digest,'/result'))
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
        original_action = original_error['next_action']
        for key in ('action_code', 'options_status', 'recovery_state_query'):
            if key in original_action and wire_size(original_action[key]) <= 1200:
                contract['next_action'][key] = original_action[key]
        if wire_size(original_action) <= 2400:
            contract['next_action'] = {**original_action, 'error_read': error_read}
        contract['diagnostics'] = {key: original_error.get('diagnostics', {}).get(key) for key in ('cad_dispatched', 'job_created')}
        contract['diagnostics']['full_error_read'] = error_read
        current = result.get('error', {})
        # Preserve useful diagnostics when they fit; contract fields never vanish
        # merely because a deeper native error required compaction.
        result['error'] = {**contract, **current}
        result['error']['next_action'] = contract['next_action']
        if wire_size(result) > compact_budget: result['error'] = contract
    if evidence:
        result['evidence'] = evidence
    def refresh_omissions():
        omitted = omitted_paths(job, result)
        result['summary_omitted_path_count'] = len(omitted)
        result['summary_omitted_paths'] = []
        result['summary_omitted_paths_shown'] = 0
        result['summary_omitted_paths_truncated'] = bool(omitted)
        result['summary_omitted_paths_limit'] = 16
        result['summary_omitted_paths_limit_scope'] = 'fixed_display_limit_then_wire_budget'
        prefixes={}
        for pointer in omitted:
            prefix='/' + pointer.strip('/').split('/')[0]
            prefixes[prefix]=prefixes.get(prefix,0)+1
        result['summary_omitted_prefix_counts']={key:prefixes[key] for key in sorted(prefixes)[:8]}
        result['summary_omitted_prefix_counts_scope']='omitted_pointer_count_by_top_level_prefix_not_leaf_field_count'
        result['summary_omitted_prefix_counts_truncated']=len(prefixes)>8
        result['summary_omitted_prefix_counts_limit']=8
        return omitted
    omitted = refresh_omissions()
    def stamp():
        # Fit the actual envelope including its own decimal byte counter.
        result['response_wire_bytes'] = 0
        for _ in range(8):
            actual = wire_size(result)
            if result['response_wire_bytes'] == actual: return actual
            result['response_wire_bytes'] = actual
        result.pop('response_wire_bytes', None)
        result['response_wire_counter_status'] = 'not_emitted_nonconvergence'
        return wire_size(result)
    def fit_envelope():
        # All contract restoration and metadata are charged to the FINAL wire
        # envelope. User data must never trigger an assertion in offline reads.
        nonlocal result
        if stamp() <= BUDGET:
            return
        result['summary_degraded'] = True
        result['summary_requires_artifact_read'] = True
        for decoration in ('progress', 'failure_chain'):
            result.pop(decoration, None)
            if stamp() <= BUDGET:
                return
        error = result.get('error')
        if isinstance(error, dict):
            action = error.get('next_action', {})
            diagnostics = error.get('diagnostics')
            if isinstance(diagnostics, dict) and diagnostics.get('full_error_read') == action.get('error_read'):
                diagnostics.pop('full_error_read', None)
            if len(encoded(error.get('message', ''))) > 100:
                error['message'] = str(error.get('message', '')).encode('utf-8')[:96].decode('utf-8', errors='ignore')
                error['message_truncated'] = True
        if stamp() <= BUDGET:
            return
        result.pop('result', None)
        if stamp() <= BUDGET:
            return
        for kind in EVIDENCE_DROP_PRIORITY:
            row = result.get('evidence', {}).get(kind, {})
            row.pop('value', None)
            row.pop('value_is_partial', None)
            if stamp() <= BUDGET:
                return
        # If typed evidence alone fills the budget, retain a small truthful
        # contract and exact SHA-bound root reads. Never emit truncated tokens.
        original_error = job.get('error')
        minimal = {key: result[key] for key in ('job_id', 'status', 'operation', 'execution_status',
                   'verification_status', 'verification_passed', 'response_summarized', 'full_response_bytes', 'full_response_wire_bytes',
                   'full_response_sha256', 'full_response_read', 'wire_budget_bytes', 'payload_budget_bytes',
                   'payload_budget_scope') if key in result}
        minimal.update(summary_degraded=True, summary_requires_artifact_read=True,
                       summary_omits_details=True, evidence_requires_artifact_read=True)
        if isinstance(original_error, dict):
            minimal['error'] = {key: original_error.get(key) for key in
                               ('code', 'assertion', 'restoration_status', 'document_context_restoration_status')}
            minimal['error']['code'] = str(minimal['error']['code'])[:120]
            minimal['error']['message'] = str(original_error.get('message', '')).encode('utf-8')[:96].decode('utf-8', errors='ignore')
            original_action = original_error.get('next_action') or {}
            minimal['error']['next_action'] = {'automatic_retry': False, 'options': [],
                'options_status': str(original_action.get('options_status', 'no_safe_parameter_change_inferred_from_error_code'))[:160],
                'instruction': '先精确读取完整失败工件与恢复状态；不得自行修改确认参数或重试写入。',
                'error_read': artifact_query(job['job_id'], digest, '/error'),
                'recovery_state_query': {'tool': 'get_recovery_state', 'arguments': {}}}
        if result.get('root_cause_read') and wire_size(result['root_cause_read']) < 2200:
            minimal.update({key: result[key] for key in ('root_cause_code', 'root_cause_path', 'root_cause_read')})
        # Preserve small actionable evidence even in the minimal fallback.
        # Each row keeps its exact read; content is charged to the final budget.
        for kind in ('review_items', 'drive_validation', 'native_motor_snapshot'):
            row = evidence.get(kind)
            if not row:
                continue
            small = {key: row[key] for key in ('path', 'read') if key in row}
            if kind == 'review_items' and 'value' in row and len(encoded(row['value'])) <= 600:
                small['value'] = row['value']
            elif 'conclusion' in row and len(encoded(row['conclusion'])) <= 600:
                small['conclusion'] = row['conclusion']
            minimal.setdefault('evidence', {})[kind] = small
            if wire_size(minimal) > BUDGET - 2200:
                minimal['evidence'].pop(kind)
        result = minimal
        refresh_omissions()
        stamp()
    fit_envelope()
    # Reserve small actionable warnings AND timing before display decoration.
    # Reclaim duplicated progress/failure summaries when a few bytes would hide
    # an otherwise short warning. All exact reads and root-cause identity survive.
    for kind in ('review_items', 'solve_performance'):
        row = result.get('evidence', {}).get(kind)
        if row is None or 'value' in row:
            continue
        node = job
        try:
            for token in row['path'][1:].split('/'):
                node = node[token.replace('~1', '/').replace('~0', '~')]
        except (KeyError, TypeError):
            node = None
        value = _summary(node)
        if node is None or wire_size(value) > 1600:
            continue
        row['value'] = value
        for decoration in ('progress', 'failure_chain'):
            if stamp() <= BUDGET - 256:
                break
            result.pop(decoration, None)
        if stamp() > BUDGET - 256:
            error = result.get('error')
            if isinstance(error, dict):
                diagnostics = error.get('diagnostics')
                action = error.get('next_action', {})
                if isinstance(diagnostics, dict) and diagnostics.get('full_error_read') == action.get('error_read'):
                    diagnostics.pop('full_error_read', None)
                if len(str(error.get('message', ''))) > 96:
                    error['message'] = error['message'][:96]
                    error['message_truncated'] = True
        if stamp() > BUDGET:
            row.pop('value')
            stamp()
    omitted = refresh_omissions()
    fit_envelope()
    omitted = refresh_omissions()
    stamp()
    for pointer in omitted:
        if len(result['summary_omitted_paths']) >= 16: break
        result['summary_omitted_paths'].append(pointer)
        result['summary_omitted_paths_shown'] = len(result['summary_omitted_paths'])
        result['summary_omitted_paths_truncated'] = len(result['summary_omitted_paths']) < len(omitted)
        if stamp() > BUDGET:
            result['summary_omitted_paths'].pop()
            result['summary_omitted_paths_shown'] = len(result['summary_omitted_paths'])
            result['summary_omitted_paths_truncated'] = True
            stamp()
    fit_envelope()
    # A metadata refresh can change the decimal counter width; charge it too.
    stamp()
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
