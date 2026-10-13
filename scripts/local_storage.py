"""Inspect local artifacts; explicit cleanup of eligible old run directories only.

Checkpoints, state snapshots, latest study runs, active jobs and recovery evidence
are retained. A run can only be deleted by naming it twice on the CLI.
"""
import argparse,json,math,os,re,shutil,stat,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def reparse(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))

def inventory(root,minimum_age_days=7):
    if not math.isfinite(minimum_age_days) or minimum_age_days<0:raise ValueError('保留天数须为有限非负数。')
    root=root.resolve();runs=root/'runs';errors=[];buckets={};referenced=set();guard='idle'
    def read(path):
        if path.stat().st_size>2_000_000:raise ValueError('metadata too large')
        return json.loads(path.read_text(encoding='utf-8-sig'))
    journal=runs/'executor-state.json'
    if journal.exists():
        try:guard=read(journal).get('status','unknown')
        except (OSError,ValueError):guard='unknown'
    if runs.exists():
        for current,dirs,files in os.walk(runs,followlinks=False,onerror=lambda e:errors.append(str(e))):
            base=Path(current);dirs[:]=[d for d in dirs if not reparse(base/d)]
            for name in files:
                path=base/name
                try:
                    if reparse(path):errors.append('reparse skipped: '+str(path));continue
                    rel=path.relative_to(runs);key=rel.parts[0];buckets[key]=buckets.get(key,0)+path.stat().st_size
                    if path.suffix=='.json' and rel.parts[0] in {'study-history','jobs'}:
                        data=read(path)
                        if rel.parts[0]=='study-history':referenced.add(data.get('run_id'))
                        elif data.get('status') in {'queued','running','timed_out','executor_lost'}:referenced.add(data.get('params',{}).get('run_id'))
                except (OSError,ValueError):errors.append('unreadable metadata: '+str(path))
    entries=[]
    for key,size in sorted(buckets.items()):
        if not re.fullmatch(r'[a-f0-9]{32}',key):continue
        folder=runs/key;reasons=[]
        try:
            data=read(folder/'solve.json')
            if data.get('run_id')!=key or data.get('restoration_status') not in {'restored','not_required'}:reasons.append('restore_or_identity_unverified')
            if data.get('finished_at') is None:reasons.append('not_terminal')
            if data.get('solver_status') not in {'completed','failed','incomplete','not_started'} or data.get('sampling_status') not in {'completed','not_completed'}:reasons.append('operation_status_not_terminal')
        except (OSError,ValueError):reasons.append('manifest_unavailable')
        if key in referenced:reasons.append('latest_study_run_or_active_job')
        if guard!='idle':reasons.append('recovery_not_idle')
        if errors:reasons.append('inventory_incomplete')
        age=(time.time()-folder.stat().st_mtime)/86400
        if age<minimum_age_days:reasons.append('within_retention_period')
        entries.append({'run_id':key,'bytes':size,'age_days':age,'eligible_for_explicit_cleanup':not reasons,'protected_reasons':reasons})
    return {'root':str(root),'scan_complete':not errors,'scan_errors':errors[:20],'scan_error_count':len(errors),'recovery_status':guard,'runs_total_observed_bytes':sum(buckets.values()),'buckets':buckets,'minimum_age_days':minimum_age_days,'run_candidates':entries,'checkpoints_and_state_snapshots':'always_retained_by_this_command','deletion_performed':False}

def delete_run(root,run_id,confirm,minimum_age_days=7):
    if not re.fullmatch(r'[a-f0-9]{32}',run_id or '') or confirm!=run_id:raise ValueError('必须用 --delete-run ID --confirm ID 明确指定同一任务。')
    root=root.resolve();target=(root/'runs'/run_id)
    target.resolve().relative_to((root/'runs').resolve())
    if reparse(root/'runs') or reparse(target):raise ValueError('不删除重解析路径。')
    sys.path.insert(0,str(ROOT))
    from sw_mcp.bridge import Bridge
    bridge=Bridge(root)
    try:
        bridge._acquire_lease()
        report=inventory(root,minimum_age_days)
        match=next((r for r in report['run_candidates'] if r['run_id']==run_id),None)
        if not match or not match['eligible_for_explicit_cleanup']:raise ValueError('任务受保护或清单不完整，拒绝清理。')
        for current,dirs,files in os.walk(target,followlinks=False):
            if any(reparse(Path(current)/p) for p in dirs+files):raise ValueError('任务包含重解析点，拒绝递归清理。')
        # Resolve the exact recursive target again immediately before deleting it.
        target.resolve().relative_to((root/'runs').resolve());shutil.rmtree(target)
    finally:bridge.close()
    return {'deleted_run_id':run_id,'deletion_performed':True,'checkpoint_files_deleted':False}

def main():
    parser=argparse.ArgumentParser(description='本地工件清单；默认不删除任何数据。')
    parser.add_argument('--minimum-age-days',type=float,default=7)
    parser.add_argument('--delete-run');parser.add_argument('--confirm');parser.add_argument('--output')
    args=parser.parse_args()
    if not math.isfinite(args.minimum_age_days) or args.minimum_age_days<0:parser.error('保留天数须为有限非负数。')
    report=delete_run(ROOT,args.delete_run,args.confirm,args.minimum_age_days) if args.delete_run else inventory(ROOT,args.minimum_age_days)
    if args.output:
        target=Path(args.output).resolve();target.relative_to(ROOT.resolve())
        if target.exists() and reparse(target):raise ValueError('输出路径不能是重解析点。')
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'deletion_performed':report['deletion_performed'],'scan_complete':report.get('scan_complete'),'output':args.output},ensure_ascii=False))
if __name__=='__main__':main()
