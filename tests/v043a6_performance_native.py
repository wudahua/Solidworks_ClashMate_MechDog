"""Matched owned-copy regression: bounded scans, exact profiles and full recovery.

Extends alpha.5's independent archived identity oracle and pagination fixture.
No reference to a user CAD process is accepted; --source is copied privately.
"""
import v043a5_observation_native as previous
harness=previous.harness
code=harness.matrix.CS
needle='"component_loop_ms","batch_restore_ms","other_elapsed_ms"'
assert needle in code
code=code.replace(needle,'"component_loop_ms","batch_restore_ms","export_and_assemble_ms","other_elapsed_ms"')
needle='r["completed"]=true;save();return 0;'
assert needle in code
extra=r'''
var alpha6Profiles=new Dictionary<string,object>();
foreach(string key in new[]{"run","verify"}){
 var output=D(r[key]);string rid=(string)output["run_id"];string folder=Path.Combine(a[0],"runs",rid);var solve=D(Cad.Json.DeserializeObject(File.ReadAllText(Path.Combine(folder,"solve.json"))));var phases=D(D(solve["solve_performance"])["phase_totals_ms"]);
 var names=D(solve["component_name_resolution"]);if(Convert.ToInt32(names["schema_version"])!=3||Math.Abs(Convert.ToDouble(names["phase_elapsed_ms"])-Convert.ToDouble(phases["resolve_component_names"]))>1e-5||Convert.ToDouble(names["phase_gap_ms"])<0||Convert.ToDouble(names["export_and_assemble_ms"])<0)throw new Exception("NAME_PARENT_EXPORT_ENVELOPE");
 var sampling=D(solve["sampling_performance"]);var exclusive=D(sampling["exclusive_stage_totals_ms"]);double wall=Convert.ToDouble(sampling["sampling_elapsed_ms"]),measured=exclusive.Values.Sum(v=>Convert.ToDouble(v)),remaining=Convert.ToDouble(sampling["unattributed_elapsed_ms"]);if(measured>wall+.001||Math.Abs(wall-measured-remaining)>.001||!exclusive.ContainsKey("batch_enter_ms")||!exclusive.ContainsKey("batch_restore_ms")||!exclusive.ContainsKey("progress_and_logging_ms"))throw new Exception("SAMPLING_EXCLUSIVE_ACCOUNTING");
 var overview=D(solve["component_overview_performance"]);if((string)overview["api_batch_status"]!="not_added_preserve_original_role_read_path"||(bool)overview["persistent_id_resolution_performed"]||(bool)overview["sampled_poses_reread"]||Math.Abs(Convert.ToDouble(overview["phase_elapsed_ms"])-Convert.ToDouble(phases["component_overview_and_manifest"]))>.001)throw new Exception("OVERVIEW_ENVELOPE");
 var axis=D(Cad.Json.DeserializeObject(File.ReadAllText(Path.Combine(folder,"time-axis.json"))));if(D(axis["native_read_timings"])["current_stage"]!=null||!(bool)D(axis["diagnostic"])["verified"])throw new Exception("NATIVE_AXIS_SUBPHASES");
 alpha6Profiles[key]=new{names=names,sampling=sampling,overview=overview,axis=axis};
}
// Explicit nondefault scan budget reaches native execution. A continuation is
// bound to this exact budget; another value cannot silently re-use its cursor.
var budgetPage=D(cad.ListMateReferences(id,"","",1,null,true,0,20,30));string budgetCursor=budgetPage["next_cursor"] as string;var scan=D(budgetPage["geometry_scan"]);
if(Convert.ToInt32(scan["cooperative_budget_ms"])!=30000||scan["scan_determinism"]==null||budgetCursor==null)throw new Exception("GEOMETRY_BUDGET_NOT_FORWARDED");
bool rejectedBudgetChange=false;try{cad.ListMateReferences(id,"","",1,budgetCursor,true,0,20,10);}catch(CadFault e){if(e.Code!="MATE_CURSOR_STALE"||(string)D(e.Diagnostics)["cause"]!="query_options_changed")throw;rejectedBudgetChange=true;}
if(!rejectedBudgetChange)throw new Exception("GEOMETRY_BUDGET_CURSOR_NOT_BOUND");
var budgetContinuation=D(cad.ListMateReferences(id,"","",1,budgetCursor,true,0,20,30));if((bool)D(budgetContinuation["pagination_snapshot"])["geometry_rescanned"]||!budgetContinuation.ContainsKey("host_timings")||!budgetContinuation.ContainsKey("scan_host_timings"))throw new Exception("BUDGET_CONTINUATION_OR_LEGACY_TIMING_ALIAS");
r["alpha6_native_profiles"]=alpha6Profiles;r["explicit_geometry_budget"]=new{requested_s=30,observed_ms=scan["cooperative_budget_ms"],changed_budget_rejected=true,continuation_without_rescan=true};
'''
harness.matrix.CS=code.replace(needle,extra+needle,1)

if __name__=='__main__':harness.main()
