"""Offline access to operation-scoped CAD save observations and legacy traces."""
import base64
import hashlib
import json
import re
from pathlib import Path
from sw_mcp.artifacts import ArtifactError


class SaveObservations:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _safe(self, path, boundary):
        if not path.resolve().is_relative_to(boundary):
            raise ArtifactError("OBSERVATION_PATH_INVALID", "保存观测路径越过登记模型目录。")
        current = path
        while current != self.root:
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise ArtifactError("OBSERVATION_PATH_INVALID", "保存观测路径不能包含链接或目录重定向。")
            if current.parent == current:
                raise ArtifactError("OBSERVATION_PATH_INVALID", "保存观测目录不在本安装目录。")
            current = current.parent
        return path

    def _read(self, path, boundary, budget=1_048_576):
        self._safe(path, boundary)
        if not path.is_file():
            raise ArtifactError("OBSERVATION_NOT_FOUND", "保存观测文件不存在；请核对本安装目录及操作标识。")
        if path.stat().st_size > budget:
            raise ArtifactError("OBSERVATION_BUDGET_EXCEEDED", "保存观测文件超过读取预算。")
        raw = path.read_bytes()
        if len(raw) > budget:
            raise ArtifactError("OBSERVATION_BUDGET_EXCEEDED", "保存观测文件超过读取预算。")
        try:
            value = json.loads(raw.decode('utf-8-sig'))
        except (ValueError, UnicodeError) as error:
            raise ArtifactError("OBSERVATION_INVALID", "保存观测文件格式损坏；保留原文件。") from error
        if not isinstance(value, dict):
            raise ArtifactError("OBSERVATION_INVALID", "保存观测不是合法对象。")
        return value, hashlib.sha256(raw).hexdigest()

    def read(self, model_id, operation_id='', limit=5, cursor='', include_file_hashes=False):
        if not isinstance(model_id, str) or not re.fullmatch(r'user_[a-f0-9]{32}', model_id):
            raise ValueError('model_id 必须是完整登记标识。')
        if not isinstance(operation_id,str) or operation_id and not re.fullmatch(r'(?:[a-f0-9]{32}|legacy_[a-f0-9]{64})', operation_id):
            raise ValueError('operation_id 须为32位操作标识，或升级摘要给出的 legacy_ 加 SHA256。')
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('limit 须在1–20。')
        boundary = self.root/'experiments/user_assemblies'/model_id[5:]
        selected = operation_id
        archived = selected.startswith('legacy_')
        manifest = boundary/'save-observations/legacy'/(selected[7:]+'.json') if archived else boundary/'save-observations'/selected/'operation.json' if selected else boundary/'last-save-observation.json'
        data, digest = self._read(manifest, boundary, 8_388_608 if archived else 1_048_576)
        if archived and digest != selected[7:]:
            raise ArtifactError('OBSERVATION_HASH_MISMATCH','归档旧观测文件的 SHA256 不匹配。')
        if data.get('model_id') != model_id:
            raise ArtifactError('OBSERVATION_INVALID', '保存观测所属模型不匹配。')
        legacy = not data.get('operation_id')
        if not legacy:
            selected = data['operation_id']
            if not isinstance(selected, str) or not re.fullmatch(r'[a-f0-9]{32}', selected) or operation_id and selected != operation_id:
                raise ArtifactError('OBSERVATION_INVALID', '保存观测操作身份不匹配。')
            manifest = boundary/'save-observations'/selected/'operation.json'
            data, digest = self._read(manifest, boundary, 4096)
            if data.get('schema_version') != 1 or data.get('model_id') != model_id or data.get('operation_id') != selected:
                raise ArtifactError('OBSERVATION_INVALID', '保存观测清单身份或版本不匹配。')
        stages = data.get('stages', [])
        if not isinstance(stages,list):
            raise ArtifactError('OBSERVATION_INVALID', '保存观测阶段列表不合法。')
        total = len(stages) if legacy else data.get('stage_count')
        if not isinstance(stages, list) or type(total) is not int or not 0 <= total <= 10000:
            raise ArtifactError('OBSERVATION_INVALID', '保存观测阶段数量不合法。')
        identity = {'model_id': model_id, 'operation_id': selected, 'sha256': digest, 'include_file_hashes': include_file_hashes}
        offset = 0
        if cursor:
            try:
                token = json.loads(base64.b64decode(cursor, validate=True))
                offset = token['offset']
                if any(token.get(k) != v for k, v in identity.items()) or type(offset) is not int or not 0 <= offset <= total:
                    raise ValueError()
            except (ValueError, KeyError, TypeError) as error:
                raise ArtifactError('OBSERVATION_CURSOR_STALE', '保存观测已改变或游标无效；从第一页重新查询。') from error
        rows = []
        response = {'model_id': model_id, 'operation_id': selected or None, 'operation_name': data.get('operation_name'), 'scope': 'legacy_model_cumulative_trace' if legacy else 'recorded_stages_of_one_operation', 'legacy_without_operation_identity': legacy, 'access': 'saved_artifacts_without_COM', 'current_model_validity': 'not_checked_offline', 'physical_validation_claim': False, 'total_stages': total, 'requested_limit': limit, 'payload_budget_bytes': 16000, 'manifest_path': str(manifest), 'include_file_hashes': include_file_hashes, 'stages': rows}
        def finish():
            response['returned'] = len(rows)
            response['next_cursor'] = base64.b64encode(json.dumps({**identity, 'offset': offset+len(rows)}).encode()).decode() if offset+len(rows) < total else None
            return len(json.dumps(response, ensure_ascii=False).encode('utf-8'))
        for i in range(offset, min(total, offset+limit)):
            if legacy:
                if not isinstance(stages[i],dict):
                    raise ArtifactError('OBSERVATION_INVALID', '旧保存观测阶段不是合法对象。')
                item = dict(stages[i]); item['artifact_integrity'] = 'not_recorded_legacy'
                path = manifest
            else:
                path = manifest.parent/f'{i+1:010d}.json'
                item, observed = self._read(path, boundary)
                checksum = self._safe(Path(str(path)+'.sha256'), boundary)
                if not checksum.is_file() or checksum.stat().st_size > 128 or checksum.read_text(encoding='utf-8').strip() != observed:
                    raise ArtifactError('OBSERVATION_HASH_MISMATCH', '保存观测阶段的哈希与记录不符。')
                if item.get('model_id') != model_id or item.get('operation_id') != selected or item.get('sequence_number') != i+1:
                    raise ArtifactError('OBSERVATION_INVALID', '保存观测阶段身份或序号不匹配。')
                item['artifact_integrity'] = 'verified'
            item['full_record_path'] = str(path)
            if not include_file_hashes:
                item.pop('file_hashes', None)
            rows.append(item)
            if finish() > 16000:
                if len(rows) > 1:
                    rows.pop(); break
                # One large record stays on disk; return an explicit bounded reference.
                reduced = {k: item[k] for k in ('schema_version','model_id','operation_id','operation_name','sequence_number','stage','observed_at_utc','model_revision','artifact_integrity','full_record_path') if k in item}
                reduced.update(full_record_omitted=True, omission_reason='single_record_byte_budget')
                rows[0] = reduced
                if finish() > 16000:
                    raise ArtifactError('OBSERVATION_BUDGET_EXCEEDED', '保存观测摘要仍超过响应预算。')
                break
        finish()
        _, current_digest = self._read(manifest, boundary, 8_388_608 if archived else 1_048_576)
        if current_digest != digest:
            raise ArtifactError('OBSERVATION_CURSOR_STALE', '读取期间保存观测新增阶段；请重新查询。')
        return response
