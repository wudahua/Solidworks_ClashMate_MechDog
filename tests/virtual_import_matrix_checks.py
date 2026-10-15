"""Owned CAD matrix on program-generated sources, never on user design originals."""
import argparse,hashlib,json,os,subprocess,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CS=r'''using System;using System.IO;using System.Linq;using System.Collections.Generic;using System.Threading;using SolidWorks.Interop.sldworks;
public partial class Cad {
 public string MatrixMakeSolidVirtual(string id){var m=GetUserModel(id);using(var s=new Scope(this,m.Path,null)){var c=UserComponents(s.Doc).First(v=>!v.IsFixed());if(!c.MakeVirtual2(false)||!c.IsVirtual)throw new Exception("MATRIX_VIRTUAL_CREATION_FAILED");Save(s.Doc,m.Path);}CloseUserDocuments(m.Files);return m.Path;}
 public void MatrixClose(int pid){if(Sw.GetProcessID()!=pid)throw new Exception("OWNED_PID_MISMATCH");var docs=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().ToArray();if(docs.Any(d=>!d.GetPathName().StartsWith(Root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)&&d.GetPathName().IndexOf("VC~~",StringComparison.OrdinalIgnoreCase)<0))throw new Exception("NON_OWNED_DOC_REFUSE_EXIT");foreach(var d in docs)Sw.CloseDoc(d.GetTitle());Sw.ExitApp();}
 public void MatrixRejectIncomplete(string id){GetUserModel(id);}
}
class MatrixAcceptance {
 static Dictionary<string,object> D(object x){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(x));}
 [STAThread] static int Main(string[] args){string root=Path.GetFullPath(args[0]);int pid=int.Parse(args[2]);if(!root.Contains("virtual-import-matrix"+Path.DirectorySeparatorChar))return 3;Cad cad=null;var report=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(root,"matrix.json"),Cad.Json.Serialize(report));using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{cad=new Cad(root);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");var prepared=D(cad.ImportUserAssembly(args[1],""));string preparedId=(string)prepared["model_id"];report["prepared"]=prepared;save();string assembly=cad.MatrixMakeSolidVirtual(preparedId);report["fixture_assembly"]=assembly;save();
 var imported=D(cad.ImportUserAssembly(assembly,"",null,null,null,true));report["solid_mated_virtual_import"]=imported;save();string id=(string)imported["model_id"];report["inspection"]=cad.InspectUserModel(id);report["restore"]=cad.RestoreUserCheckpoint(id,(string)D(imported["checkpoint"])["checkpoint_id"]);report["completed"]=true;save();return 0;
 }catch(Exception e){report["error"]=e.ToString();report["details"]=e is CadFault?((CadFault)e).Diagnostics:null;if(e is CadFault){var d=D(((CadFault)e).Diagnostics);if(d.ContainsKey("model_id"))try{cad.MatrixRejectIncomplete((string)d["model_id"]);report["incomplete_guard"]=false;}catch(CadFault guard){report["incomplete_guard"]=guard.Code=="MODEL_IMPORT_INCOMPLETE";}}save();return 1;}finally{if(cad!=null)try{cad.MatrixClose(pid);report["owned_exit_requested"]=true;}catch(Exception e){report["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}
 }
}'''
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);args=parser.parse_args();source=Path(args.source).resolve()
 if source.name.lower()!='rotary.sldasm' or not (source.parent/'examples.json').is_file():raise ValueError('Use the program-generated example assembly')
 folder=ROOT/'runs/virtual-import-matrix'/uuid.uuid4().hex[:8];folder.mkdir(parents=True);helper=folder/'test.cs';helper.write_text(CS,encoding='utf-8');redist=Path(os.environ.get('SW_INSTALL_DIR',r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'))/'api/redist';names=('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')
 for n in names:(folder/n).write_bytes((redist/n).read_bytes())
 exe=folder/'Matrix.exe';command=[str(Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'),'/nologo','/platform:x64','/main:MatrixAcceptance','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll','/out:'+str(exe)]+['/reference:'+str(redist/n) for n in names]+[str(p) for p in (ROOT/'executor').glob('*.cs')]+[str(helper)];subprocess.run(command,check=True)
 hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source.parent.iterdir() if p.is_file()};journal=ROOT/'runs/executor-state.json';before=hashlib.sha256(journal.read_bytes()).hexdigest();report={'directory':str(folder),'source_hashes':hashes,'primary_journal_sha256':before};save=lambda:(folder/'session.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0;owned=subprocess.Popen([str(redist.parents[1]/'SLDWORKS.exe')],startupinfo=startup);env={**os.environ,'SW_MCP_PROCESS_ID':str(owned.pid)};report['owned_pid']=owned.pid;save();print('OWNED_INSTANCE',owned.pid,str(folder),flush=True);deadline=time.monotonic()+180
 while True:
  check=subprocess.run([str(ROOT/'executor/bin/SwExecutor.exe'),'check-connection'],env=env,capture_output=True,timeout=25);hello=json.loads(check.stdout)
  if hello.get('ready'):assert hello['process_id']==owned.pid;break
  if owned.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Owned application not connected')
  time.sleep(2)
 with (folder/'stdout.log').open('wb') as out,(folder/'stderr.log').open('wb') as err:
  test=subprocess.Popen([str(exe),str(folder),str(source),str(owned.pid)],env=env,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW);report['helper_pid']=test.pid;save();test.wait(timeout=600)
 report.update(helper_exit=test.returncode,source_files_unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items()),primary_journal_unchanged=hashlib.sha256(journal.read_bytes()).hexdigest()==before)
 try:owned.wait(timeout=45);report['owned_exit_code']=owned.returncode
 except subprocess.TimeoutExpired:report['owned_exit_pending']=True
 report['completed']=test.returncode==0 and report['source_files_unchanged'] and report['primary_journal_unchanged'];save();(ROOT/'runs/virtual-import-matrix-latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='source_hashes'},ensure_ascii=True))
if __name__=='__main__':main()
