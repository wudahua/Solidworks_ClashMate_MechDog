"""Read-only installation prerequisites, shared by upgrade planning and installation."""
import argparse
import ctypes
import json
import os
from pathlib import Path
try:
    from .validate_runtime import identity, validate
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validate_runtime import identity, validate

DLLS = ('SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll', 'SolidWorks.Interop.swmotionstudy.dll')


def preflight(target, python, solidworks_dir='', *, check_access=True):
    target = Path(target).resolve()
    selected = identity(str(python))
    if selected['prefix'] != selected['base_prefix']:
        raise ValueError('PYTHON_RUNTIME_MISMATCH: -PythonPath must select the base Python; use ' + selected['base_executable'])
    if selected['bits'] != 64 or tuple(selected['version']) < (3, 11):
        raise ValueError('PYTHON_RUNTIME_MISMATCH: 64-bit Python 3.11+ required')
    venv = target / '.venv'
    if venv.exists():
        if not (venv / 'Scripts/python.exe').is_file():
            raise ValueError('PYTHON_RUNTIME_MISMATCH: existing .venv is incomplete; no files were changed')
        validate(selected, identity(str(venv / 'Scripts/python.exe')), venv)
    sw = Path(solidworks_dir or os.environ.get('SW_INSTALL_DIR') or r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS').resolve()
    missing = [str(sw / 'api/redist' / name) for name in DLLS if not (sw / 'api/redist' / name).is_file()]
    if missing:
        raise ValueError('SOLIDWORKS_BUILD_PREREQUISITES_MISSING: specify -SolidWorksInstallDir or SW_INSTALL_DIR; resolved ' + str(sw) + '; missing ' + ', '.join(missing))
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise ValueError('X64_COMPILER_MISSING: ' + str(compiler))
    if check_access:
        if os.name != 'nt':
            raise ValueError('Installation requires Windows')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateFileW(str(target), 2, 7, None, 3, 0x02000000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ValueError('TARGET_ACCESS_DENIED: target directory does not grant file creation access')
        kernel.CloseHandle(handle)
    return {'prerequisites_checked': True, 'base_python': selected['executable'], 'venv_identity': 'matched' if venv.exists() else 'will_create',
            'solidworks_install_dir': str(sw), 'x64_compiler': str(compiler), 'target_directory_access': 'checked' if check_access else 'not_checked',
            'not_checked': ['future_pip_network_and_package_installation', 'native_compilation_result'],
            'guarantees_install_success': False}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--target', required=True); p.add_argument('--python', required=True); p.add_argument('--solidworks-install-dir', default=''); a = p.parse_args()
    try:
        result = preflight(a.target, a.python, a.solidworks_install_dir)
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=True)); return 1
    print(json.dumps({'ok': True, **result}, ensure_ascii=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
