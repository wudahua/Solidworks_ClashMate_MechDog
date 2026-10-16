"""Explicit owned-instance reset of existing high-FPS studies; never edits the input assembly."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix
matrix.CS=matrix.CS[:matrix.CS.index('class ProbeAcceptance')]+r'''
public partial class Cad {
 public object Alpha9RequireInitial(string id){using(var s=new Scope(this,GetUserModel(id).Path,null)){RequireMateInitialTime(s.Doc);return new{initial_time_verified=true};}}
}
class ProbeAcceptance {
 static Dictionary<string,object> D(object x){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(x));}
 [STAThread]static int Main(string[] args){if(args.Length==2&&args[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(args[1]);string root=Path.GetFullPath(args[0]);int pid=int.Parse(args[2]);Cad cad=null;var report=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(root,"native.json"),Cad.Json.Serialize(report));using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{
 cad=new Cad(root);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");
 var imported=D(cad.ImportUserAssembly(args[1],"",materializeVirtual:true));report["import"]=imported;string id=(string)imported["model_id"];var initial=Cad.Json.Deserialize<Cad.StudyState[]>(Cad.Json.Serialize(cad.ProbeTestStates(id)));report["initial_studies"]=initial;save();if(!initial.Any(s=>s.fps==300&&Math.Abs(s.time_s)>1e-8))throw new Exception("TEST_REQUIRES_EXISTING_NONZERO_300FPS_STUDY");
 try{cad.Alpha9RequireInitial(id);throw new Exception("NONZERO_STUDIES_IGNORED");}catch(CadFault e){if(e.Code!="MATE_REQUIRES_INITIAL_TIME")throw;report["preview_initial_time_guidance"]=e.Diagnostics;save();}
 var resets=new List<object>();foreach(var state in initial.OrderBy(s=>s.active?1:0)){if(Math.Abs(state.time_s)>1e-8){resets.Add(cad.ResetUserStudyTime(id,state.name,true));report["resets"]=resets;save();}}
 var final=Cad.Json.Deserialize<Cad.StudyState[]>(Cad.Json.Serialize(cad.ProbeTestStates(id)));if(final.Any(s=>Math.Abs(s.time_s)>1e-8)||final.Any(s=>{var old=initial.Single(i=>i.name==s.name);return old.fps!=s.fps||old.type!=s.type||Math.Abs(old.duration_s-s.duration_s)>1e-8;}))throw new Exception("RESET_CHANGED_SETTINGS_OR_NONZERO_TIME");report["final_studies"]=final;report["preview_time_gate_after_reset"]=cad.Alpha9RequireInitial(id);report["inspection"]=cad.InspectUserModel(id);save();
 report["completed"]=true;save();return 0;
 }catch(Exception e){report["error"]=e.ToString();report["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){report["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
'''
if __name__=='__main__':matrix.main()
