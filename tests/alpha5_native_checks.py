"""Owned SolidWorks instance and generated examples only; preserve source and main journal."""
import argparse,hashlib,json,os,subprocess,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=r'''using System;using System.IO;using System.Linq;using System.Threading;using System.Collections.Generic;using SolidWorks.Interop.sldworks;
public partial class Cad {
 public void Alpha5CloseFiles(string id){CloseUserDocuments(GetUserModel(id).Files);}
 public object Alpha5CloseOwned(int pid){if(Sw.GetProcessID()!=pid)throw new Exception("OWNED_PID_MISMATCH");var docs=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().ToArray();if(docs.Any(d=>!d.GetPathName().StartsWith(Root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)))throw new Exception("NON_OWNED_DOCUMENT_REFUSE_EXIT");CloseUserDocuments(docs.Select(d=>d.GetPathName()).ToArray());if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_DOCUMENTS_STILL_OPEN");Sw.ExitApp();return new{exit_requested=true,owned_pid=pid};}
}
class Alpha5Native {
 static Dictionary<string,object> D(object x){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(x));}
 static List<Dictionary<string,object>> Rows(object x){return Cad.Json.Deserialize<List<Dictionary<string,object>>>(Cad.Json.Serialize(x));}
 static Dictionary<string,object>[] References(object inspect){return Rows(D(inspect)["mates"]).SelectMany(m=>Rows(m["entities"])).Where(e=>e.ContainsKey("geometry")).Select(e=>{var g=D(e["geometry"]);g["registration"]=e["entity_registration_status"];return g;}).ToArray();}
 static void Require(bool value,string name){if(!value)throw new Exception(name);}
 [STAThread] static int Main(string[] args){string root=Path.GetFullPath(args[0]);int pid=int.Parse(args[1]);if(!root.Contains("mechanism-feedback-audit"+Path.DirectorySeparatorChar))return 3;Cad cad=null;var report=new Dictionary<string,object>{{"completed",false},{"steps",new List<object>()}};string output=Path.Combine(root,"alpha5-native.json");
  Action<string,object> record=(n,d)=>{((List<object>)report["steps"]).Add(new{name=n,data=d});File.WriteAllText(output,Cad.Json.Serialize(report));Cad.Log("ALPHA5_STEP "+n);};
  using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{
   cad=new Cad(root);Require(cad.Sw.GetProcessID()==pid,"OWNED_PID_MISMATCH");record("environment",cad.UserEnvironment());
   var imported=D(cad.ImportUserAssembly(Path.Combine(args[2],"rotary.SLDASM"),""));string id=(string)imported["model_id"],initial=(string)D(imported["checkpoint"])["checkpoint_id"];record("import",imported);
   var inspected=cad.InspectUserModel(id);record("automatic_registration",inspected);var refs=References(inspected);Require(refs.Length>0&&refs.All(r=>(string)r["registration"]=="registered_supported_inspected_face"),"INSPECTED_REFERENCES_NOT_REGISTERED");
   var drive=refs.First(r=>(string)r["kind"]=="cylindrical_axis"&&!(bool)r["fixed_component"]);string component=(string)drive["component_id"],entity=(string)drive["entity_id"];
   record("drive_from_inspection_without_requery",cad.CreateUserStudy(id,"Alpha5",component,entity,"rotary",30,false,"",4,30));
   string verifyRun=Guid.NewGuid().ToString("N");var verified=D(cad.VerifyRequestedMotion(id,"Alpha5",component,entity,"rotary",720,4,30,verifyRun,""));record("theoretical_720_verification",verified);Require((string)verified["assertion"]=="pass","THEORETICAL_TRAVEL_FAILED");
   cad.CreateUserCheckpoint(id);cad.Alpha5CloseFiles(id);
   var probe=D(cad.ProbeUserCompatibility(id,"Alpha5",1,30,Guid.NewGuid().ToString("N")));record("independent_compatibility_probe",probe);Require((string)probe["solver_compatibility_status"]=="pass"&&(bool)probe["original_copy_unchanged"],"PROBE_FAILED_OR_ORIGINAL_CHANGED");
   var afterProbe=D(cad.PreflightUserMotion(id,"Alpha5"));record("basic_preflight_is_not_compatibility_greenlight",afterProbe);Require((string)afterProbe["solver_compatibility_status"]=="not_checked"&&(bool)afterProbe["ready_is_legacy_basic_input_alias"],"BASIC_SCOPE_MISSING");
   refs=Rows(D(cad.ListMateReferences(id,"","planar_normal",50,null))["entities"]).ToArray();var fixedPlane=refs.First(r=>(string)r["kind"]=="planar_normal"&&(bool)r["fixed_component"]);var movingPlane=refs.First(r=>(string)r["kind"]=="planar_normal"&&!(bool)r["fixed_component"]);
   var plan=D(cad.PreviewBasicMate(id,(string)fixedPlane["entity_id"],(string)movingPlane["entity_id"],"distance","aligned",5,false,""));
   try{cad.ApplyBasicMate((string)plan["plan_id"],true);throw new Exception("CONFLICT_UNEXPECTEDLY_COMMITTED");}catch(CadFault error){Require(error.Code=="MATE_APPLY_ROLLED_BACK","FAILED_MATE_NOT_ROLLED_BACK");var details=D(error.Diagnostics);Require((bool)details["rollback_verified"]&&details.ContainsKey("existing_mate_preflight"),"ROLLBACK_CONTEXT_MISSING");record("failure_preserves_preview_context",new{code=error.Code,details=details});}
   record("restore_initial",cad.RestoreUserCheckpoint(id,initial));
   try{cad.PreviewBasicMate(id,(string)fixedPlane["entity_id"],(string)movingPlane["entity_id"],"distance","aligned",5,false,"");throw new Exception("RESTORE_REMOVED_REFERENCE_NOT_REJECTED");}catch(CadFault error){Require(error.Code=="MATE_REFERENCE_NOT_REGISTERED","REMOVED_REFERENCE_ERROR_INVALID");var query=D(D(error.Diagnostics)["required_query"]);Require(query["component_id"]!=null&&query["kind"]!=null,"ENTITY_QUERY_METADATA_MISSING");record("restore_removed_reference_has_exact_query",error.Diagnostics);}
   record("reregister_after_restore",cad.InspectUserModel(id));record("source_unchanged",D(cad.InspectUserModel(id))["source_files_unchanged"]);
   report["completed"]=true;record("cleanup",cad.Alpha5CloseOwned(pid));cad=null;File.WriteAllText(output,Cad.Json.Serialize(report));return 0;
  }catch(Exception error){report["failure"]=error.ToString();report["failure_details"]=error is CadFault?((CadFault)error).Diagnostics:null;File.WriteAllText(output,Cad.Json.Serialize(report));return 1;}
  finally{if(cad!=null)try{record("failure_cleanup",cad.Alpha5CloseOwned(pid));}catch(Exception error){report["cleanup_failure"]=error.ToString();File.WriteAllText(output,Cad.Json.Serialize(report));}gate.ReleaseMutex();}}
 }
}'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);args=parser.parse_args();source=Path(args.source).resolve()
    if not (source/'examples.json').is_file() or not (source/'rotary.SLDASM').is_file():raise ValueError('Use the program-generated example directory with examples.json')
    inventory=json.loads(subprocess.check_output(['powershell.exe','-NoProfile','-Command',"ConvertTo-Json -InputObject @(Get-Process SwExecutor,Alpha5Native -ErrorAction SilentlyContinue | Select-Object Id,ProcessName) -Compress"],text=True))
    if inventory:raise RuntimeError('Another executor is running; stop its client service first. No process was stopped.')
    folder=ROOT/'runs/mechanism-feedback-audit'/uuid.uuid4().hex[:8];folder.mkdir(parents=True);helper=folder/'Alpha5Native.cs';helper.write_text(SOURCE,encoding='utf-8')
    redist=Path(os.environ.get('SW_INSTALL_DIR',r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'))/'api/redist';names=('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')
    for n in names:(folder/n).write_bytes((redist/n).read_bytes())
    exe=folder/'Alpha5Native.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe';command=[str(compiler),'/nologo','/platform:x64','/main:Alpha5Native','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll','/out:'+str(exe)]+['/reference:'+str(redist/n) for n in names]+[str(p) for p in (ROOT/'executor').glob('*.cs')]+[str(helper)];subprocess.run(command,check=True)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()};journal=ROOT/'runs/executor-state.json';journal_hash=hashlib.sha256(journal.read_bytes()).hexdigest() if journal.exists() else None
    output=folder/'session.json';report={'completed':False,'source':str(source),'source_hashes':hashes,'protected_journal_sha256':journal_hash};save=lambda:output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    owned=subprocess.Popen([str(redist.parents[1]/'SLDWORKS.exe')],startupinfo=startup);report['owned_pid']=owned.pid;save();print('OWNED_INSTANCE',owned.pid,str(folder),flush=True)
    env={**os.environ,'SW_MCP_PROCESS_ID':str(owned.pid)};deadline=time.monotonic()+180
    while True:
        if owned.poll() is not None:report['owned_exit_code']=owned.returncode;save();raise RuntimeError('Owned SolidWorks exited before connection; preserve evidence')
        check=subprocess.run([str(ROOT/'executor/bin/SwExecutor.exe'),'check-connection'],env=env,capture_output=True,timeout=25)
        hello=json.loads(check.stdout);report['connection_attempt']=hello;save()
        if hello.get('ready'):assert hello['process_id']==owned.pid;break
        if time.monotonic()>deadline:raise TimeoutError('COM startup pending; preserve owned instance')
        time.sleep(2)
    auto=subprocess.run([str(ROOT/'executor/bin/SwExecutor.exe'),'check-connection'],env={**os.environ,'SW_MCP_PROCESS_ID':'auto'},capture_output=True,timeout=30);report['auto_connection']=json.loads(auto.stdout);save()
    with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as err:
        test=subprocess.Popen([str(exe),str(folder),str(owned.pid),str(source)],env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW);report['executor_pid']=test.pid;save();test.wait(timeout=900)
    report.update(exit_code=test.returncode,source_files_unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items()),protected_journal_unchanged=(hashlib.sha256(journal.read_bytes()).hexdigest() if journal.exists() else None)==journal_hash)
    report['completed']=test.returncode==0 and report['source_files_unchanged'] and report['protected_journal_unchanged'];save()
    try:owned.wait(timeout=45);report['owned_exit_code']=owned.returncode
    except subprocess.TimeoutExpired:report['owned_shutdown_pending']=True
    save();print(json.dumps(report,ensure_ascii=True),flush=True)
    if not report['completed']:raise RuntimeError('Native checks failed; see '+str(output))

if __name__=='__main__':main()
