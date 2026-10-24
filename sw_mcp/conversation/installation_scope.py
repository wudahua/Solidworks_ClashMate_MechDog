"""Recovery snapshots are data, never independent MCP/owner installations."""
from pathlib import Path

SNAPSHOT_MARKER='.clashmate-recovery-snapshot.json'


def require_live_installation(*paths):
    from . import core
    for value in paths:
        path=core.no_links(Path(value))
        if any(p.casefold()=='upgrade-backups' for p in path.parts) or any((p/SNAPSHOT_MARKER).is_file() for p in (path,*path.parents)):
            raise core.StopBatch('HOST_BACKUP_TREE_REFUSED',
                '升级备份是恢复数据，不能注册或启动MCP宿主。AI使用原正式安装目录；对比旧版本请使用可信官方包的独立安装，不运行备份树。',
                {'refused_path':str(path),'launch_attempted':False,'CAD_dispatched':False})
    return True
