"""Explicit owned-instance reset regression. Source assemblies are copied, never opened directly."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix
matrix.CS=matrix.CS[:matrix.CS.index("class ProbeAcceptance")]+r'''
public partial class Cad {
 public Dictionary<string,double[]> ResetTestPoses(string id){var m=GetUserModel(id);using(var scope=new Scope(this,m.Path,null))return UserComponents(scope.Doc).Where(c=>!c.IsSuppressed()).ToDictionary(c=>c.GetID().ToString(),c=>(double[])c.GetTotalTransform(false).ArrayData);}
 public object ResetTestClockAndHealth(string id){var m=GetUserModel(id);using(var scope=new Scope(this,m.Path,null))return new{studies=StudyStates(scope.Doc),health=NativeMateHealth(scope.Doc)};}
}
class ProbeAcceptance {
 static Dictionary<string,object> D(object v){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(v));}
 [STAThread]static int Main(string[] a){if(a.Length==2&&a[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(a[1]);Cad cad=null;int pid=int.Parse(a[2]);var r=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(a[0],"native.json"),Cad.Json.Serialize(r));using(var gate=new Mutex(false,@"Local\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{
 cad=new Cad(a[0]);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");
 var imported=D(cad.ImportUserAssembly(a[1],""));r["import"]=imported;save();string id=(string)imported["model_id"];
 var states=Cad.Json.Deserialize<Cad.StudyState[]>(Cad.Json.Serialize(cad.ProbeTestStates(id)));foreach(var state in states)r["initial_reset_"+state.name]=cad.ResetUserStudyTime(id,state.name,true);save();
 var baseline=cad.ResetTestPoses(id);string study=states.First(s=>s.type==1||s.type==4).name;var cp=D(cad.CreateUserCheckpoint(id));r["checkpoint"]=cp;r["baseline"]=baseline;save();
 var results=new List<object>();r["branches"]=results;
 foreach(int fps in new[]{8,30}){var reset=D(cad.ResetStudyInNewModel(id,study,fps,true,(string)cp["checkpoint_id"]));string child=(string)reset["model_id"];var actual=cad.ResetTestPoses(child);bool same=baseline.Count==actual.Count&&baseline.All(p=>actual.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,actual[p.Key]));results.Add(new{output_fps=fps,reset=reset,checkpoint_zero_pose_matches=same,checked_components=actual.Count,states=cad.ResetTestClockAndHealth(child)});save();if(!same||!(bool)reset["original_model_unchanged"])throw new Exception("BRANCH_DID_NOT_PRESERVE_CHECKPOINT_ZERO_POSE");}
 r["completed"]=true;save();return 0;
 }catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
'''
if __name__=="__main__":matrix.main()
