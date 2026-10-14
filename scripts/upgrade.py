"""Verified source upgrade with local backup; preserve CAD data and recovery journal."""
import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
try:
    from .verify_release import safe_relative, reject_links, validate_manifest, verify
except ImportError:
    from verify_release import safe_relative, reject_links, validate_manifest, verify

def package_files(package):
    package=Path(package);sidecar=package.with_suffix(package.suffix+'.sha256')
    text=sidecar.read_text(encoding='utf-8-sig').strip();parts=text.split()
    if not parts or not re.fullmatch(r'[a-fA-F0-9]{64}',parts[0]):raise ValueError('Invalid ZIP SHA256 sidecar')
    if len(parts)>1 and ' '.join(parts[1:]).lstrip('*')!=package.name:raise ValueError('SHA256 filename mismatch')
    if package.stat().st_size>50_000_000:raise ValueError('ZIP exceeds source package budget')
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    if digest!=parts[0].lower():raise ValueError('ZIP SHA256 mismatch')
    contents={};total=0
    with zipfile.ZipFile(package) as z:
        if len(z.infolist())>1000:raise ValueError('Too many source entries')
        for entry in z.infolist():
            if entry.is_dir():continue
            name=entry.filename
            if not name.startswith('SolidWorksMotionMCP/'):raise ValueError('Unexpected ZIP root')
            relative=safe_relative(name[len('SolidWorksMotionMCP/'):]).as_posix()
            if entry.external_attr>>16&0o170000==0o120000:raise ValueError('Linked ZIP entry refused')
            if relative.casefold() in {n.casefold() for n in contents}:raise ValueError('Duplicate ZIP path')
            total+=entry.file_size
            if entry.file_size>8_000_000 or total>100_000_000:raise ValueError('Expanded source package exceeds budget')
            contents[relative]=z.read(entry)
    manifest=json.loads(contents['发布清单.json'].decode('utf-8-sig'));names=validate_manifest(manifest,contents.__getitem__)
    if set(contents)!=names|{'发布清单.json'}:raise ValueError('ZIP has unlisted files')
    return manifest,contents,digest

@contextmanager
def idle_installation(root):
    """Take the same per-installation lease; never kill or stop the existing owner."""
    if os.name!='nt':raise RuntimeError('Upgrade requires Windows')
    folder=root/'runs';reject_links(folder,root);folder.mkdir(exist_ok=True)
    path=folder/'executor-owner.lock';reject_links(path,root)
    import msvcrt
    file=path.open('a+b');mutex=None;owned=False;locked=False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint];kernel.WaitForSingleObject.restype=ctypes.c_uint
    kernel.ReleaseMutex.argtypes=[ctypes.c_void_p];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    try:
        if file.seek(0,2)==0:file.write(b'0');file.flush()
        file.seek(0)
        try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1);locked=True
        except OSError as error:raise RuntimeError('Stop this installation MCP service before upgrading; no process was stopped') from error
        mutex=kernel.CreateMutexW(None,False,'Local\\SolidWorksClashMate_MechDog_Executor')
        if not mutex:raise RuntimeError('Cannot verify executor mutex')
        status=kernel.WaitForSingleObject(mutex,0);owned=status in (0,0x80)
        if status!=0:raise RuntimeError('Executor active or previously abandoned; preserve journal and inspect before upgrading')
        yield
    finally:
        if owned:kernel.ReleaseMutex(mutex)
        if mutex:kernel.CloseHandle(mutex)
        if locked:file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
        file.close()

def upgrade(package,target,python,solidworks_dir='',dry_run=False,install=True):
    target=Path(target).absolute()
    if not target.is_dir():raise ValueError('Target must be an existing installation directory')
    if target.resolve()!=target:raise ValueError('Aliased installation root refused')
    if not (target/'motion_server.py').is_file() or not (target/'executor').is_dir():raise ValueError('Target is not a recognized MCP installation')
    reject_links(target,target)
    # Check every destination and its ancestors before changing any source file.
    manifest,contents,digest=package_files(package)
    for name in contents:reject_links(target/safe_relative(name),target)
    for protected in ('.venv','runs','experiments','upgrade-backups','executor/bin'):reject_links(target/protected,target)
    plan={'version':manifest['version'],'zip_sha256':digest,'source_files':len(manifest['files']),'preserved_directories':['.venv','runs','experiments'],'dry_run':dry_run}
    if dry_run:return plan
    with idle_installation(target):
        journal=target/'runs/executor-state.json';before=journal.read_bytes() if journal.exists() else None
        backup=target/'upgrade-backups'/uuid.uuid4().hex;backup.mkdir(parents=True)
        managed={n:target/safe_relative(n) for n in contents};existing=set()
        bin_dir=target/'executor/bin'
        for name in ('SwExecutor.exe','build-manifest.json','SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll'):
            managed['executor/bin/'+name]=bin_dir/name
        if bin_dir.exists():
            for p in bin_dir.iterdir():
                reject_links(p,target)
                if p.is_file():managed[p.relative_to(target).as_posix()]=p
        for name,p in managed.items():
            reject_links(p,target)
            if p.exists():
                if not p.is_file():raise ValueError('Source destination is not a file: '+name)
                saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,saved);existing.add(name)
        status={**plan,'backup_directory':str(backup),'committed':False,'rollback_verified':False}
        try:
            for name,data in contents.items():
                p=target/safe_relative(name);reject_links(p,target);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            verify(target)
            if install:
                if not Path(python).is_file():raise ValueError('Specify an existing base Python runtime')
                command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(target/'install.ps1'),'-PythonPath',str(python)]
                if solidworks_dir:command+=['-SolidWorksInstallDir',solidworks_dir]
                subprocess.run(command,check=True)
            after=journal.read_bytes() if journal.exists() else None
            if before!=after:raise RuntimeError('Recovery journal changed unexpectedly; preserve backup and inspect')
            status.update(committed=True,recovery_journal_unchanged=True,environment_scope='existing_venv_validated_by_install_not_snapshot_rollback',executor_compiled=install)
        except Exception as error:
            # Delete only newly introduced managed files, with bounds checked individually.
            rollback_errors=[]
            for name,p in managed.items():
                try:
                    reject_links(p,target)
                    if name in existing:shutil.copy2(backup/name,p)
                    elif p.is_file():p.unlink()
                except Exception as failure:rollback_errors.append(str(failure))
            status.update(error=str(error),rollback_verified=not rollback_errors,rollback_errors=rollback_errors,recovery_journal_unchanged=(journal.read_bytes() if journal.exists() else None)==before)
            (backup/'receipt.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
            raise RuntimeError('Upgrade failed; source/binary rollback recorded at '+str(backup/'receipt.json')) from error
        (backup/'receipt.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8');return status

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--target',required=True);parser.add_argument('--python',required=True);parser.add_argument('--solidworks-install-dir',default='');parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    try:result=upgrade(args.package,args.target,args.python,args.solidworks_install_dir,args.dry_run)
    except Exception as error:print(json.dumps({'ok':False,'error':str(error),'processes_stopped':False},ensure_ascii=False));return 1
    print(json.dumps({'ok':True,**result},ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
