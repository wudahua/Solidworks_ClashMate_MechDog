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
    from .install_preflight import preflight
    from .lease_access import open_lease_file, lease_diagnostics
except ImportError:
    from verify_release import safe_relative, reject_links, validate_manifest, verify
    from install_preflight import preflight
    from lease_access import open_lease_file, lease_diagnostics


class UpgradeFailure(RuntimeError):
    def __init__(self, code, message, state=None, diagnostics=None):
        super().__init__(message)
        self.code, self.state, self.diagnostics = code, dict(state or {}), diagnostics or {}

    def payload(self):
        state = self.state
        rollback = state.get('rollback_status', 'not_required')
        instruction = ('源码或二进制回滚未完整核验；不要启动 MCP。保留备份、回执和恢复日志，人工核对后修复安装。'
                       if rollback in {'incomplete', 'unknown'} else
                       '按 receipt_path 核对已验证的源码/二进制回滚；依赖环境不在快照回滚范围，不自动重试。' if rollback == 'verified' else
                       '核对 code、stage 和诊断后显式处理；未自动停止进程、修改权限或重试升级。')
        if self.code in {'UPGRADE_LEASE_BUSY', 'UPGRADE_EXECUTOR_ACTIVE'}:
            instruction = '停用目标安装目录及其他客户端中的本项目 MCP，等待执行器退出后显式重新预检；不删除锁或恢复日志，不结束不明进程。'
        if self.code == 'UPGRADE_EXECUTOR_ABANDONED':
            instruction = '原生互斥体返回 WAIT_ABANDONED；保留并检查恢复日志，不能视为正常空闲或直接重试升级。'
        return {'ok': False, 'schema_version': 2, 'upgrade_result_schema_version': 1, 'code': self.code,
                **{key: state.get(key) for key in ('stage','failure_stage','python_started','target_mutation_started','backup_created','receipt_path','receipt_stage_persisted','receipt_write_error','committed','rollback_attempted','rollback_verified','rollback_status','recovery_journal_unchanged','installation_state')},
                'processes_stopped': False, 'automatic_retry': False,
                'safe_to_start_mcp': False,
                'managed_files_consistent': not state.get('target_mutation_started', False) or rollback == 'verified',
                'error': {'code': self.code, 'message': str(self), 'stage': state.get('stage'),
                          'diagnostics': {**self.diagnostics, 'rollback_errors': state.get('rollback_errors', []),
                                          'original_failure_message': state.get('error'), 'target_directory': state.get('target_directory'),
                                          'mutation_scope': 'managed_source_and_executor_binaries_not_dependency_environment'},
                          'next_action': {'automatic_retry': False, 'instruction': instruction,
                                          'receipt_path': state.get('receipt_path')}}}

