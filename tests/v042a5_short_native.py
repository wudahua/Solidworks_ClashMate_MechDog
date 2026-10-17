"""Short-duration Motion settings and native grid regression in an owned copy."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix

matrix.CS = matrix.CS[:matrix.CS.index('class ProbeAcceptance')] + r'''
class ProbeAcceptance {
 static Dictionary<string,object> D(object v){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(v));}
 static Dictionary<string,object>[] Rows(object v){return Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(v));}
 [STAThread]static int Main(string[] a){if(a.Length==2&&a[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(a[1]);Cad cad=null;int pid=int.Parse(a[2]);var r=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(a[0],"native.json"),Cad.Json.Serialize(r));using(var gate=new Mutex(false,@"Local\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{
 cad=new Cad(a[0]);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");var imported=D(cad.ImportUserAssembly(a[1],""));string id=(string)imported["model_id"];r["import"]=imported;save();
 var cs=Rows(D(cad.InspectUserModel(id,"components"))["components"]);var component=cs.Single(e=>!(bool)e["fixed_component"]&&((string)e["instance"]).IndexOf("Part6",StringComparison.OrdinalIgnoreCase)>=0);string cid=(string)component["component_id"];var refs=Rows(D(cad.ListMateReferences(id,cid,"cylindrical_axis",50,null,true))["entities"]);var drive=refs.First(e=>Math.Abs(((System.Collections.IEnumerable)e["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last())>.99);string eid=(string)drive["entity_id"];
 var trials=new List<object>();r["trials"]=trials;
 foreach(int index in new[]{0,1,2,3,4}){double duration=new[]{.1,.3,.1,1.0/3,.5}[index];int fps=index==2?100:30;string name="Short_"+index;var t=new Dictionary<string,object>{{"duration_s",duration},{"output_fps",fps}};trials.Add(t);try{t["created"]=cad.CreateUserStudy(id,name,cid,eid,"rotary",10,false,"",duration,fps);t["settings_after_create"]=cad.ProbeTestStates(id);save();t["run"]=cad.RunUserStudy(id,name,duration,fps,Guid.NewGuid().ToString("N"));t["passed"]=true;}catch(Exception e){t["passed"]=false;t["error"]=e.ToString();t["details"]=e is CadFault?((CadFault)e).Diagnostics:null;t["expected_admission_rejection"]=index<2&&e is CadFault&&((CadFault)e).Code=="OUTPUT_GRID_TOO_SPARSE_FOR_NATIVE_ADAPTER";}save();}
 r["all_passed"]=trials.Cast<Dictionary<string,object>>().All(t=>(bool)t["passed"]||(t.ContainsKey("expected_admission_rejection")&&(bool)t["expected_admission_rejection"]));if(!(bool)r["all_passed"])throw new Exception("SHORT_NATIVE_REGRESSION_FAILED");r["completed"]=true;save();return 0;
 }catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
'''
if __name__ == '__main__': matrix.main()
