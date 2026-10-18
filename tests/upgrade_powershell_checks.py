"""Windows PowerShell 5.1 pipeline regression; fake upgrade child, no installer/CAD/network."""
import json
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
        (root / 'scripts/upgrade.py').write_text('import json,sys\nsys.stderr.write("[notice] informational stderr\\n")\nprint(json.dumps({"ok":True,"args":sys.argv[1:],"message":"参数原样保留"},ensure_ascii=False))\nraise SystemExit(37 if "--dry-run" in sys.argv else 0)\n', encoding='utf-8', newline='\n')
        def quote(value): return "'" + str(value).replace("'", "''") + "'"
        for dry in (False, True):
            captured = root / ('dry.json' if dry else 'normal.json')
            expected = [str(root/'scripts/upgrade.py'), '--package', str(root/'package " quote.zip'), '--target', str(root/'target'), '--python', sys.executable]
            command = ("$ErrorActionPreference='Stop'; try { $value = & " + quote(root/'upgrade.ps1') +
                       ' -SourcePackage ' + quote(expected[2]) + ' -TargetDir ' + quote(expected[4]) +
                       ' -PythonPath ' + quote(sys.executable) + (' -DryRun' if dry else '') +
                       ' 2>&1 | Out-String; [IO.File]::WriteAllText(' + quote(captured) + ', $value); exit $LASTEXITCODE } catch { Write-Output $_; exit 91 }')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command], capture_output=True, timeout=30)
            assert result.returncode == (37 if dry else 0), result.stdout + result.stderr
            value = json.loads(captured.read_text(encoding='utf-8-sig'))
            assert value['args'] == expected[1:] + (['--dry-run'] if dry else [])
            assert value['message'] == '参数原样保留'
            assert b'informational stderr' in result.stderr
            rows.append({'dry_run': dry, 'exit_code': result.returncode, 'captured_json': True, 'stderr_did_not_abort': True})
    return {'all_passed': True, 'cases': rows, 'cad_connection_used': False, 'network_used': False}


if __name__ == '__main__': print(json.dumps(check()))
