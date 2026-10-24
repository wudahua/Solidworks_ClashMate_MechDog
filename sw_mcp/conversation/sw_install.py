"""Resolve an installed CAD directory by filesystem/registry observations, never COM."""
import importlib.util
import os
from pathlib import Path
from . import core

DLLS=('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')

def check_directory(path):
    path=core.no_links(path)
    required=[path/'SLDWORKS.exe',*[path/'api/redist'/name for name in DLLS]]
    missing=[str(p) for p in required if not core.no_links(p).is_file()]
    return path,missing

def installed_candidates(project):
    # The caller verifies every published source byte before this import.
    spec=importlib.util.spec_from_file_location('newuser_verified_install_preflight',project/'scripts/install_preflight.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.installed_solidworks_candidates()

def resolve(project,explicit=None,*,environ=None,detector=None,default=None):
    project=core.no_links(project);env=os.environ if environ is None else environ
    report={'schema_version':1,'CAD_called':False,'candidates':[],'record_issues':[],
            'precedence':['explicit_cli','SW_INSTALL_DIR','installed_build_record','installed_inventory','default_directory']}
    def accept(path,source,strict=False):
        path,missing=check_directory(path)
        report['candidates'].append({'source':source,'directory':str(path),'missing':missing})
        if missing:
            if strict:fail('SW_INSTALL_PREREQUISITES_MISSING','指定的安装目录缺少 SLDWORKS.exe 或 Motion Interop；不会静默回退。')
            return None
        report.update(status='resolved',selected_source=source,resolved_directory=str(path),missing=[])
        return report
    def fail(code,message):
        report.update(status='refused',next_action={'code':'specify_sw_install','argument':'--sw-install / -SwInstall',
            'message':'指定实际包含 SLDWORKS.exe 和 api/redist 三个 Interop 的安装目录；没有启动 CAD。'})
        raise core.StopBatch(code,message,report)
    if explicit is not None:return accept(explicit,'explicit_cli',True)
    if env.get('SW_INSTALL_DIR'):return accept(env['SW_INSTALL_DIR'],'SW_INSTALL_DIR',True)
    record=core.no_links(project/'executor/bin/build-manifest.json')
    if record.is_file():
        try:
            saved=core.read(record)
            if not isinstance(saved,dict):raise ValueError('build manifest must be an object')
            value=saved.get('solidworks_install_dir')
            if not isinstance(value,str) or not value.strip():raise ValueError('missing solidworks_install_dir')
            result=accept(value,'installed_build_record')
            if result:return result
        except (ValueError,KeyError,OSError) as error:
            report['record_issues'].append({'path':str(record),'reason':str(error)})
    raw=(detector or installed_candidates)(project)
    valid={}
    for value in raw:
        if not isinstance(value,str) or not value.strip():continue
        path,missing=check_directory(value)
        report['candidates'].append({'source':'installed_inventory','directory':str(path),'missing':missing})
        if not missing:valid[str(path).casefold()]=path
    if len(valid)>1:fail('SW_INSTALL_AMBIGUOUS','检测到多个可用安装目录，请明确指定 --sw-install。')
    if valid:return accept(next(iter(valid.values())),'installed_inventory')
    result=accept(default or Path(r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'),'default_directory')
    if result:return result
    fail('SW_INSTALL_NOT_FOUND','未找到包含 Motion Interop 的可用 SolidWorks 安装目录。')
