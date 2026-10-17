"""Explicit owned-instance geometry-budget and post-write rollback regression."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix
matrix.CS=matrix.CS[:matrix.CS.index("class ProbeAcceptance")]+r'''
class ProbeAcceptance {
 static Dictionary<string,object> D(object v){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(v));}
 static Dictionary<string,object>[] Rows(object v){return Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(v));}
 [STAThread]static int Main(string[] a){if(a.Length==2&&a[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(a[1]);Cad cad=null;int pid=int.Parse(a[2]);var r=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(a[0],"native.json"),Cad.Json.Serialize(r));using(var gate=new Mutex(false,@"Local\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{
 cad=new Cad(a[0]);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");var imported=D(cad.ImportUserAssembly(a[1],""));string id=(string)imported["model_id"];r["import"]=imported;save();
 cad.GeometryQueryTestBudgetMs=1;var limited=D(cad.ListMateReferences(id,"","cylindrical_axis",50,null,true));r["budget_limited_query"]=limited;save();var budget=D(limited["geometry_scan"]);if(!(bool)budget["scan_budget_exhausted"]||Convert.ToInt32(budget["pending_query_count"])<1||(bool)limited["geometry_complete"])throw new Exception("GEOMETRY_BUDGET_NOT_ENFORCED");cad.GeometryQueryTestBudgetMs=0;
 var next=Rows(budget["next_queries"])[0];var continued=D(cad.ListMateReferences(id,(string)next["component_id"],"",50,null,true,Convert.ToInt32(next["face_offset"])));r["continued_component_query"]=continued;save();
 var first=Rows(continued["entities"]).First();var stable=D(cad.ListMateReferences(id,(string)first["component_id"],(string)first["kind"],50,null,true,Convert.ToInt32(first["native_face_index"])));if(!Rows(stable["entities"]).Any(e=>(string)e["entity_id"]==(string)first["entity_id"]&&e.ContainsKey("area_m2")))throw new Exception("EXACT_FACE_ID_NOT_STABLE_OR_COMPACT_AREA_MISSING");r["stable_face_id_verified"]=true;
 var raw=D(cad.ImportUserAssembly(Path.Combine(a[3],"rotary_unmated.SLDASM"),""));string rawId=(string)raw["model_id"];foreach(var state in Cad.Json.Deserialize<Cad.StudyState[]>(Cad.Json.Serialize(cad.ProbeTestStates(rawId))))cad.ResetUserStudyTime(rawId,state.name,true);
 var refs=Rows(D(cad.ListMateReferences(rawId,"","cylindrical_axis",50,null))["entities"]);var fixedFace=refs.First(v=>(bool)v["fixed_component"]);var moving=refs.First(v=>!(bool)v["fixed_component"]);var plan=D(cad.PreviewBasicMate(rawId,(string)fixedFace["entity_id"],(string)moving["entity_id"],"concentric","aligned",0,false,""));
 try{cad.ApplyBasicMate((string)plan["plan_id"],true,true);throw new Exception("CONTROLLED_WRITE_DID_NOT_ROLL_BACK");}catch(CadFault error){r["rollback_code"]=error.Code;r["rollback_details"]=error.Diagnostics;save();if(error.Code!="MATE_APPLY_ROLLED_BACK"||!(bool)D(error.Diagnostics)["rollback_verified"]||cad.LastOperationRestoration!="restored")throw;}
 if(Convert.ToInt32(D(cad.ProbeTestCounts(rawId))["mate_count"])!=0)throw new Exception("ROLLED_BACK_MATE_PERSISTED");r["completed"]=true;save();return 0;
 }catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
'''
if __name__=="__main__":matrix.main()
