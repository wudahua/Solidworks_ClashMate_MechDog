"""Windows PowerShell 5.1 pipeline regression; fake upgrade child, no installer/CAD/network."""
import json
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from test_service import temporary_workspace

ROOT = Path(__file__).resolve().parents[1]


def check():
    rows = []
    with temporary_workspace() as directory:
        root = Path(directory) / "space ' quote"
        (root / 'scripts').mkdir(parents=True)
        shutil.copyfile(ROOT / 'upgrade.ps1', root / 'upgrade.ps1')
        (root / 'scripts/upgrade.py').write_text('import json,sys,os\nsys.stderr.write("[notice] informational stderr\\n")\nprint(json.dumps({"ok":True,"args":sys.argv[1:],"message":"参数原样保留","encoding":os.environ.get("PYTHONIOENCODING")},ensure_ascii=False))\nraise SystemExit(37 if "--dry-run" in sys.argv else 0)\n', encoding='utf-8', newline='\n')
        def quote(value): return "'" + str(value).replace("'", "''") + "'"
        powershell = shutil.which('powershell.exe')
        if not powershell:
            raise RuntimeError('Windows PowerShell 5.1 is required for this release check')
        probe = subprocess.run([powershell, '-NoProfile', '-Command', "$p=New-Object Diagnostics.ProcessStartInfo; $cold=$p.EnvironmentVariables; @{ps=$PSVersionTable.PSVersion.ToString();clr=[Environment]::Version.ToString();first_environment_getter_is_null=($null -eq $cold)} | ConvertTo-Json -Compress"], capture_output=True, check=True)
        runtime = json.loads(probe.stdout)
        assert runtime['ps'].startswith('5.1.'), runtime
        # New shell per case; do not warm ProcessStartInfo in the tested shell.
        # Run through the reported caller pipeline, both missing/present env.
        clean_env = {k:v for k,v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONIOENCODING'}}
        for index, (dry, previous, start_failure) in enumerate(((False, None, False), (True, 'ascii', False), (False, 'latin-1', True))):
            captured = root / (str(index)+'.json')
            observed = root / (str(index)+'-env.json')
            executable = str(root/'missing-python.exe') if start_failure else sys.executable
            expected = [str(root/'scripts/upgrade.py'), '--package', str(root/'package " quote.zip'), '--target', str(root/'target'), '--python', sys.executable]
            command = ("$ErrorActionPreference='Stop'; try { $value = & " + quote(root/'upgrade.ps1') +
                       ' -SourcePackage ' + quote(expected[2]) + ' -TargetDir ' + quote(expected[4]) +
                       ' -PythonPath ' + quote(executable) + (' -DryRun' if dry else '') +
                       ' 2>&1 | Out-String; $code=$LASTEXITCODE; [IO.File]::WriteAllText(' + quote(captured) + ', $value); '+
                       '[IO.File]::WriteAllText(' + quote(observed) + ", (@{encoding=[Environment]::GetEnvironmentVariable('PYTHONIOENCODING','Process')} | ConvertTo-Json -Compress)); exit $code } catch { Write-Output $_; exit 91 }")
            env = dict(clean_env)
            if previous is not None: env['PYTHONIOENCODING'] = previous
            result = subprocess.run([powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command], env=env, capture_output=True, timeout=30)
            assert result.returncode == (1 if start_failure else 37 if dry else 0), result.stdout + result.stderr
            value = json.loads(captured.read_text(encoding='utf-8-sig'))
            assert json.loads(observed.read_text(encoding='utf-8-sig'))['encoding'] == previous
            if start_failure:
                assert value['code'] == 'UPGRADE_WRAPPER_START_FAILED' and value['python_started'] is False
                assert value['error']['code'] == value['code'] and value['schema_version'] == 2
                assert value['rollback_status'] == 'not_required' and value['safe_to_start_mcp'] is False
                assert value['target_mutation_started'] is False and value['backup_created'] is False
                assert not (root/'target').exists()
            else:
                assert value['args'] == expected[1:] + (['--dry-run'] if dry else [])
                assert value['message'] == '参数原样保留' and value['encoding'] == 'utf-8'
                assert b'informational stderr' in result.stderr
            rows.append({'dry_run': dry, 'start_failure': start_failure, 'exit_code': result.returncode, 'captured_json': True, 'parent_environment_restored': True})
    assert 'EnvironmentVariables[' not in (ROOT/'upgrade.ps1').read_text(encoding='utf-8')
    return {'all_passed': True, 'checks': len(rows), 'cases': rows, 'powershell': powershell, 'runtime': runtime,
            'wrapper_sha256': hashlib.sha256((ROOT/'upgrade.ps1').read_bytes()).hexdigest(),
            'cad_connection_used': False, 'network_used': False}


if __name__ == '__main__': print(json.dumps(check()))
