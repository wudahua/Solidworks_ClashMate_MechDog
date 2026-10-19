"""Frozen geometry pages and verified-baseline workflow on the owned slider copy.

Extends the saved six-component acceptance fixture. Never attaches to user CAD.
"""
import v043a3_performance_native as previous

harness = previous.harness
extra = r'''
var pagingEvidence=new List<object>();
foreach(bool mates in new[]{true,false}){
 int guardSequence=0;string toolPrefix=mates?"mate":"drive";
 cad.GeometryQueryTestObserver=observation=>File.WriteAllText(Path.Combine(a[0],toolPrefix+"-guard-"+(guardSequence++)+".json"),Cad.Json.Serialize(observation));
 cad.GeometryQueryTestBudgetMs=3000;
 Func<string,Dictionary<string,object>> query=token=>D(mates?cad.ListMateReferences(id,"","",token==null?1:20,token,true):cad.UserDriveCandidates(id,"","",token==null?1:20,token,false,true));
 var first=query(null);var rows=new List<string>();var firstEntities=Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(first["entities"]));
 rows.AddRange(firstEntities.Select(e=>(string)e["entity_id"]));
 string cursor=first["next_cursor"] as string;int total=Convert.ToInt32(first["total"]),pages=1;
 if(cursor==null||total<2)throw new Exception("PAGINATION_FIXTURE_NEEDS_MULTIPLE_ROWS");
 // The injected scan budget changes only the test hook, not the model. A
 // continuation must NOT observe a different timed subset or scan geometry.
 cad.GeometryQueryTestBudgetMs=1;
 var repeated=query(cursor);var repeatedAgain=query(cursor);
 if(Cad.Json.Serialize(repeated["entities"])!=Cad.Json.Serialize(repeatedAgain["entities"]))throw new Exception("FROZEN_CURSOR_NOT_REPEATABLE");
 cad.ProbeTestFrozenCursorRevisionGuard(id,()=>query(cursor));
 while(cursor!=null){var page=query(cursor);if((bool)D(page["pagination_snapshot"])["geometry_rescanned"])throw new Exception("CURSOR_RESCANNED_GEOMETRY");
 if(Convert.ToInt32(page["total"])!=total||Cad.Json.Serialize(page["geometry_scan"])!=Cad.Json.Serialize(first["geometry_scan"]))throw new Exception("FROZEN_PENDING_QUEUE_CHANGED");
 rows.AddRange(Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(page["entities"])).Select(e=>(string)e["entity_id"]));cursor=page["next_cursor"] as string;if(++pages>200)throw new Exception("PAGING_DID_NOT_END");}
 if(rows.Count!=total||rows.Distinct().Count()!=total)throw new Exception("FROZEN_ROWS_LOST_OR_DUPLICATED");
 pagingEvidence.Add(new{tool=mates?"list_mate_references":"list_drive_candidates",pages=pages,total=total,frozen_rows_complete=true,repeatable_cursor=true,revision_change_rejected=true,pending_queue_unchanged=true,geometry_budget=first["geometry_scan"]});
 cad.GeometryQueryTestBudgetMs=0;cad.GeometryQueryTestObserver=null;
 r["frozen_pagination"]=pagingEvidence;save();
}
r["frozen_pagination"]=pagingEvidence;save();
'''
method = r'''
public partial class Cad {
 public void ProbeTestFrozenCursorRevisionGuard(string id,Action action){var m=GetUserModel(id);bool rejected=false;try{m.Revision++;try{action();}catch(CadFault e){if(e.Code!="MATE_CURSOR_STALE"&&e.Code!="CANDIDATE_CURSOR_STALE")throw;rejected=true;}}finally{m.Revision--;}if(!rejected)throw new Exception("FROZEN_CURSOR_ACCEPTED_MODEL_CHANGE");}
}
'''
harness.matrix.CS=harness.matrix.CS.replace('class ProbeAcceptance {',method+'class ProbeAcceptance {',1)
needle='r["signature_compatibility"]='
assert needle in harness.matrix.CS
harness.matrix.CS=harness.matrix.CS.replace(needle,extra+needle,1)

baseline=r'''
var verification=D(r["verify"]);var candidate=D(verification["baseline_candidate"]);
if((string)candidate["status"]!="eligible_saved_input_verified"||(string)candidate["run_id"]!=(string)verification["run_id"]||(bool)candidate["automatic_rebinding"])throw new Exception("NEW_BASELINE_NOT_EXPLICIT_OR_VERIFIED");
var followup=D(cad.PreviewBasicMate(id,(string)pa["entity_id"],(string)pb["entity_id"],"perpendicular","aligned",0,false,(string)candidate["run_id"]));
r["post_verify_baseline_preview"]=followup;r["baseline_candidate_verified"]=candidate;save();
'''
needle='foreach(string key in new[]{"run","verify"})'
assert needle in harness.matrix.CS
harness.matrix.CS=harness.matrix.CS.replace(needle,baseline+needle,1)

if __name__=='__main__':
    harness.main()
