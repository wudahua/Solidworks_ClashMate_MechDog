"""Choose and audit a writable, budget-compliant runtime without global policy edits."""
import os
import uuid
from pathlib import Path
from . import core


def choose_runtime(requested, work):
    requested = Path(requested).absolute()
    candidates = [requested]
    local = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
    candidates.extend([local / 'CMChat' / 'r', Path(os.environ.get('TEMP', str(local))) / 'CMChat' / 'r'])
    failures = []
    for candidate in dict.fromkeys(candidates):
        try:
            candidate = core.no_links(candidate)
            budget = core.runtime_path_budget(candidate / '000000')
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ('.write-probe-' + uuid.uuid4().hex)
            with probe.open('xb') as f:
                f.write(b'probe')
            probe.unlink()
            receipt = {'requested': str(requested), 'resolved': str(candidate),
                       'automatic_fallback': candidate != requested, 'budget': budget,
                       'rejected_candidates': failures, 'CAD_started': False,
                       'global_long_path_policy_changed': False}
            core.write(Path(work) / '运行目录选择.json', receipt)
            return candidate
        except (OSError, core.StopBatch) as error:
            failures.append({'path': str(candidate), 'code': getattr(error, 'code', type(error).__name__),
                             'message': str(error)})
    raise core.StopBatch('RUNTIME_LOCATION_UNAVAILABLE', '无法自动选出可写且满足路径预算的目录，诊断已保留。',
                         {'candidates': failures, 'CAD_started': False})
