"""Matched owned-instance 4s/30fps run/verify comparison. Never attaches to user CAD.

Use --executor-source to compile an archived release for the baseline. Each run
imports the same saved source to a fresh private copy. Timing is evidence for
this machine/session only, not a cross-machine speed guarantee.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from v042a4_performance_native import matrix

ROOT = Path(__file__).resolve().parents[1]
PROBE_CS = matrix.CS[:matrix.CS.index('class ProbeAcceptance')] + r'''
class ProbeAcceptance {
 static Dictionary<string,object> D(object x){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(x));}
 [STAThread]static int Main(string[] a){if(a.Length==2&&a[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(a[1]);Cad cad=null;int pid=int.Parse(a[2]);var r=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(a[0],"native.json"),Cad.Json.Serialize(r));using(var gate=new Mutex(false,@"Local\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{
 cad=new Cad(a[0]);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");var imported=D(cad.ImportUserAssembly(a[1],""));r["import"]=imported;string id=(string)imported["model_id"];var states=Cad.Json.Deserialize<Cad.StudyState[]>(Cad.Json.Serialize(cad.ProbeTestStates(id)));var study=states.Single(s=>s.name=="MatchedPerformance");if(study.duration_s!=4||study.fps!=30||states.Any(s=>Math.Abs(s.time_s)>1e-8))throw new Exception("USE_VERIFIED_PERFORMANCE_COPY_AT_ZERO");var cp=D(cad.CreateUserCheckpoint(id));r["checkpoint"]=cp;save();var probe=D(cad.ProbeUserCompatibility(id,study.name,4,30,Guid.NewGuid().ToString("N"),(string)cp["checkpoint_id"]));r["probe"]=probe;save();if((string)probe["solver_compatibility_status"]!="pass")throw new Exception("MATCHED_COMPATIBILITY_PROBE_NOT_PASS");var worker=D(probe["worker"]);if(Convert.ToInt32(worker["worker_exit_code"])!=0||(string)worker["native_exit_code_process"]!="owned_SOLIDWORKS_not_managed_worker"||!(bool)worker["cleanup_verified"]||!File.Exists((string)worker["worker_host_observation_path"]))throw new Exception("WORKER_EXIT_CONTRACT_NOT_VISIBLE");r["completed"]=true;save();return 0;
 }catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--executor-source', default=str(ROOT / 'executor'))
    parser.add_argument('--scenario', choices=('performance', 'compatibility'), default='performance')
    args = parser.parse_args()
    source = Path(args.source).resolve(); executor = Path(args.executor_source).resolve()
    if not source.is_file() or source.suffix.lower() != '.sldasm' or not (executor / 'UserMotion.cs').is_file():
        raise ValueError('Specify saved assembly and validated executor source directory')
    folder = ROOT / 'runs/performance-a7' / uuid.uuid4().hex[:8]; folder.mkdir(parents=True)
    (folder / 'test.cs').write_text(matrix.CS if args.scenario == 'performance' else PROBE_CS, encoding='utf-8', newline='\n')
    redist = Path(os.environ.get('SW_INSTALL_DIR', r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS')) / 'api/redist'
    dlls = ('SolidWorks.Interop.sldworks.dll', 'SolidWorks.Interop.swconst.dll', 'SolidWorks.Interop.swmotionstudy.dll')
    for name in dlls: (folder / name).write_bytes((redist / name).read_bytes())
    exe = folder / 'ProbeAcceptance.exe'
    command = [str(Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'), '/nologo', '/platform:x64', '/main:ProbeAcceptance', '/reference:System.Web.Extensions.dll', '/reference:System.Windows.Forms.dll', '/reference:Microsoft.CSharp.dll', '/out:' + str(exe)]
    command += ['/reference:' + str(redist / name) for name in dlls]
    command += [str(p) for p in executor.glob('*.cs')] + [str(folder / 'test.cs')]
    subprocess.run(command, check=True)
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.parent.iterdir() if p.is_file()}
    journal = ROOT / 'runs/executor-state.json'; journal_hash = hashlib.sha256(journal.read_bytes()).hexdigest()
    report = {'completed': False, 'directory': str(folder), 'executor_source': str(executor), 'source_hashes': hashes, 'executor_source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in executor.glob('*.cs')}, 'primary_journal_sha256': journal_hash}
    def save(): (folder / 'session.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
    owned = subprocess.Popen([str(redist.parents[1] / 'SLDWORKS.exe')], startupinfo=startup, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report['owned_pid'] = owned.pid; save(); print('OWNED_INSTANCE', owned.pid, str(folder), flush=True)
    env = {**os.environ, 'SW_MCP_PROCESS_ID': str(owned.pid), 'SW_MCP_FAULT_TESTS': '1'}
    deadline = time.monotonic() + 180
    while True:
        if owned.poll() is not None: raise RuntimeError('Owned application exited before connection')
        result = subprocess.run([str(ROOT / 'executor/bin/SwExecutor.exe'), 'check-connection'], env=env, capture_output=True, timeout=25)
        hello = json.loads(result.stdout); report['connection'] = hello; save()
        if hello.get('ready'):
            assert hello['process_id'] == owned.pid
            break
        if time.monotonic() > deadline: raise TimeoutError('COM startup pending; preserved owned process evidence')
        time.sleep(2)
    with (folder / 'stdout.log').open('wb') as out, (folder / 'stderr.log').open('wb') as err:
        helper = subprocess.Popen([str(exe), str(folder), str(source), str(owned.pid)], env=env, stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        report['helper_pid'] = helper.pid; save()
        helper.wait(timeout=900)
    report.update(helper_exit=helper.returncode, source_files_unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items()), primary_journal_unchanged=hashlib.sha256(journal.read_bytes()).hexdigest() == journal_hash)
    try:
        owned.wait(timeout=45); report['owned_exit_code'] = owned.returncode
    except subprocess.TimeoutExpired:
        report['owned_exit_pending'] = True
    report['completed'] = helper.returncode == 0 and owned.poll() is not None and report['source_files_unchanged'] and report['primary_journal_unchanged']
    save()
    print(json.dumps({k: v for k, v in report.items() if k not in ('source_hashes', 'executor_source_hashes', 'connection')}, ensure_ascii=True), flush=True)
    if not report['completed']: raise SystemExit(1)
    return report


if __name__ == '__main__': main()