def package_files(package):
    package=Path(package);sidecar=package.with_suffix(package.suffix+'.sha256')
    try:text=sidecar.read_text(encoding='utf-8-sig').strip()
    except FileNotFoundError as error:
        raise UpgradeFailure('UPGRADE_SIDECAR_MISSING', '缺少同名同目录的 ZIP.sha256；请从可信发布页取得 ZIP 与匹配边车。', diagnostics={'package':str(package),'required_sidecar':str(sidecar)}) from error
    parts=text.split()
    if not parts or not re.fullmatch(r'[a-fA-F0-9]{64}',parts[0]):raise ValueError('Invalid ZIP SHA256 sidecar')
    if len(parts)>1 and ' '.join(parts[1:]).lstrip('*')!=package.name:
        expected=' '.join(parts[1:]).lstrip('*')
        raise ValueError('SHA256 filename mismatch: expected '+expected+'; actual '+package.name+'. Rename the local ZIP to the expected filename, retain the matching .sha256 sidecar, and retry. Filename and digest checks remain strict.')
    if package.stat().st_size>50_000_000:raise ValueError('ZIP exceeds source package budget')
    digest=hashlib.sha256(package.read_bytes()).hexdigest()
    if digest!=parts[0].lower():raise ValueError('ZIP SHA256 mismatch')
    contents={};total=0;archive_root=None
    with zipfile.ZipFile(package) as z:
        if len(z.infolist())>1000:raise ValueError('Too many source entries')
        for entry in z.infolist():
            if entry.is_dir():continue
            name=entry.filename
            prefix, separator, remainder=name.partition('/')
            if not separator or prefix not in {'Solidworks_ClashMate_MechDog','SolidWorksMotionMCP'}:raise ValueError('Unexpected ZIP root')
            if archive_root is not None and archive_root!=prefix:raise ValueError('Mixed ZIP roots refused')
            archive_root=prefix
            relative=safe_relative(remainder).as_posix()
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
    try:file=open_lease_file(path)
    except OSError as error:
        diagnostics=lease_diagnostics(path,error,'open_lease')
        raise UpgradeFailure('UPGRADE_LEASE_BUSY' if diagnostics['sharing_conflict_proven'] else 'UPGRADE_LEASE_ACCESS_FAILED',
                             '锁文件存在共享冲突；停用相关服务或检查占用句柄。' if diagnostics['sharing_conflict_proven'] else '无法打开升级锁；权限、属性或过滤器原因尚未区分，不证明服务正在运行。',diagnostics=diagnostics) from error
    mutex=None;owned=False;locked=False
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p];kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint];kernel.WaitForSingleObject.restype=ctypes.c_uint
    kernel.ReleaseMutex.argtypes=[ctypes.c_void_p];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    try:
        if file.seek(0,2)==0:file.write(b'0');file.flush()
        file.seek(0)
        try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1);locked=True
        except OSError as error:raise UpgradeFailure('UPGRADE_LEASE_BUSY','Stop this installation MCP service before upgrading; no process was stopped',diagnostics={**lease_diagnostics(path,error,'lock_lease'),'byte_lock_conflict_observed':True}) from error
        mutex=kernel.CreateMutexW(None,False,'Local\\SolidWorksClashMate_MechDog_Executor')
        if not mutex:raise RuntimeError('Cannot verify executor mutex')
        status=kernel.WaitForSingleObject(mutex,0);owned=status in (0,0x80)
        if status!=0:
            code='UPGRADE_EXECUTOR_ACTIVE' if status==0x102 else 'UPGRADE_EXECUTOR_ABANDONED' if status==0x80 else 'UPGRADE_MUTEX_WAIT_FAILED'
            raise UpgradeFailure(code,'Executor active or previously abandoned; preserve journal and inspect before upgrading',diagnostics={'stage':'executor_mutex','wait_status':status,'wait_status_name':{0x102:'WAIT_TIMEOUT',0x80:'WAIT_ABANDONED'}.get(status,'WAIT_FAILED_OR_UNKNOWN'),'lease_path':str(path),'owner_pid':None,'owner_identity_status':'not_proven'})
        yield
    finally:
        if owned:kernel.ReleaseMutex(mutex)
        if mutex:kernel.CloseHandle(mutex)
        if locked:file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
        file.close()

def upgrade(package,target,python,solidworks_dir='',dry_run=False,install=True):
    state={'schema_version':2,'upgrade_result_schema_version':1,'stage':'validating_target','python_started':True,'target_mutation_started':False,
           'backup_created':False,'receipt_path':None,'committed':False,'rollback_attempted':False,
           'rollback_verified':None,'rollback_status':'not_required','installation_state':'unchanged',
           'recovery_journal_unchanged':None,'target_directory':str(Path(target).absolute())}
    try:return _upgrade(package,target,python,solidworks_dir,dry_run,install,state)
    except Exception as error:
        code=error.code if isinstance(error,UpgradeFailure) else {
            'validating_target':'UPGRADE_TARGET_INVALID','validating_package':'UPGRADE_PACKAGE_INVALID',
            'installation_preflight':'UPGRADE_PREFLIGHT_FAILED'}.get(state['stage'],'UPGRADE_FAILED')
        if isinstance(error,ValueError) and re.match(r'^[A-Z][A-Z0-9_]+:',str(error)):
            code=str(error).split(':',1)[0]
        raise UpgradeFailure(code,str(error),state,getattr(error,'diagnostics',{'error_type':type(error).__name__,'errno':getattr(error,'errno',None),'winerror':getattr(error,'winerror',None)})) from error


