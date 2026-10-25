"""Task input integrity uses frozen CAD inputs, never a mutable workspace tree."""
from pathlib import Path
import re
from . import core

CAD_SUFFIXES={'.sldasm','.sldprt','.slddrw'}


def snapshot_record(source):
    source=core.no_links(source)
    files=[p for p in sorted(source.parent.rglob('*')) if p.is_file()]
    return {'source_hashes':{p.relative_to(source.parent).as_posix():core.digest(core.no_links(p))
            for p in files if p.suffix.lower() in CAD_SUFFIXES and not p.name.startswith('~$')},
            'source_workspace_files':[p.relative_to(source.parent).as_posix() for p in files]}


def snapshot(source):return snapshot_record(source)['source_hashes']


def normalized_hash(value):
    if isinstance(value,str) and (re.fullmatch('[a-fA-F0-9]{64}',value) or re.fullmatch('(?:[a-fA-F0-9]{2}-){31}[a-fA-F0-9]{2}',value)):
        return value.replace('-','').lower()
    return None


def bind(task,session):
    """Use the importer's exact frozen dependency catalog, including external files.

    The assembly and any pre-observed local CAD inputs must match the admission
    snapshot; binding cannot bless a change that happened during discovery.
    """
    if task.get('source_dependency_hashes'):return
    model=getattr(session,'model',None);runtime=getattr(session,'runtime',None)
    if not runtime or not model or not re.fullmatch('user_[a-f0-9]{32}',model):return
    path=core.no_links(Path(runtime)/'experiments/user_assemblies'/model[5:]/'import-evidence.json')
    if not path.is_file():return
    rows=core.read(path).get('source_hashes')
    source=core.no_links(Path(task['source']));old=task['source_hashes'];values={}
    if not isinstance(rows,dict) or not rows:raise core.StopBatch('SOURCE_CHANGED','导入依赖清单为空或无效。',{'evidence_path':str(path)})
    for name,digest in rows.items():
        digest=normalized_hash(digest)
        p=Path(name)
        if not p.is_absolute() or digest is None:
            raise core.StopBatch('SOURCE_CHANGED','导入依赖身份无效。',{'evidence_path':str(path)})
        p=core.no_links(p)
        try:relative=p.relative_to(source.parent).as_posix()
        except ValueError:relative=None
        if relative in old and old[relative]!=digest:
            raise core.StopBatch('SOURCE_CHANGED','导入前后源文件发生变化，未重绑基线。',
                {'changed':[{'path':str(p),'before_sha256':old[relative],'after_sha256':digest}]})
        values[str(p)]=digest
    if values.get(str(source))!=old.get(source.name):
        raise core.StopBatch('SOURCE_CHANGED','导入依赖清单未绑定原装配体哈希。',{'evidence_path':str(path)})
    task.update(source_dependency_hashes=values,source_hash_scope='native_import_frozen_dependencies',
                source_dependency_evidence={'path':str(path),'sha256':core.digest(path)})


def review(task,session=None):
    if session:bind(task,session)
    source=core.no_links(Path(task['source']));baseline=task.get('source_dependency_hashes')
    if not baseline:
        # Compatibility with alpha.12 records containing the entire workspace.
        baseline={str(core.no_links(source.parent/name)):digest for name,digest in task['source_hashes'].items()
                  if Path(name).suffix.lower() in CAD_SUFFIXES and not Path(name).name.startswith('~$')}
    if str(source) not in baseline:raise core.StopBatch('SOURCE_CHANGED','缺少原装配体基线。')
    changed=[];missing=[];unreadable=[]
    for name,before in baseline.items():
        try:
            p=core.no_links(name)
            if not p.is_file():missing.append({'path':name,'before_sha256':before,'after_sha256':None});continue
            after=core.digest(p)
            if before!=after:changed.append({'path':name,'before_sha256':before,'after_sha256':after})
        except (OSError,core.StopBatch) as error:
            unreadable.append({'path':name,'before_sha256':before,'after_sha256':None,'error':str(error)})
    # Additions cannot change an already frozen copy's dependency graph. A new
    # reference requires changed assembly bytes, which are checked above.
    added=[];scan_error=None
    try:
        recorded_workspace=set(task.get('source_workspace_files',task['source_hashes']))
        added=[{'path':p.relative_to(source.parent).as_posix(),'before_sha256':None,'after_sha256':None,
                'hash_status':'not_an_input_not_hashed'} for p in sorted(source.parent.rglob('*'))
               if p.is_file() and p.relative_to(source.parent).as_posix() not in recorded_workspace
               and str(p) not in baseline]
    except OSError as error:scan_error=type(error).__name__
    result={'unchanged':not (changed or missing or unreadable),'scope':task.get('source_hash_scope','recorded_CAD_inputs_legacy_compatible'),
            'input_count':len(baseline),'changed':changed,'missing':missing,'unreadable':unreadable,
            'added':added[:50],'added_count':len(added),'added_truncated':len(added)>50,
            'added_files_policy':'workspace_additions_are_not_new_inputs_and_do_not_block_cleanup',
            'workspace_scan_error':scan_error}
    core.write(Path(task['directory'])/'源文件核对.json',result)
    return result
