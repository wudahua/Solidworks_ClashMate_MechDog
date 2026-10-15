"""Explicit CAD acceptance on an isolated source copy and an owned application only."""
import argparse, hashlib, json, os, subprocess, time, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CS=r'''using System;using System.IO;using System.Linq;using System.Threading;using System.Collections.Generic;using SolidWorks.Interop.sldworks;
public partial class Cad {
 public void VirtualAcceptanceClose(int pid){if(Sw.GetProcessID()!=pid)throw new Exception("OWNED_PID_MISMATCH");var docs=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().ToArray();if(docs.Any(d=>!d.GetPathName().StartsWith(Root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)&&d.GetPathName().IndexOf("VC~~",StringComparison.OrdinalIgnoreCase)<0))throw new Exception("NON_OWNED_DOC_REFUSE_EXIT");foreach(var d in docs)Sw.CloseDoc(d.GetTitle());Sw.ExitApp();}
}
class VirtualAcceptance {
 static Dictionary<string,object> D(object x){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(x));}
 static Dictionary<string,object>[] Rows(object x){return Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(x));}
 static void Require(bool v,string code){if(!v)throw new Exception(code);}
 [STAThread] static int Main(string[] args){string root=Path.GetFullPath(args[0]),source=Path.GetFullPath(args[1]);int pid=int.Parse(args[2]);if(!root.Contains("virtual-import-acceptance"+Path.DirectorySeparatorChar))return 3;Cad cad=null;var output=new Dictionary<string,object>{{"completed",false},{"steps",new List<object>()}};Action save=()=>File.WriteAllText(Path.Combine(root,"native.json"),Cad.Json.Serialize(output));Action<string,object> record=(n,d)=>{((List<object>)output["steps"]).Add(new{name=n,data=d});save();Cad.Log("VIRTUAL_ACCEPTANCE "+n);};
 using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try {
  cad=new Cad(root);Require(cad.Sw.GetProcessID()==pid&&(cad.Sw.GetDocuments() as object[]??new object[0]).Length==0,"OWNED_INSTANCE_NOT_EMPTY");
  try{cad.ImportUserAssembly(source,"");throw new Exception("DEFAULT_VIRTUAL_IMPORT_NOT_REJECTED");}catch(CadFault e){Require(e.Code=="VIRTUAL_COMPONENT_REFERENCE_UNSUPPORTED","DEDICATED_ERROR_MISSING");Require(!Cad.Json.Serialize(e.Diagnostics).Contains("C:\\\\Users"),"OLD_MACHINE_PATH_EXPOSED");record("default_virtual_import_clear_error",new{code=e.Code,details=e.Diagnostics});}
  var imported=D(cad.ImportUserAssembly(source,"",null,null,null,true));record("explicit_materialization",imported);Require(Convert.ToInt32(imported["file_count"])==7,"EXPECTED_SEVEN_FILES");string id=(string)imported["model_id"],initial=(string)D(imported["checkpoint"])["checkpoint_id"];
  var inspected=D(cad.InspectUserModel(id));record("inspect_after_externalization",inspected);Require(Rows(inspected["components"]).Length==6,"COMPONENT_COUNT_CHANGED");var mates=Rows(inspected["mates"]);Require(mates.Length==6,"MATE_COUNT_CHANGED");var tangent=mates.Single(m=>(string)m["name"]=="CONTACTO TANGENTE");var refs=Rows(tangent["entities"]);Require(refs.All(e=>(string)e["geometry_status"]=="unsupported_surface_type")&&refs.Select(e=>(string)e["surface_type"]).OrderBy(v=>v).SequenceEqual(new[]{"sphere","torus"}),"CURVED_SURFACE_DIAGNOSTIC_WRONG");
  var studies=D(cad.UserStudies(id,true));record("existing_study_inventory",studies);Require(Rows(studies["studies"]).Length==4,"STUDIES_CHANGED");
  var reference=mates.SelectMany(m=>Rows(m["entities"])).Where(e=>e.ContainsKey("geometry")).Select(e=>D(e["geometry"])).First(e=>(string)e["kind"]=="cylindrical_axis"&&((string)e["instance"]).IndexOf("polea",StringComparison.OrdinalIgnoreCase)>=0);string component=(string)reference["component_id"],entity=(string)reference["entity_id"];
  record("create_explicit_rotary_drive",cad.CreateUserStudy(id,"VirtualAcceptance",component,entity,"rotary",30,false,"",2,30));record("registered_native_drive_observation",cad.UserStudies(id,true));string run=Guid.NewGuid().ToString("N");record("motion_61_frames",cad.RunUserStudy(id,"VirtualAcceptance",2,30,run));
  var replay=D(cad.ReplayUserFrame(run,30,20));record("replay_all_six_component_diagnostics",replay);var diagnostic=D(replay["pose_validation"]);Require(Convert.ToInt32(diagnostic["checked_component_count"])==6&&Convert.ToInt32(diagnostic["returned_diagnostic_count"])==6&&!(bool)diagnostic["components_truncated"],"REPLAY_DIAGNOSTICS_INCOMPLETE");
  record("verify_360_degrees",cad.VerifyRequestedMotion(id,"VirtualAcceptance",component,entity,"rotary",360,2,30,Guid.NewGuid().ToString("N"),""));record("restore_initial_checkpoint",cad.RestoreUserCheckpoint(id,initial));record("source_unchanged",D(cad.InspectUserModel(id))["source_files_unchanged"]);output["completed"]=true;save();return 0;
 }catch(Exception e){output["error"]=e.ToString();output["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.VirtualAcceptanceClose(pid);output["owned_exit_requested"]=true;}catch(Exception e){output["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}
 }
}'''
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);args=parser.parse_args();source=Path(args.source).resolve()
 if not source.is_file() or source.suffix.lower()!='.sldasm':raise ValueError('Specify the saved test assembly')
 folder=ROOT/'runs/virtual-import-acceptance'/uuid.uuid4().hex[:8];folder.mkdir(parents=True);(folder/'test.cs').write_text(CS,encoding='utf-8')
 redist=Path(os.environ.get('SW_INSTALL_DIR',r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'))/'api/redist';dlls=('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')
 for n in dlls:(folder/n).write_bytes((redist/n).read_bytes())
 exe=folder/'VirtualAcceptance.exe';command=[str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/platform:x64','/main:VirtualAcceptance','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll','/out:'+str(exe)]+['/reference:'+str(redist/n) for n in dlls]+[str(p) for p in (ROOT/'executor').glob('*.cs')]+[str(folder/'test.cs')];subprocess.run(command,check=True)
 hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.parent.iterdir() if p.is_file()};journal=ROOT/'runs/executor-state.json';journal_hash=hashlib.sha256(journal.read_bytes()).hexdigest()
 report={'completed':False,'directory':str(folder),'source_hashes':hashes,'primary_journal_sha256':journal_hash};save=lambda:(folder/'session.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0;owned=subprocess.Popen([str(redist.parents[1]/'SLDWORKS.exe')],startupinfo=startup);report['owned_pid']=owned.pid;save();print('OWNED_INSTANCE',owned.pid,str(folder),flush=True);env={**os.environ,'SW_MCP_PROCESS_ID':str(owned.pid)};deadline=time.monotonic()+180
 while True:
  if owned.poll() is not None:raise RuntimeError('Owned application exited before connection')
  check=subprocess.run([str(ROOT/'executor/bin/SwExecutor.exe'),'check-connection'],env=env,capture_output=True,timeout=25);hello=json.loads(check.stdout);report['connection']=hello;save()
  if hello.get('ready'):assert hello['process_id']==owned.pid;break
  if time.monotonic()>deadline:raise TimeoutError('COM startup pending')
  time.sleep(2)
 with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as err:
  helper=subprocess.Popen([str(exe),str(folder),str(source),str(owned.pid)],env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW);report['helper_pid']=helper.pid;save();helper.wait(timeout=900)
 report.update(helper_exit=helper.returncode,source_files_unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items()),primary_journal_unchanged=hashlib.sha256(journal.read_bytes()).hexdigest()==journal_hash)
 try:owned.wait(timeout=45);report['owned_exit_code']=owned.returncode
 except subprocess.TimeoutExpired:report['owned_exit_pending']=True
 report['completed']=helper.returncode==0 and report['source_files_unchanged'] and report['primary_journal_unchanged'];save();(ROOT/'runs/virtual-import-acceptance-latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','connection')},ensure_ascii=True),flush=True)
if __name__=='__main__':main()
