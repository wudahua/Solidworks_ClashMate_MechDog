"""Read previously verified frame images; never move or open a CAD model."""
import hashlib
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from sw_mcp.artifacts import ArtifactError


class ReplayImages:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _safe(self, path, boundary):
        if not path.resolve().is_relative_to(boundary):
            raise ArtifactError('IMAGE_PATH_INVALID', '历史截图路径越过运行目录。')
        current = path
        while current != self.root:
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise ArtifactError('IMAGE_PATH_INVALID', '历史截图路径不能包含链接。')
            if current.parent == current:
                raise ArtifactError('IMAGE_PATH_INVALID', '历史截图不在本安装目录。')
            current = current.parent
        return path

    def _metadata(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise ValueError('run_id 必须是32位小写十六进制。')
        boundary = self.root/'runs'/run_id
        self._safe(boundary, boundary)
        if not boundary.is_dir():
            raise ArtifactError('RUN_NOT_FOUND', '运行目录不存在；请核对本安装目录的 run_id。')
        folder = self._safe(boundary/'screenshots', boundary)
        if not folder.exists():
            return boundary, []
        files = list(folder.glob('*.json'))
        if len(files) > 2000:
            raise ArtifactError('IMAGE_BUDGET_EXCEEDED', '截图记录超过2000项读取预算。')
        rows, total = [], 0
        for path in files:
            self._safe(path, boundary)
            if not re.fullmatch(r'[a-f0-9]{32}\.json', path.name) or path.stat().st_size > 32768:
                raise ArtifactError('IMAGE_MANIFEST_INVALID', '截图清单名称或大小不合法。')
            raw = path.read_bytes(); total += len(raw)
            if len(raw) > 32768 or total > 8_388_608:
                raise ArtifactError('IMAGE_BUDGET_EXCEEDED', '截图清单超过读取预算。')
            try:
                data = json.loads(raw.decode('utf-8-sig'))
                if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('run_id') != run_id or data.get('attempt_id')+'.json' != path.name:
                    raise ValueError()
                frame, time = data['frame'], data['time_s']
                if type(frame) is not int or frame < 0 or type(time) not in (int,float) or not math.isfinite(time) or time < 0:
                    raise ValueError()
                image = data['image_file']
                if not isinstance(image, str) or not re.fullmatch(r'motion-frame-'+str(frame)+r'-'+data['attempt_id']+r'\.bmp', image):
                    raise ValueError()
                for key in ('image_sha256','poses_sha256'):
                    if not isinstance(data.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', data[key]):
                        raise ValueError()
                if data.get('pose_assertion') != 'pass' or data.get('restoration_status') != 'restored' or data['pose_validation']['within_pose_tolerance'] is not True:
                    raise ValueError()
                pose = data['pose_validation']
                if pose.get('frame') != frame or type(pose.get('checked_component_count')) is not int or pose['checked_component_count'] < 1:
                    raise ValueError()
                for observed_key, tolerance_key, maximum_tolerance in (
                    ('maximum_translation_difference_m','translation_tolerance_m',1e-7),
                    ('maximum_rotation_difference_rad','rotation_tolerance_rad',1e-6)):
                    observed_value, tolerance = pose[observed_key], pose[tolerance_key]
                    if type(observed_value) not in (int,float) or type(tolerance) not in (int,float) or not math.isfinite(observed_value) or not math.isfinite(tolerance) or not 0 < tolerance <= maximum_tolerance or not 0 <= observed_value <= tolerance:
                        raise ValueError()
                if not isinstance(data.get('captured_at_utc'), str):
                    raise ValueError()
                captured = datetime.fromisoformat(data['captured_at_utc'].replace('Z','+00:00'))
                if captured.tzinfo is None or captured.utcoffset() != timezone.utc.utcoffset(captured):
                    raise ValueError()
            except (ValueError, KeyError, TypeError, UnicodeError) as error:
                raise ArtifactError('IMAGE_MANIFEST_INVALID', '截图清单身份、帧或核验状态不匹配。') from error
            data['metadata_path'] = str(path); rows.append(data)
        return boundary, sorted(rows, key=lambda r:(r['captured_at_utc'],r['attempt_id']), reverse=True)

    def _verified(self, data, boundary):
        csv_path = self._safe(boundary/'component-poses.csv', boundary)
        image = self._safe(boundary/data['image_file'], boundary)
        if not csv_path.is_file() or csv_path.stat().st_size > 100_000_000 or not image.is_file() or image.stat().st_size > 20_000_000:
            raise ArtifactError('IMAGE_ARTIFACT_MISSING', '历史截图或其姿态数据缺失、过大。')
        for path, expected in ((csv_path,data['poses_sha256']),(image,data['image_sha256'])):
            with path.open('rb') as stream:
                observed = hashlib.file_digest(stream,'sha256').hexdigest()
            if observed != expected:
                raise ArtifactError('IMAGE_HASH_MISMATCH', '历史截图或姿态 CSV 的哈希与截图清单不符。')
        components = set()
        try:
            with csv_path.open(encoding='utf-8-sig',newline='') as stream:
                for index, row in enumerate(csv.DictReader(stream)):
                    if index >= 100000:
                        raise ValueError('row budget')
                    if int(row['frame']) == data['frame']:
                        time = float(row['time_s'])
                        if not math.isfinite(time) or abs(time-data['time_s']) > 1e-7 or row['component_id'] in components:
                            raise ValueError('frame identity')
                        components.add(row['component_id'])
            if len(components) != data['pose_validation']['checked_component_count']:
                raise ValueError('component coverage')
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            raise ArtifactError('IMAGE_POSE_IDENTITY_MISMATCH','历史截图的帧时间或全组件覆盖与姿态 CSV 不匹配。') from error
        return {'run_id':data['run_id'], 'model_id':data.get('model_id'), 'attempt_id':data['attempt_id'], 'frame':data['frame'], 'time_s':data['time_s'], 'image_path':str(image), 'metadata_path':data['metadata_path'], 'image_sha256':data['image_sha256'], 'poses_sha256':data['poses_sha256'], 'captured_at_utc':data['captured_at_utc'], 'recorded_pose_assertion':'pass', 'recorded_restoration_status':'restored', 'capture_scope':data.get('capture_scope'), 'artifact_integrity':'verified', 'historical_image':True, 'current_model_validity':'not_checked_offline', 'fresh_cad_replay_performed':False, 'physical_validation_claim':False, 'access':'saved_image_without_COM', 'warning':'既有截图及文件完整性已核对；未重算或核验当前CAD模型，不提供独立物理精度证明。'}

    def list(self, run_id):
        boundary, rows = self._metadata(run_id)
        images = [self._verified(data,boundary) for data in rows[:5]]
        return {'status':'available' if images else 'no_recorded_verified_images', 'total':len(rows), 'returned':len(images), 'truncated':len(rows)>len(images), 'images':images, 'query':{'tool':'replay_motion_frame','saved_image_only':True}, 'legacy_bmp_without_manifest':'not_promoted_to_verified_image'}

    def frame(self, run_id, frame):
        if type(frame) is not int or frame < 0:
            raise ValueError('frame 须为非负整数。')
        boundary, rows = self._metadata(run_id)
        selected = next((row for row in rows if row['frame']==frame), None)
        if selected is None:
            raise ArtifactError('SAVED_FRAME_IMAGE_NOT_FOUND', '该帧没有已登记的核验截图；历史 CSV 不等于图像。新截图可用输入匹配的CAD回放；本版本新run若有绑定快照，可显式use_input_snapshot=True独立重算；无绑定快照的旧run不能猜测重建。')
        return self._verified(selected,boundary)
