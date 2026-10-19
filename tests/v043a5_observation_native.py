"""Owned-copy pagination invariants, alpha.4 identity oracle and native timing closure.

The embedded three identity methods are the exact alpha.4 read algorithms,
renamed only, so compatibility does not compare the new code with itself.
Run --source with the saved six-component slider fixture. No user CAD attach.
"""
import v043a4_pagination_native as previous
harness=previous.harness
oracle=r'''public partial class Cad {
public static string Alpha4ComponentIdentity(IModelDoc2 doc,IComponent2[] cs=null){return Json.Serialize((cs??UserComponents(doc)).OrderBy(c=>c.GetID()).Select(c=>new{id=c.GetID(),reference=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(c)),path=c.GetPathName(),configuration=c.ReferencedConfiguration,fixed_component=c.IsFixed(),suppressed=c.IsSuppressed()}).ToArray());}
public static string Alpha4MateHealthIdentity(IModelDoc2 doc,IFeature[] fs=null){return Json.Serialize((fs??BasicMateFeatures(doc)).OrderBy(f=>f.GetID()).Select(f=>{bool warning;return new{id=f.GetID(),error=f.GetErrorCode2(out warning),warning=warning};}).ToArray());}
public static string Alpha4MateIdentity(IModelDoc2 doc,IFeature[] fs=null){return Json.Serialize((fs??BasicMateFeatures(doc)).GroupBy(f=>f.GetID()).Select(g=>g.First()).OrderBy(f=>f.GetID()).Select(f=>{var m=(IMate2)f.GetSpecificFeature2();var lockData=m.Type==(int)SolidWorks.Interop.swconst.swMateType_e.swMateCONCENTRIC?f.GetDefinition() as SolidWorks.Interop.sldworks.IConcentricMateFeatureData:null;double? distance=null;if(m.Type==5){var d=m.DisplayDimension2[0] as IDisplayDimension;if(d==null)throw new Exception("MATE_PARAMETER_UNREADABLE");distance=((IDimension)d.GetDimension2(0)).SystemValue;}return new{id=f.GetID(),type=m.Type,alignment=m.Alignment,lock_rotation=lockData==null?(bool?)null:lockData.LockRotation,distance_m=distance,references=Enumerable.Range(0,m.GetMateEntityCount()).Select(i=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(m.MateEntity(i).Reference))).ToArray()};}).ToArray());}
}
'''
code=harness.matrix.CS.replace('class ProbeAcceptance {',oracle+'class ProbeAcceptance {',1)
for name in ('ComponentIdentity','MateHealthIdentity','MateIdentity'):
    code=code.replace('ProbeWorkingState.'+name+'(doc)', 'Alpha4'+name+'(doc)')
# Check every returned cursor against the actual reduced entity count. Repeated
# calls remain byte-identical and preserve the original subset/pending queue.
needle='rows.AddRange(Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(page["entities"]))'
assert needle in code
code=code.replace(needle,r'''int incomingOffset=Convert.ToInt32(D(Cad.Json.DeserializeObject(System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(cursor))))["offset"]);
int returnedCount=Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(page["entities"])).Length;
string outgoingCursor=page["next_cursor"] as string;
if(Convert.ToInt32(page["returned"])!=returnedCount||(string)page["total_semantics"]!="frozen_observed_subset_not_model_total")throw new Exception("FROZEN_PAGE_COUNT_OR_TOTAL_SEMANTICS");
if(outgoingCursor!=null){int next=Convert.ToInt32(D(Cad.Json.DeserializeObject(System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(outgoingCursor))))["offset"]);if(outgoingCursor==cursor||next!=incomingOffset+returnedCount||next<=incomingOffset||Convert.ToInt32(page["next_offset"])!=next||Convert.ToInt32(page["next_offset_delta"])!=returnedCount)throw new Exception("REDUCED_CURSOR_SELF_OR_SKIP");}
'''+needle,1)
needle='r["completed"]=true;save();return 0;'
assert needle in code
code=code.replace(needle,r'''
var profiles=new Dictionary<string,object>();
foreach(string key in new[]{"run","verify"}){var output=D(r[key]);string rid=(string)output["run_id"];string folder=Path.Combine(a[0],"runs",rid);var solve=D(Cad.Json.DeserializeObject(File.ReadAllText(Path.Combine(folder,"solve.json"))));var names=D(solve["component_name_resolution"]);double total=Convert.ToDouble(names["total_elapsed_ms"]),sum=new[]{"batch_enter_ms","extension_acquisition_ms","component_loop_ms","batch_restore_ms","other_elapsed_ms"}.Sum(k=>Convert.ToDouble(names[k]));if(Math.Abs(total-sum)>.02||!(bool)D(names["api_batch"])["restored"]||(bool)names["cross_request_cache"])throw new Exception("NAME_TIMING_OR_BATCH_CLOSURE");var axis=D(Cad.Json.DeserializeObject(File.ReadAllText(Path.Combine(folder,"time-axis.json"))));if(!(bool)D(axis["diagnostic"])["verified"]||D(axis["host_timings"])["current_stage"]!=null)throw new Exception("TIME_AXIS_CHILD_TIMING");profiles[key]=new{names=names,time_axis=axis};}
var probe=D(r["checkpoint"]);var proof=D(Cad.Json.DeserializeObject(File.ReadAllText((string)probe["evidence_path"])));if(!(bool)D(D(proof["baseline_read_timings"])["api_batch"])["restored"])throw new Exception("BASELINE_BATCH_RESTORE");var finalState=D(proof["original_state"]);if(!(bool)finalState["verified"]||!(bool)D(finalState["native_api_batch"])["restored"])throw new Exception("FULL_OBSERVATION_OR_BATCH_RESTORE");
profiles["checkpoint"]=proof;r["alpha5_native_profiles"]=profiles;
'''+needle,1)
harness.matrix.CS=code

if __name__=='__main__':harness.main()
