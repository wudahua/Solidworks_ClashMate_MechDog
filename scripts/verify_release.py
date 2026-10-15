"""Validate declared public source bytes and version; no CAD, network or writes."""
import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


class ReleaseSourceMismatch(ValueError):
    """Exact bytes still fail; line-ending equivalence is diagnostic only."""
    def __init__(self, mismatches):
        self.mismatches = mismatches
        self.code = ('LINE_ENDING_MISMATCH' if all(m['code'] == 'LINE_ENDING_MISMATCH' for m in mismatches)
                     else 'RELEASE_SOURCE_MISMATCH')
        paths = ', '.join(m['path'] for m in mismatches[:8])
        ending = any(m['code'] == 'LINE_ENDING_MISMATCH' for m in mismatches)
        hint = (' CRLF/LF conversion matches the manifest for the indicated files, but exact-byte verification still failed. '
                'Changing .gitattributes alone may leave existing working files unchanged. '
                'Back up local edits, then use the trusted official ZIP and its SHA256 sidecar with upgrade.ps1; '
                'it restores exact source bytes and rebuilds the executor. Do not reset/delete local files blindly.' if ending else '')
        super().__init__('Release source mismatch [' + self.code + ']: ' + paths + hint)


def source_mismatch(name, data, record):
    actual = hashlib.sha256(data).hexdigest()
    if len(data) == record['bytes'] and actual == record['sha256']:
        return None
    code = 'RELEASE_SOURCE_MISMATCH'
    conversion = None
    try:
        data.decode('utf-8')  # No encoding/BOM/whitespace normalization.
        lf = data.replace(b'\r\n', b'\n')
        for label, candidate in (('CRLF_to_LF', lf), ('LF_to_CRLF', lf.replace(b'\n', b'\r\n'))):
            if len(candidate) == record['bytes'] and hashlib.sha256(candidate).hexdigest() == record['sha256']:
                code, conversion = 'LINE_ENDING_MISMATCH', label
                break
    except UnicodeDecodeError:
        pass
    return {'path': name, 'code': code, 'expected_bytes': record['bytes'], 'actual_bytes': len(data),
            'expected_sha256': record['sha256'], 'actual_sha256': actual,
            'diagnostic_conversion': conversion, 'exact_bytes_verified': False}

def safe_relative(value):
    if not isinstance(value,str) or '\\' in value or ':' in value:raise ValueError('Invalid manifest path')
    path=PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(p in ('','.', '..') for p in value.split('/')):raise ValueError('Unsafe manifest path')
    if path.parts[0] in {'runs','experiments','.venv','.git','upgrade-backups'}:raise ValueError('Runtime data must not be a release source')
    return path

def reject_links(path,root):
    current=Path(path)
    while True:
        if current.is_symlink() or (hasattr(current,'is_junction') and current.is_junction()):raise ValueError('Linked release path refused: '+str(current))
        if current==root:break
        if root not in current.parents:raise ValueError('Source outside release root')
        current=current.parent

def validate_manifest(manifest,read):
    if not isinstance(manifest,dict) or not isinstance(manifest.get('files'),list):raise ValueError('Invalid release manifest')
    if any(manifest.get(k,False) is not False for k in ('includes_user_cad','includes_runtime_data','includes_solidworks_binaries')):raise ValueError('Release includes unsupported private/runtime content')
    names=set();folded=set();mismatches=[]
    for record in manifest['files']:
        name=safe_relative(record['path']).as_posix()
        path=PurePosixPath(name)
        root_files={'README.md','LICENSE','.gitignore','.gitattributes','.editorconfig','requirements.txt','requirements.lock.txt','motion_server.py','server.py','mcp-config.example.json','install.ps1','start.ps1','upgrade.ps1','初始化环境.ps1','启动MCP.ps1','生成运动示例.ps1'}
        allowed=(len(path.parts)==1 and (name in root_files or re.fullmatch(r'发布说明_v[0-9A-Za-z.\-]+\.md',name))) or (path.parts[0] in {'executor','sw_mcp','scripts','tests'} and len(path.parts)==2 and path.suffix in {'.cs','.py','.ps1'}) or (path.parts[:2]==('.github','workflows') and len(path.parts)==3 and path.suffix in {'.yml','.yaml'})
        if not allowed:raise ValueError('Non-public or runtime release path: '+name)
        if name=='发布清单.json' or name in names or name.casefold() in folded:raise ValueError('Duplicate or self-referential manifest entry')
        names.add(name);folded.add(name.casefold());data=read(name)
        mismatch=source_mismatch(name,data,record)
        if mismatch:mismatches.append(mismatch)
    if mismatches:raise ReleaseSourceMismatch(mismatches)
    for name in ('motion_server.py','executor/UserMotion.cs','scripts/build_release.py'):
        text=read(name).decode('utf-8-sig');pattern=r'VERSION\s*=\s*"([^"]+)"' if name.endswith('build_release.py') else r'version="([^"]+)"'
        match=re.search(pattern,text)
        if not match or match.group(1)!=manifest['version']:raise ValueError('Release version mismatch: '+name)
    return names

def verify(root):
    root=Path(root).absolute();reject_links(root,root)
    def read(name):
        path=root/safe_relative(name);reject_links(path,root);return path.read_bytes()
    manifest=json.loads(read('发布清单.json').decode('utf-8-sig'));listed=validate_manifest(manifest,read)
    production={p.relative_to(root).as_posix() for directory in ('executor','sw_mcp','scripts','tests') for p in (root/directory).rglob('*') if p.is_file() and p.suffix in ('.cs','.py','.ps1')}
    production={n for n in production if not any(p in ('bin','__pycache__') for p in PurePosixPath(n).parts)}
    if production-listed:raise ValueError('Unlisted public source files: '+','.join(sorted(production-listed)))
    return {'all_passed':True,'version':manifest['version'],'source_files':len(listed),'coverage':'declared_public_sources_excludes_manifest_self_and_runtime_data'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));args=parser.parse_args()
    try:result=verify(args.root)
    except ReleaseSourceMismatch as error:
        print(json.dumps({'all_passed':False,'code':error.code,'message':str(error),'mismatch_count':len(error.mismatches),'mismatches':error.mismatches},ensure_ascii=False,indent=2));return 1
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps({'all_passed':False,'code':'RELEASE_VALIDATION_FAILED','message':str(error)},ensure_ascii=False,indent=2));return 1
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
