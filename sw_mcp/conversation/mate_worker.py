"""Owns one isolated CAD instance. JSON stdin commands; no automatic native write retries."""
from pathlib import Path
import argparse,hashlib,inspect,json,os,shutil,subprocess,sys,time,traceback,uuid
from . import core,sw_install,mate_motion,startup_gate
KIT=Path(__file__).resolve().parent

def stage(runtime):
    source=KIT.parents[1]
    paths=sorted((source/'executor').glob('*.cs'))+sorted((source/'sw_mcp').glob('*.py'))
    paths += [source/'scripts/lease_access.py']
    manifest={'build':'formal_source_snapshot','files':[{'path':p.relative_to(source).as_posix(),'sha256':core.digest(p)} for p in paths]}
    runtime.mkdir(parents=True,exist_ok=False)
    for row in manifest['files']:
        relative=Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:raise core.StopBatch('CANDIDATE_PATH_INVALID')
        p=core.no_links(source/relative)
        if core.digest(p)!=row['sha256']:raise core.StopBatch('CANDIDATE_SOURCE_MISMATCH',str(relative))
        dest=runtime/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    core.write(runtime/'candidate-provenance.json',manifest)

def compile_runtime(runtime,install,folder):
    redist=install/'api/redist';binpath=runtime/'executor/bin';binpath.mkdir(exist_ok=True)
    names=['SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll']
    for name in names:shutil.copyfile(redist/name,binpath/name)
    csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    common=[str(csc),'/nologo','/platform:x64','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll']+['/reference:'+str(redist/n) for n in names]
    sources=sorted((runtime/'executor').glob('*.cs'))
    # Keep the test/control helper outside production executor sources, with exact copied bytes.
    helper=runtime/'test_host/AcceptanceControl.cs';helper.parent.mkdir(exist_ok=True);shutil.copyfile(KIT/'session_control.cs',helper)
    core.write(folder/'control-helper-provenance.json',{'sha256':core.digest(helper),'source_sha256':core.digest(KIT/'session_control.cs'),'bytes_changed':False})
    for main,extra,target in [('Program',[],binpath/'SwExecutor.exe'),('AcceptanceControl',[helper],binpath/'AcceptanceControl.exe')]:
        run=subprocess.run(common+['/main:'+main,'/out:'+str(target)]+[str(p) for p in sources+extra],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        (folder/(main+'.compile.log')).write_bytes(run.stdout+run.stderr)
        if run.returncode:raise core.StopBatch('COMPILATION_FAILED','本机编译失败，诊断已保存。')
    core.write(folder/'compiled-sources.json',{p.name:core.digest(p) for p in sources})

class Session:
    def __init__(self,project,folder,runtime_base):
        self.project=project;self.folder=folder;self.runtime=runtime_base/uuid.uuid4().hex[:6]
        self.proc=None;self.bridge=None;self.model=None;self.checkpoint=None;self.recommendation=None;self.plan=None
        self.import_restored=False;self.motion=None;self.applied_plan=None;self.unknown=False;self.committed=False;self.ended=False;self.serial=0;self.cleanup_warning=None
        folder.mkdir(parents=True,exist_ok=False);self.state('ready','等待选择装配体。')
    def state(self,status,message,**kw):
        data={'status':status,'message':message,'runtime':str(self.runtime),'owned_pid':self.proc.pid if self.proc else None,
            'model_id':self.model,'checkpoint_id':self.checkpoint,'unknown':self.unknown,'committed':self.committed,'ended':self.ended,'cleanup_warning':self.cleanup_warning,'motion':self.motion,'recommendation_valid':self.recommendation is not None,'import_checkpoint_restored':self.import_restored,**kw}
        core.write(self.folder/'CAD会话状态.json',data)
        with (self.folder/'阶段.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'observed_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),**data},ensure_ascii=False)+'\n')
    def call(self,operation,**kw):
        if operation in {'apply_mate','create_motion_study'}:self.import_restored=False
        self.serial+=1;start=time.monotonic()
        try:
            value=self.bridge.request(operation,**kw)
            core.write(self.folder/'calls'/f'{self.serial:04d}-{operation}.json',{'operation':operation,'arguments':kw,'ok':True,'elapsed_s':time.monotonic()-start,'result':value})
            return value
        except Exception as e:
            self.unknown=bool(self.bridge.recovery_state().get('recovery_required'))
            core.write(self.folder/'calls'/f'{self.serial:04d}-{operation}.json',{'operation':operation,'arguments':kw,'ok':False,'code':getattr(e,'code',type(e).__name__),
                'message':str(e),'diagnostics':getattr(e,'diagnostics',None),'restoration_status':getattr(e,'restoration_status',None),'unknown':self.unknown})
            raise
    def discover(self,path,hint='',materialize=False):
        if self.bridge or self.proc:raise core.StopBatch('MATE_SESSION_ALREADY_STARTED','请先结束已有会话，不重复导入。')
        path=core.no_links(path)
        if not path.is_file() or path.suffix.lower()!='.sldasm':raise core.StopBatch('INVALID_ASSEMBLY_PATH')
        startup_gate.require_idle(self.folder)
        self.state('preparing','自动核对候选源码、定位 SolidWorks 并编译本机执行器…')
        core.runtime_path_budget(self.runtime);stage(self.runtime)
        install=Path(sw_install.resolve(self.project)['resolved_directory']);compile_runtime(self.runtime,install,self.folder)
        def retain(proc):self.proc=proc;self.state('starting','正在启动本次专用 SolidWorks 实例…')
        try:self.proc=core.launch(self.runtime,install,self.folder,on_started=retain)
        except Exception:self.unknown=self.proc is not None;raise
        from sw_mcp.bridge import Bridge
        self.bridge=Bridge(self.runtime)
        self.bridge._selected_startup_pid=str(self.proc.pid)
        self.state('importing','正在创建并核验隔离副本，原文件不写入…')
        imported=self.call('import_assembly',path=str(path),materialize_virtual_components=materialize)
        self.model=imported['model_id'];self.checkpoint=imported['checkpoint']['checkpoint_id'];core.write(self.folder/'导入.json',imported)
        return self.rescan(hint)
    def rescan(self,hint=''):
        if not self.model or self.unknown:raise core.StopBatch('MATE_STATE_NOT_READY')
        self.plan=None;self.recommendation=None;self.state('recommending','自动发现圆边、核对已有约束并推荐零件对…')
        from sw_mcp.circular_recommendations import discover
        value=discover(self.bridge,self.model,hint,5,budget_seconds=120,maximum_queries=128);self.recommendation=value;core.write(self.folder/'推荐.json',value)
        message=value['selection_question'] if value.get('setup_required') or not value.get('recommendations') else '推荐已准备好；核对零件对后可预演。'
        self.state('setup_required' if value.get('setup_required') else 'recommended',message,recommendation=value)
        return value
    def preview(self,index,translation=1,rotation=1):
        import math
        if self.unknown or self.committed or not self.recommendation:raise core.StopBatch('MATE_PREVIEW_NOT_READY')
        if self.motion and self.motion.get('stage')!='baseline_ready':raise core.StopBatch('MOTION_SESSION_FINISHED','本次运动对照已结束或未通过；结束会话并读取已有证据，不重用历史结论写入新配合。')
        if type(index) is not int or index<0 or index>=len(self.recommendation['recommendations']):raise core.StopBatch('INVALID_RECOMMENDATION_INDEX')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (translation,rotation)) or not 0<=translation<=10000 or not 0<=rotation<=180:raise core.StopBatch('INVALID_POSE_BUDGET')
        self.plan=None;item=self.recommendation['recommendations'][index]
        args={**item['preview_arguments'],'distance_mm':0,'baseline_run_id':self.motion['baseline']['run_id'] if self.motion and self.motion.get('stage')=='baseline_ready' else '','maximum_translation_mm':translation,'maximum_rotation_deg':rotation}
        if self.motion and self.motion.get('stage')=='baseline_ready' and {item['preview_arguments']['entity_a'],item['preview_arguments']['entity_b']}!=set(self.motion['pair_entities']):raise core.StopBatch('MOTION_BASELINE_PAIR_MISMATCH','基线只绑定已选圆边对，请先恢复后更换任务。')
        self.state('previewing','正在核对当前引用和已有配合；预演不会移动零件…')
        self.plan=self.call('preview_mate',**args);core.write(self.folder/'预演.json',self.plan)
        self.state('previewed','预演完成，请核对后明确确认写入。',plan=self.plan)
        return self.plan
    def apply(self,confirmed=False):
        if confirmed is not True:raise core.StopBatch('MATE_CONFIRMATION_REQUIRED')
        if self.unknown or self.committed or not self.plan:raise core.StopBatch('MATE_PLAN_NOT_READY')
        plan=self.plan;self.plan=None
        self.state('applying','正在验证检查点并创建配合；请勿重复点击或关闭 SolidWorks…')
        result=self.call('apply_mate',plan_id=plan['plan_id'],confirmed=True)
        self.applied_plan=plan['plan_id'];self.committed=True;core.write(self.folder/'配合成果.json',result)
        self.state('committed','配合已保存到隔离副本；尚未认证运动保留。可保留成果结束，或恢复本次修改。',applied=result)
        return result
    def restore(self):
        if self.unknown or not self.model:raise core.StopBatch('MATE_RECOVERY_REQUIRES_AI')
        self.import_restored=False;self.plan=None;self.state('restoring','正在恢复本次导入检查点…')
        value=self.call('restore_model_checkpoint',model_id=self.model,checkpoint_id=self.checkpoint)
        if not core.restored_ok(value):self.unknown=True;raise core.StopBatch('RESTORE_NOT_VERIFIED')
        self.import_restored=True;self.committed=False;self.applied_plan=None;self.recommendation=None
        if self.motion:self.motion['stage']='restored';core.write(self.folder/'运动对照.json',self.motion)
        core.write(self.folder/'恢复.json',value)
        self.state('restored','已恢复导入时状态；可结束本次会话。')
        return value
    def close(self):
        if self.unknown:raise core.StopBatch('NATIVE_STATE_UNKNOWN','保留现场交由AI核对，不结束实例。')
        if self.bridge:self.bridge.close();self.bridge=None
        if self.proc:
            self.state('closing','正在关闭本次专用CAD会话，保留已保存副本…')
            try:core.close_owned(None,self.proc,self.runtime,self.folder)
            except core.StopBatch as error:
                exit_file=self.folder/'exit.json'
                known_exit=core.read(exit_file) if exit_file.exists() else {}
                if error.code=='OWNED_CAD_EXIT_NONZERO' and known_exit.get('native_process_exited') is True:
                    self.cleanup_warning=known_exit
                    self.state('closing_warning','已确认专用进程结束，但退出码非零；单独保留清理警告。',cleanup_warning=known_exit)
                    core.write(self.folder/'清理警告.json',known_exit)
                else:self.unknown=True;raise
        self.ended=True;self.state('closed','本次CAD会话已结束；原装配与用户SolidWorks实例保留。')
        receipt={'ended':True,'committed_copy_preserved':self.committed,'import_checkpoint_restored':self.import_restored,
            'finish_mode':'restored_then_closed' if self.import_restored else 'kept_committed_copy' if self.committed else 'closed_without_verified_import_restore',
            'model_id':self.model,'checkpoint_id':self.checkpoint,'runtime':str(self.runtime),'cleanup_warning':self.cleanup_warning}
        core.write(self.folder/'会话收尾.json',receipt)
        return receipt
    def execute(self,action,data):
        if self.ended:raise core.StopBatch('MATE_SESSION_ENDED')
        if action=='discover':return self.discover(data['path'],data.get('hint',''),data.get('materialize') is True)
        if action=='motion_baseline':return mate_motion.baseline(self,data['index'],data.get('confirmed'),data.get('scope_confirmed',False))
        if action=='motion_verify':return mate_motion.verify(self,data.get('confirmed'))
        if action=='rescan':return self.rescan(data.get('hint',''))
        if action=='preview':return self.preview(data['index'],data.get('translation',1),data.get('rotation',1))
        if action=='apply':return self.apply(data.get('confirmed'))
        if action=='restore':return self.restore()
        if action=='restore_close':
            restored=self.restore() # Failure must preserve the live session, never continue into exit.
            result=self.close();result['restore']=restored
            return result
        if action=='close':
            if self.committed and data.get('keep_changes_confirmed') is not True:raise core.StopBatch('KEEP_CHANGES_CONFIRMATION_REQUIRED','请明确选择保留配合成果，或使用推荐的恢复并结束。')
            return self.close()
        raise core.StopBatch('UNKNOWN_MATE_ACTION')

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--runtime-base',type=Path,required=True);args=p.parse_args()
    session=Session(args.project,args.output,args.runtime_base)
    for line in sys.stdin:
        request=None
        try:
            request=json.loads(line);result=session.execute(request['action'],request.get('data',{}));reply={'id':request['id'],'ok':True,'result':result}
        except Exception as e:
            if session.bridge:session.unknown=bool(session.bridge.recovery_state().get('recovery_required')) or session.unknown
            error={'code':getattr(e,'code',type(e).__name__),'message':str(e),'diagnostics':getattr(e,'diagnostics',None),'unknown':session.unknown,'automatic_retry':False}
            if error['code']=='MATE_RECOMMENDATION_STALE':
                session.recommendation=None;session.plan=None
                core.write(args.output/'状态变化诊断.json',error.get('diagnostics'))
            core.write(args.output/'最近失败.json',{**error,'traceback':traceback.format_exc()});session.state('failed','当前步骤未完成，已保存诊断。',error=error)
            reply={'id':request.get('id') if request else None,'ok':False,'error':error}
        print(json.dumps(reply,ensure_ascii=False),flush=True)
        if session.ended:return
    # Lost browser/controller does not imply permission to discard/close native work.
    if session.proc and not session.ended:session.state('controller_ended','控制连接结束，保留CAD现场供AI处理。')
if __name__=='__main__':main()