def _upgrade(package,target,python,solidworks_dir,dry_run,install,state):
    target=Path(target).absolute()
    if not target.is_dir():raise ValueError('Target must be an existing installation directory')
    if target.resolve()!=target:raise ValueError('Aliased installation root refused')
    if not (target/'motion_server.py').is_file() or not (target/'executor').is_dir():raise ValueError('Target is not a recognized MCP installation')
    reject_links(target,target)
    # Check every destination and its ancestors before changing any source file.
    state['stage']='validating_package'
    manifest,contents,digest=package_files(package)
    for name in contents:reject_links(target/safe_relative(name),target)
    for protected in ('.venv','runs','experiments','upgrade-backups','executor/bin'):reject_links(target/protected,target)
    plan={'version':manifest['version'],'zip_sha256':digest,'source_files':len(manifest['files']),'preserved_directories':['.venv','runs','experiments'],'dry_run':dry_run}
    state['stage']='installation_preflight'
    if install:
        plan['installation_preflight']=preflight(target,python,solidworks_dir)
        solidworks_dir=plan['installation_preflight']['solidworks_install_dir']
    else:
        plan['installation_preflight']={'prerequisites_checked':False,'scope':'source_only_install_false'}
    if dry_run:
        state['stage']='checking_installation_lease'
        with idle_installation(target):
            plan['executor_lease_available']=True
        return {**state,**plan,'stage':'dry_run_complete'}
    state['stage']='checking_installation_lease'
    with idle_installation(target):
        if install:
            state['stage']='installation_preflight_under_lease'
            preflight(target,python,solidworks_dir)
        state['stage']='read_recovery_journal'
        journal=target/'runs/executor-state.json';before=journal.read_bytes() if journal.exists() else None
        state['stage']='creating_backup'
        backup=target/'upgrade-backups'/uuid.uuid4().hex;backup.mkdir(parents=True)
        state.update(plan,backup_directory=str(backup),backup_created=True,receipt_path=str(backup/'receipt.json'),rollback_verified=False,stage='backing_up')
        status=state
        def receipt(stage):
            status['stage']=stage
            temporary=backup/'receipt.tmp'
            try:
                temporary.write_text(json.dumps({**status,'receipt_stage_persisted':stage},ensure_ascii=False,indent=2),encoding='utf-8')
                temporary.replace(backup/'receipt.json')
            except OSError as error:
                status['receipt_write_error']=str(error)
                raise
            status['receipt_stage_persisted']=stage
        receipt('backing_up')
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
        receipt('backup_complete')
        try:
            status['target_mutation_started']=True
            status['installation_state']='changing_managed_files'
            receipt('copying_sources')
            for name,data in contents.items():
                p=target/safe_relative(name);reject_links(p,target);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            verify(target)
            receipt('sources_verified')
            if install:
                receipt('installing_and_compiling')
                if not Path(python).is_file():raise ValueError('Specify an existing base Python runtime')
                command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(target/'install.ps1'),'-PythonPath',str(python)]
                if solidworks_dir:command+=['-SolidWorksInstallDir',solidworks_dir]
                subprocess.run(command,check=True)
            final_integrity=verify(target)
            receipt('verifying_commit')
            after=journal.read_bytes() if journal.exists() else None
            if before!=after:raise RuntimeError('Recovery journal changed unexpectedly; preserve backup and inspect')
            status.update(committed=True,installation_state='upgraded',rollback_status='not_required',recovery_journal_unchanged=True,source_integrity_verified=True,final_source_files=final_integrity['source_files'],environment_scope='existing_venv_validated_by_install_not_snapshot_rollback',executor_compiled=install)
        except Exception as error:
            # Delete only newly introduced managed files, with bounds checked individually.
            status.update(failure_stage=status['stage'],rollback_attempted=True,rollback_status='unknown')
            rollback_errors=[]
            for name,p in managed.items():
                try:
                    reject_links(p,target)
                    if name in existing:shutil.copy2(backup/name,p)
                    elif p.is_file():p.unlink()
                except Exception as failure:rollback_errors.append(str(failure))
            for name,p in managed.items():
                try:
                    reject_links(p,target)
                    if name in existing:
                        if p.read_bytes()!=(backup/name).read_bytes():raise RuntimeError('Restored bytes mismatch: '+name)
                    elif p.exists():raise RuntimeError('New managed file remains: '+name)
                except Exception as failure:rollback_errors.append(str(failure))
            try:journal_unchanged=(journal.read_bytes() if journal.exists() else None)==before
            except OSError as journal_error:
                journal_unchanged=None;status['journal_observation_error']=str(journal_error)
            status.update(error=str(error),rollback_verified=not rollback_errors,rollback_errors=rollback_errors,
                          rollback_status='verified' if not rollback_errors else 'incomplete',installation_state='restored_managed_files' if not rollback_errors else 'mixed_or_unknown',
                          recovery_journal_unchanged=journal_unchanged)
            receipt('failed_rollback_verified' if not rollback_errors else 'failed_rollback_incomplete')
            raise UpgradeFailure('UPGRADE_FAILED_ROLLBACK_VERIFIED' if not rollback_errors else 'UPGRADE_FAILED_ROLLBACK_INCOMPLETE',
                                 'Upgrade failed; source/binary rollback verified; inspect receipt before retry' if not rollback_errors else 'Upgrade failed; rollback INCOMPLETE. Do not start MCP; preserve backup and receipt for manual repair') from error
        receipt('completed');return status

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--target',required=True);parser.add_argument('--python',required=True);parser.add_argument('--solidworks-install-dir',default='');parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    try:result=upgrade(args.package,args.target,args.python,args.solidworks_install_dir,args.dry_run)
    except UpgradeFailure as error:print(json.dumps(error.payload(),ensure_ascii=False));return 1
    print(json.dumps({'ok':True,**result},ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
