"""Owned-instance acceptance for the matched six-component slider fixture.

Requires Part10 / Part5 planar references and Part6 rotary input, as in the
existing performance fixture. --source must name its saved source assembly.
Creates isolated copies only. Never connects to the user's original CAD.
"""
import json
import v043a0_timing_native as timing

harness=timing.harness
signature=r'''
public partial class Cad {
 public object ProbeTestSignatureIdentity(string id){var m=GetUserModel(id);using(var scope=new Scope(this,m.Path,null)){var doc=scope.Doc;bool previous=Sw.CommandInProgress;
 // Alpha.2 observation is an independent compatibility oracle: all original
 // signature members remain present, including unrelated components/mates.
 var loaded=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Where(d=>m.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)).OrderBy(d=>d.GetPathName(),StringComparer.OrdinalIgnoreCase).Select(d=>new{path=d.GetPathName(),stamp=d.GetUpdateStamp(),dirty=d.GetSaveFlag()}).ToArray();
 string legacy=StableId("state_",Json.Serialize(new{revision=m.Revision,configuration=doc.ConfigurationManager.ActiveConfiguration.Name,files=m.Files.ToDictionary(p=>p,p=>FileHash(p)),documents=loaded,poses=Transforms(doc),studies=StudyStates(doc),mates=ProbeWorkingState.MateIdentity(doc),mate_health=ProbeWorkingState.MateHealthIdentity(doc),component_identity=ProbeWorkingState.ComponentIdentity(doc)}));
 object profile;string actual=MateSignature(m,doc,out profile);if(legacy!=actual||Sw.CommandInProgress!=previous)throw new Exception("SIGNATURE_COMPATIBILITY_OR_BATCH_STATE_FAILED");
 string changed;try{m.Revision++;changed=MateSignature(m,doc);}finally{m.Revision--;}if(changed==actual)throw new Exception("SIGNATURE_REVISION_GUARD_LOST");
 return new{legacy_signature_equal=true,revision_change_rejected=true,command_flag_restored=Sw.CommandInProgress==previous,timing=profile};}}
}
'''
harness.matrix.CS=harness.matrix.CS.replace('class ProbeAcceptance {',signature+'class ProbeAcceptance {',1)
extra=r'''
r["signature_compatibility"]=cad.ProbeTestSignatureIdentity(id);
bool batchFlag=cad.Sw.CommandInProgress;
var full=D(cad.ListMateReferences(id,"","",50,null,false,0,20));r["full_context"]=full;
var compact=D(cad.ListMateReferences(id,"","",50,null,true,0,20));r["compact_context"]=compact;
foreach(var q in new[]{full,compact}){var context=D(q["mate_context_scan"]);if(Convert.ToInt32(context["cooperative_budget_ms"])!=20000||!(bool)context["enumeration_complete"]||Convert.ToInt32(context["total_mate_count"])!=13||(bool)q["mate_context_complete"]!=(Convert.ToInt32(context["unresolved_reference_count"])==0))throw new Exception("FULL_MATE_ENUMERATION_OR_REFERENCE_STATUS_INCORRECT");if(!(bool)q["mate_context_complete"]&&q["mate_context_warning"]==null)throw new Exception("PARTIAL_REFERENCE_WARNING_MISSING");}
if(cad.Sw.CommandInProgress!=batchFlag)throw new Exception("CONTEXT_COMMAND_FLAG_NOT_RESTORED");
Func<string,Dictionary<string,object>> plane=name=>{var c=components.Single(e=>((string)e["instance"]).IndexOf(name,StringComparison.OrdinalIgnoreCase)>=0);var rows=Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(D(cad.ListMateReferences(id,(string)c["component_id"],"planar_normal",50,null,true,0,20))["entities"]));return rows.First(e=>Math.Abs(((System.Collections.IEnumerable)e["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last())>.99);};
var pa=plane("Part10");var pb=plane("Part5");double za=((System.Collections.IEnumerable)pa["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last(),zb=((System.Collections.IEnumerable)pb["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last();
var plan=D(cad.PreviewBasicMate(id,(string)pa["entity_id"],(string)pb["entity_id"],"parallel",za*zb>0?"aligned":"anti_aligned",0,false,""));timer.Restart();r["apply"]=cad.ApplyBasicMate((string)plan["plan_id"],true);r["apply_ms"]=timer.ElapsedMilliseconds;
var execution=D(D(r["apply"])["execution"]);var admission=D(execution["admission_timing"]);var profile=D(execution["plan_signature_timing"]);
if(((System.Collections.IEnumerable)admission["phases"]).Cast<object>().Count()!=9||((System.Collections.IEnumerable)profile["phases"]).Cast<object>().Count()<9||profile["current_stage"]!=null)throw new Exception("ADMISSION_SIGNATURE_TIMING_NOT_COMPLETE");
r["admission_timing_verified"]=admission;r["signature_timing_verified"]=profile;save();
'''
needle='var component=components.Single'
assert needle in harness.matrix.CS
harness.matrix.CS=harness.matrix.CS.replace(needle,extra+needle,1)

if __name__=='__main__':
    report=harness.main()
    if report:print(json.dumps({'accepted':True,'directory':report['directory']}),flush=True)
