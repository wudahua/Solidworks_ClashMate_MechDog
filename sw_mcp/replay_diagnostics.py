"""Read the full, hash-bound component diagnostics from the last replay attempt."""
import base64
import hashlib
import json
import re
from sw_mcp.artifacts import ArtifactError
from sw_mcp.replay_images import ReplayImages

def read(root, run_id, limit=20, cursor=''):
    if not isinstance(cursor,str) or len(cursor)>2048:raise ValueError('回放诊断游标格式或长度无效。')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('回放诊断limit须为1–100整数。')
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}',run_id):
        raise ValueError('run_id须为32位小写十六进制。')
    safe=ReplayImages(root);boundary=safe.root/'runs'/run_id
    path=safe._safe(boundary/'replay-check.json',boundary)
    if not path.is_file():raise ArtifactError('REPLAY_DIAGNOSTICS_NOT_RECORDED','尚无已记录回放诊断。')
    if path.stat().st_size>32768:raise ArtifactError('REPLAY_DIAGNOSTICS_INVALID','回放摘要超出读取预算。')
    try:
        meta=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(meta,dict):raise ValueError()
        if 'component_diagnostics_artifact' not in meta:raise ArtifactError('REPLAY_DIAGNOSTICS_NOT_RECORDED','此历史回放只记录受限摘要，未保存完整诊断，不能补造。')
        reference=meta['component_diagnostics_artifact']
        name=reference['file'];digest=reference['sha256']
        if meta['run_id']!=run_id or not re.fullmatch(r'replay-components-[a-f0-9]{32}\.json',name) or not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError()
        full=safe._safe(boundary/name,boundary)
        if full.stat().st_size>2_000_000:raise ValueError()
        raw=full.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError()
        data=json.loads(raw.decode('utf-8-sig'));rows=data['components']
        if data['schema_version']!=1 or data['run_id']!=run_id or data['attempt_id']!=meta['attempt_id'] or data['frame']!=meta['frame'] or not isinstance(rows,list) or len(rows)!=reference['component_count'] or len(rows)!=meta['checked_component_count']:raise ValueError()
        offset=0
        if cursor:
            decoded=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
            if decoded['run_id']!=run_id or decoded['sha256']!=digest or type(decoded['offset']) is not int:raise ValueError()
            offset=decoded['offset']
        if not 0<=offset<=len(rows):raise ValueError()
    except ArtifactError:
        raise
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise ArtifactError('REPLAY_DIAGNOSTICS_INVALID','诊断清单、文件哈希或游标不匹配；未返回未核验数据。') from exc
    page=[]
    for row in rows[offset:offset+limit]:
        if len(json.dumps(page+[row],ensure_ascii=False).encode('utf-8'))>12000:break
        page.append(row)
    if offset<len(rows) and not page:raise ArtifactError('REPLAY_DIAGNOSTICS_BUDGET_EXCEEDED','单条诊断超过分页预算。')
    end=offset+len(page)
    next_cursor=base64.urlsafe_b64encode(json.dumps({'run_id':run_id,'sha256':digest,'offset':end}).encode()).decode().rstrip('=') if end<len(rows) else None
    return {'query_scope':'replay_component_diagnostics','run_id':run_id,'attempt_id':meta['attempt_id'],'frame':meta['frame'],'components':page,'checked_component_count':len(rows),'returned_diagnostic_count':len(page),'next_cursor':next_cursor,'limit_applied':True,'artifact_integrity':'verified','access':'saved_artifacts_without_COM','current_model_validity':'not_checked_offline','replay_within_pose_tolerance':meta['within_pose_tolerance'],'sorting':'maximum_pose_tolerance_ratio_then_instance','response_budget_bytes':16000}
