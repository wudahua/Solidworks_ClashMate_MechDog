"""Reproduce every release policy entry point. No CAD is started or connected."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Alpha.4 Python diagnostic contracts are in test_v042a4.py and are run by
# unittest discover. This list contains standalone policy compiler entry points.
SUITES = (
    'alpha5_evidence_checks', 'session_connection_checks', 'axis_convention_checks',
    'installation_powershell_checks', 'alpha8_policy_checks', 'alpha9_policy_checks',
    'study_history_v04', 'upgrade_powershell_checks', 'v042_policy_checks', 'v042a1_policy_checks',
    'v042a2_policy_checks', 'v042a3_policy_checks', 'v042a5_policy_checks', 'v042a7_policy_checks', 'v042a8_policy_checks',
)


def main():
    from check_entrypoints import ENTRIES as registry
    scripts = {p.stem for p in (ROOT/'tests').glob('*_checks.py')}
    unclassified = scripts - set(registry)
    assert not unclassified, 'Classify new check entry points before release: ' + ', '.join(sorted(unclassified))
    for name in scripts:
        mode = registry[name]['mode']
        assert mode in {'offline_suite', 'unittest', 'manual_offline', 'native_cad'}, (name, mode)
        if mode == 'offline_suite': assert name in SUITES, 'Offline entry is not wired: ' + name
        if mode == 'unittest':
            caller = ROOT/'tests'/registry[name]['caller']
            assert caller.is_file() and ('from '+name+' import') in caller.read_text(encoding='utf-8'), name
    results = []
    for suite in SUITES:
        completed = subprocess.run([sys.executable, str(ROOT/'tests'/(suite+'.py'))],
                                   cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if completed.returncode:
            print(completed.stdout); print(completed.stderr, file=sys.stderr)
            raise SystemExit(completed.returncode)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        assert result['all_passed'] and result['cad_connection_used'] is False
        results.append({'suite': suite, **result})
        print(suite, result['checks'], 'PASS', flush=True)
    report = {'all_passed': True, 'cad_connection_used': False, 'entry_points': len(results), 'classified_check_scripts': len(scripts),
              'executed_checks_including_historical_overlap': sum(r['checks'] for r in results), 'suites': results}
    target = ROOT/'runs/offline-policy-suite.json'; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='suites'}))


if __name__ == '__main__': main()
