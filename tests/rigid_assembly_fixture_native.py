"""Explicit empty-owned-CAD fixture generation, with a no-CAD compile mode."""
import argparse,json,os,shutil,subprocess,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sw_mcp.conversation import core,sw_install,startup_gate
from sw_mcp.conversation.mate_worker import stage,compile_runtime

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--compile-only',action='store_true')
    parser.add_argument('--internal-lock',action='store_true',help='Generate one existing internal mate as a preservation control')
    args=parser.parse_args();folder=core.no_links(args.output);runtime=core.no_links(args.runtime)
    folder.mkdir(exist_ok=False,parents=True)
    result={'status':'running','compile_only':args.compile_only,'CAD_launched':False,'process_force_termination':False}
    try:
        if not args.compile_only:startup_gate.require_idle(folder)
        stage(runtime);install=Path(sw_install.resolve(ROOT)['resolved_directory']);compile_runtime(runtime,install,folder)
        source=runtime/'test_host/RigidAssemblyFixture.cs';shutil.copyfile(ROOT/'tests/RigidAssemblyFixture.cs',source)
        redist=install/'api/redist';binary=runtime/'executor/bin/RigidAssemblyFixture.exe'
        command=[str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/platform:x64',
            '/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll',
            '/main:RigidAssemblyFixtureControl','/out:'+str(binary)]
        command+=['/reference:'+str(redist/name) for name in ('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')]
        command+=[str(p) for p in sorted((runtime/'executor').glob('*.cs'))]+[str(source)]
        compiled=subprocess.run(command,capture_output=True);(folder/'fixture-compile.log').write_bytes(compiled.stdout+compiled.stderr)
        assert compiled.returncode==0,'Fixture compilation failed; no CAD launched'
        result.update(production_compiled=True,fixture_compiled=True,source_sha256=core.digest(source))
        if args.compile_only:
            result.update(status='pass',native_fixture_generated=False)
            return
        # Check again after compilation. A second product must never share the executor.
        startup_gate.require_idle(folder)
        retained={}
        def started(process):
            retained['process']=process;result.update(CAD_launched=True,owned_pid=process.pid)
            core.write(folder/'result.json',result)
        process=core.launch(runtime,install,folder,on_started=started)
        run=subprocess.run([str(binary),str(runtime),str(process.pid),str(folder/'fixture.json')]+(['internal-lock'] if args.internal_lock else []),
            env={**os.environ,'SW_MCP_PROCESS_ID':str(process.pid)},capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        (folder/'fixture.stdout').write_bytes(run.stdout);(folder/'fixture.stderr').write_bytes(run.stderr)
        assert run.returncode==0,'Native fixture generation failed; preserve owned instance for review'
        truth=core.read(folder/'fixture.json')
        assert truth['components']==4 and truth['native_rigid_solving']==0 and truth['initial_root_mates']==0
        assert truth['initial_internal_mates']==int(args.internal_lock)
        result.update(fixture=truth,helper_exit_code=run.returncode)
        result['cleanup']=core.close_owned(None,process,runtime,folder)
        result['native_exit']=core.read(folder/'exit.json')
        assert result['native_exit']['exit_code']==0 and not result['native_exit']['force_kill']
        result.update(status='pass',native_fixture_generated=True)
    except Exception as error:
        result.update(status='failed',error=str(error),traceback=traceback.format_exc(),
            instruction='No automatic write retry or force termination; preserve any owned native process and evidence.')
        raise
    finally:
        core.write(folder/'result.json',result)
        print(json.dumps({k:result.get(k) for k in ('status','compile_only','CAD_launched','native_fixture_generated','owned_pid')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
