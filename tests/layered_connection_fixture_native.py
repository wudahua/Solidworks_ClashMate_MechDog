"""Wrap only a new isolated import; never edit the supplied assembly source."""
import argparse,json,os,pathlib,shutil,subprocess,sys,traceback
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sw_mcp.conversation import core,sw_install
from sw_mcp.conversation.motion_tasks import MotionSession
from sw_mcp.conversation.task_engine import release_executor

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=pathlib.Path,required=True)
    parser.add_argument('--output',type=pathlib.Path,required=True);parser.add_argument('--runtime',type=pathlib.Path,required=True)
    parser.add_argument('--remove-native-feature-id',type=int,default=0)
    parser.add_argument('--label',required=True);parser.add_argument('--copies',type=int,choices=(1,2),default=1)
    args=parser.parse_args();out=core.no_links(args.output);out.mkdir(parents=True,exist_ok=False)
    before=core.fixture_hashes(args.source);s=MotionSession(ROOT,out/'session',args.runtime);s.task_kind='assembly_constraints'
    result={'status':'running','developer_fixture':True,'source_files_unchanged':None,'force_termination':False}
    try:
        if args.remove_native_feature_id:os.environ['SW_MCP_FAULT_TESTS']='1'
        s.discover(args.source)
        if args.remove_native_feature_id:
            mates=s.connection_survey['mates'];feature=next(m for m in mates if m['native_feature_id']==args.remove_native_feature_id)
            assert len(mates)==13 and feature['type']==5,'Controlled single-missing fixture requires the declared 13-mate crank input'
            deleted=s.call('_test_connection_deletion',model_id=s.model,native_feature_id=args.remove_native_feature_id)
            assert deleted['remaining_mate_count']==12 and deleted['source_files_unchanged']
            core.write(out/'controlled-single-missing.json',deleted);result['controlled_single_missing']=deleted
        release_executor(s.bridge,s.folder);s.bridge=None
        runtime=s.runtime;redist=pathlib.Path(sw_install.resolve(ROOT)['resolved_directory'])/'api/redist'
        names=('LayeredConnectionFixture.cs','RigidAssemblyFixture.cs');sources=[]
        for name in names:
            p=runtime/'test_host'/name;shutil.copyfile(ROOT/'tests'/name,p);sources.append(p)
        binary=runtime/'executor/bin/LayeredConnectionFixture.exe'
        command=[str(pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/platform:x64',
            '/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll',
            '/main:LayeredConnectionFixtureControl','/out:'+str(binary)]
        command+=['/reference:'+str(redist/n) for n in ('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')]
        command+=[str(p) for p in sorted((runtime/'executor').glob('*.cs'))]+[str(p) for p in sources]
        compiled=subprocess.run(command,capture_output=True);(out/'fixture.compile.log').write_bytes(compiled.stdout+compiled.stderr);assert compiled.returncode==0
        with (out/'fixture.stdout').open('wb') as stdout,(out/'fixture.stderr').open('wb') as stderr:
            helper=subprocess.Popen([str(binary),str(runtime),str(s.proc.pid),str(out/'fixture.json'),s.model,args.label,str(args.copies)],
                env={**os.environ,'SW_MCP_PROCESS_ID':str(s.proc.pid),'SW_MCP_FAULT_TESTS':'1'},stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            core.write(out/'fixture-helper.json',{'pid':helper.pid,'owned_CAD_pid':s.proc.pid,'force_termination':False})
            code=helper.wait()
        assert code==0,'Fixture helper failed; preserve native state without retries'
        truth=core.read(out/'fixture.json');assert truth['original_sources_unchanged']
        result.update(fixture=truth,fixture_helper_exit=code,geometry_saved_and_assertions_passed=True)
        # No model operation is dispatched after the fixture writer. Only empty
        # owned-CAD cleanup follows, with the same retained process handle.
        try:result['cleanup']=core.close_owned(None,s.proc,runtime,out)
        except core.StopBatch as error:
            if error.code!='OWNED_CAD_EXIT_NONZERO':raise
            result['producer_exit_warning']=error.code
        result['native_exit']=core.read(out/'exit.json');assert result['native_exit']['native_process_exited'] and not result['native_exit']['force_kill']
        assert core.fixture_hashes(args.source)==before
        result.update(status='generated_input_requires_fresh_formal_validation',source_files_unchanged=True,
            producer_lifecycle_passed=result['native_exit']['exit_code']==0,
            fixture_file_hashes=core.fixture_hashes(pathlib.Path(truth['assembly'])))
    except Exception as error:
        result.update(status='failed',code=getattr(error,'code',type(error).__name__),error=str(error),traceback=traceback.format_exc());raise
    finally:core.write(out/'result.json',result)
    print(json.dumps({k:result[k] for k in ('status','source_files_unchanged','producer_lifecycle_passed')},ensure_ascii=False))

if __name__=='__main__':main()
