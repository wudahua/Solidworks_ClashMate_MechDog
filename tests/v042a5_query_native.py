"""Native parent/child continuation regression for both geometric query tools."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix

matrix.CS=matrix.CS[:matrix.CS.index('class ProbeAcceptance')]+r'''
class ProbeAcceptance {
 static Dictionary<string,object> D(object v){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(v));}
 static Dictionary<string,object>[] Rows(object v){return Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(v));}
 [STAThread]static int Main(string[] a){if(a.Length==2&&a[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(a[1]);Cad cad=null;int pid=int.Parse(a[2]);var r=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(a[0],"native.json"),Cad.Json.Serialize(r));using(var gate=new Mutex(false,@"Local\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{
 cad=new Cad(a[0]);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");string id=(string)D(cad.ImportUserAssembly(a[1],""))["model_id"];var components=Rows(D(cad.InspectUserModel(id,"components"))["components"]);var cases=new List<object>();r["cases"]=cases;
 foreach(bool drive in new[]{false,true}){Func<string,int,string,Dictionary<string,object>> query=(component,face,cursor)=>D(drive?cad.UserDriveCandidates(id,component,"",50,cursor,false,true,face):cad.ListMateReferences(id,component,"",50,cursor,true,face));cad.GeometryQueryTestBudgetMs=1;var parent=query("",0,null);cad.GeometryQueryTestBudgetMs=0;var parentScan=D(parent["geometry_scan"]);var pending=Rows(parentScan["next_queries"]);if(pending.Length<2||(bool)parent["geometry_complete"])throw new Exception("TWO_SIBLING_TASKS_NOT_REPRODUCED");var queue=new List<Dictionary<string,object>>(pending);if((bool)parentScan["next_queries_truncated"])queue=components.Select(c=>new Dictionary<string,object>{{"component_id",c["component_id"]},{"face_offset",0}}).ToList();var seen=new HashSet<string>();var pages=new List<object>();var entry=new Dictionary<string,object>{{"tool",drive?"list_drive_candidates":"list_mate_references"},{"parent",parent},{"pages",pages}};cases.Add(entry);int tasks=0;
 while(queue.Count>0){if(++tasks>100)throw new Exception("QUEUE_DID_NOT_CONVERGE");var task=queue[0];queue.RemoveAt(0);int siblings=queue.Count;string cursor=null;Dictionary<string,object> child=null;do{child=query((string)task["component_id"],Convert.ToInt32(task["face_offset"]),cursor);if((bool)child["geometry_complete"]||child["model_geometry_complete"]!=null||D(child["geometry_scan"])["pending_query_count"]!=null)throw new Exception("SCOPED_FALSE_MODEL_COMPLETION");foreach(var e in Rows(child["entities"]))seen.Add((string)e["entity_id"]);cursor=child["next_cursor"] as string;pages.Add(new{result=child,parent_sibling_tasks_retained=siblings});save();}while(cursor!=null);queue.AddRange(Rows(D(child["geometry_scan"])["next_queries"]));if(queue.Count<siblings)throw new Exception("SIBLING_TASKS_LOST");}
 entry["client_queue_completed"]=true;entry["observed_entity_count"]=seen.Count;entry["continuation_tasks"]=tasks;entry["page_count"]=pages.Count;save();if(seen.Count==0)throw new Exception("NO_NATIVE_GEOMETRY_OBSERVED");
 try{query("component_invalid",0,null);throw new Exception("INVALID_COMPONENT_ACCEPTED");}catch(CadFault e){if(e.Code!="COMPONENT_ID_NOT_FOUND")throw;entry["invalid_component"]=new{code=e.Code,details=e.Diagnostics};}
 }
 r["all_passed"]=true;r["completed"]=true;save();return 0;
 }catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
'''
if __name__ == '__main__': matrix.main()
