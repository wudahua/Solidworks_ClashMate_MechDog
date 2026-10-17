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
 var states=Cad.Json.Deserialize<Cad.StudyState[]>(Cad.Json.Serialize(cad.ProbeTestStates(id)));string study=states.First(s=>s.type==1||s.type==4).name;var cp=D(cad.CreateUserCheckpoint(id));r["nonzero_checkpoint"]=cp;save();
 var results=new List<object>();r["branches"]=results;Dictionary<string,double[]> baseline=null;
 foreach(int fps in new[]{30,8}){var reset=D(cad.ResetStudyInNewModel(id,study,fps,true,(string)cp["checkpoint_id"]));string child=(string)reset["model_id"];var actual=cad.ResetTestPoses(child);if(baseline==null){baseline=actual;r["zero_baseline_by_component_id"]=baseline;}bool same=baseline.Count==actual.Count&&baseline.All(p=>actual.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,actual[p.Key]));results.Add(new{output_fps=fps,reset=reset,branch_zero_matches_30fps=same,checked_components=actual.Count,states=cad.ResetTestClockAndHealth(child)});save();if(!same||!(bool)reset["original_model_unchanged"])throw new Exception("BRANCH_ZERO_POSE_MISMATCH");}
 var inPlace=D(cad.ResetUserStudyTime(id,study,true));r["in_place"]=inPlace;var final=cad.ResetTestPoses(id);r["in_place_by_component_id"]=final;bool matches=baseline.Count==final.Count&&baseline.All(p=>final.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,final[p.Key]));r["in_place_matches_30fps_zero"]=matches;save();if(!matches)throw new Exception("IN_PLACE_RESET_DID_NOT_MATCH_ZERO_BRANCH");
 r["completed"]=true;save();return 0;
 }catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
'''
if __name__=="__main__":matrix.main()
