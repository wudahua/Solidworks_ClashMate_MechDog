"""Content-bound local binaries; never share a native journal or CAD session."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import time
import uuid
from . import core

INTEROP = ('SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll',
           'SolidWorks.Interop.swmotionstudy.dll')
OPTIONS = ('/nologo', '/platform:x64', '/reference:System.Web.Extensions.dll',
           '/reference:System.Windows.Forms.dll', '/reference:Microsoft.CSharp.dll')
BINARIES = ('SwExecutor.exe', 'AcceptanceControl.exe', *INTEROP)


def checked_entry(entry, inputs):
    """Do not execute a cache entry merely because its directory name matches."""
    try:
        core.no_links(entry)
        record = core.read(core.no_links(entry/'build.json'))
        if record['inputs'] != inputs or set(record['artifacts']) != set(BINARIES):
            return False
        return all(core.digest(core.no_links(entry/name)) == record['artifacts'][name]
                   for name in BINARIES)
    except (OSError, ValueError, KeyError, core.StopBatch):
        return False


def compile_cached(runtime, install, folder, helper_source, cache_base=None):
    started = time.monotonic()
    runtime, install, folder = map(Path, (runtime, install, folder))
    redist = install/'api/redist'
    compiler = core.no_links(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    sources = sorted((runtime/'executor').glob('*.cs'))
    helper = runtime/'test_host/AcceptanceControl.cs'
    helper.parent.mkdir(exist_ok=True)
    shutil.copyfile(core.no_links(helper_source), helper)
    core.write(folder/'control-helper-provenance.json', {
        'sha256': core.digest(helper), 'source_sha256': core.digest(helper_source), 'bytes_changed': False})
    inputs = {'format': 1, 'compiler': {'path': str(compiler), 'sha256': core.digest(compiler)},
              'options': list(OPTIONS), 'entry_points': ['Program', 'AcceptanceControl'],
              'sources': {p.name: core.digest(core.no_links(p)) for p in sources},
              'helper_sha256': core.digest(helper),
              'interop': {n: core.digest(core.no_links(redist/n)) for n in INTEROP}}
    support = sorted(compiler.parent.glob('*.dll')) + [compiler.with_suffix('.exe.config'), compiler.with_suffix('.rsp')]
    inputs['framework_support'] = {p.name: core.digest(core.no_links(p)) if p.is_file() else None for p in support}
    import hashlib
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode('utf-8')).hexdigest()
    # Managed runtimes already passed the atomic-metadata path budget. Keep
    # the shared build cache there rather than under a potentially long install.
    # Legacy developer compilation of a full installation stays inside it.
    default_base = (runtime/'runs' if (runtime/'motion_server.py').is_file() else runtime.parent)/'executor-cache-v1'
    base = core.no_links(cache_base or default_base)
    base.mkdir(parents=True, exist_ok=True)
    entry = base/key
    hit = checked_entry(entry, inputs)
    if not hit:
        # Unique immutable build directories avoid half-published entries and
        # do not require deleting a corrupt/in-use binary or a stale lock.
        build = base/(key[:16]+'-build-'+uuid.uuid4().hex[:12])
        build.mkdir()
        for name in INTEROP:
            shutil.copyfile(redist/name, build/name)
        common = [str(compiler), *OPTIONS]+['/reference:'+str(build/n) for n in INTEROP]
        for main, extra, target in [('Program', [], 'SwExecutor.exe'),
                                    ('AcceptanceControl', [helper], 'AcceptanceControl.exe')]:
            run = subprocess.run(common+['/main:'+main, '/out:'+str(build/target)]+
                                 [str(p) for p in sources+extra], capture_output=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/(main+'.compile.log')).write_bytes(run.stdout+run.stderr)
            if run.returncode:
                raise core.StopBatch('COMPILATION_FAILED', '本机编译失败，诊断已保存。')
        # Recheck every build input after compilation, including actual copied DLLs.
        if (inputs['sources'] != {p.name: core.digest(p) for p in sources}
                or inputs['helper_sha256'] != core.digest(helper)
                or inputs['compiler']['sha256'] != core.digest(compiler)
                or inputs['framework_support'] != {p.name: core.digest(p) if p.is_file() else None for p in support}
                or inputs['interop'] != {n: core.digest(redist/n) for n in INTEROP}
                or inputs['interop'] != {n: core.digest(build/n) for n in INTEROP}):
            raise core.StopBatch('CANDIDATE_SOURCE_MISMATCH', '编译期间输入变化，未使用或发布缓存。')
        core.write(build/'build.json', {'inputs': inputs, 'artifacts': {n: core.digest(build/n) for n in BINARIES}})
        if not checked_entry(build, inputs):
            raise core.StopBatch('EXECUTOR_CACHE_INVALID', '构建产物校验失败，未启动执行器。')
        if entry.exists():
            if checked_entry(entry, inputs):
                # Another build completed first. Keep this build as evidence.
                pass
            else:
                core.no_links(entry).rename(base/(key+'-rejected-'+uuid.uuid4().hex[:8]))
                build.rename(entry)
        else:
            try: build.rename(entry)
            except FileExistsError:
                if not checked_entry(entry, inputs):
                    raise core.StopBatch('EXECUTOR_CACHE_INVALID', '并发缓存校验失败。')
    if not checked_entry(entry, inputs):
        raise core.StopBatch('EXECUTOR_CACHE_INVALID', '缓存输入或产物不一致，未执行。')
    binpath = core.no_links(runtime/'executor/bin')
    binpath.mkdir(exist_ok=True)
    record = core.read(entry/'build.json')
    for name in BINARIES:
        target = core.no_links(binpath/name)
        shutil.copyfile(core.no_links(entry/name), target)
        if core.digest(target) != record['artifacts'][name]:
            raise core.StopBatch('EXECUTOR_CACHE_INVALID', '运行目录产物复制校验失败。')
    core.write(folder/'compiled-sources.json', inputs['sources'])
    result = {'cache_hit': hit, 'key': key, 'entry': str(entry), 'artifact_sha256': record['artifacts'],
              'inputs_verified': True, 'copied_binaries_verified': True,
              'compiler_invocations': 0 if hit else 2, 'elapsed_s': time.monotonic()-started,
              'runtime_shared': False, 'native_session_shared': False}
    core.write(folder/'执行器构建回执.json', result)
    return result
