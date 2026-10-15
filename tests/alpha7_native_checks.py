"""Owned CAD matrix plus repeated dirty-working-copy / explicit checkpoint probes."""
from pathlib import Path
import sys
import checkpoint_probe_native_checks as matrix

# Reuse the actual mate/rollback/recovery matrix. The same compiled helper acts as
# the isolated child; its explicit branch must precede the interactive lease.
matrix.CS = matrix.CS.replace(
    '[STAThread]static int Main(string[] args){',
    '[STAThread]static int Main(string[] args){if(args.Length==2&&args[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(args[1]);')
matrix.CS = matrix.CS.replace(
    ' public object ProbeTestStates',
    ' public void ProbeTestDirty(string id){using(var s=new Scope(this,GetUserModel(id).Path,null))s.Doc.SetSaveFlag();}\n public object ProbeTestStates')
needle = 'record("positive_motion_preservation_360",motion);'
matrix.CS = matrix.CS.replace(needle, needle + '''
var checkpoint=D(cad.CreateUserCheckpoint(id));string cp=(string)checkpoint["checkpoint_id"];
cad.ProbeTestDirty(id);
try{cad.ProbeUserCompatibility(id,"ProbeVerifiedMotion",1,30,Guid.NewGuid().ToString("N"));throw new Exception("DIRTY_INPUT_WAS_IMPLICITLY_ACCEPTED");}
catch(CadFault e){Require(e.Code=="PROBE_REQUIRES_EXPLICIT_CHECKPOINT","DIRTY_INPUT_WRONG_REFUSAL");record("dirty_without_checkpoint_rejected",e.Diagnostics);}
for(int probeIndex=0;probeIndex<2;probeIndex++){
var probe=D(cad.ProbeUserCompatibility(id,"ProbeVerifiedMotion",1,30,Guid.NewGuid().ToString("N"),cp));
Require((string)probe["solver_compatibility_status"]=="pass"&&(bool)probe["original_copy_unchanged"],"SNAPSHOT_PROBE_FAILED");
record("dirty_snapshot_probe_"+probeIndex,probe);}
''')

if __name__ == '__main__':
    if '--external-change-only' in sys.argv:
        sys.argv.remove('--external-change-only')
        a=matrix.CS.index(' foreach(bool firstLast')
        b=matrix.CS.index(' string template=',a)
        matrix.CS=matrix.CS[:a]+matrix.CS[b:]
        matrix.CS=matrix.CS.replace('new[]{"safe_failure","context_restored","restore_failure","cleanup_failure","post_add_fault","positive"}', 'new[]{"external_change","part_change"}')
        matrix.CS=matrix.CS.replace('if(mode=="safe_failure"&&stage=="before_copy")', 'if(mode=="external_change"&&stage=="after_probe_close"){cad.ProbeTestExternalChange(doc);injected=true;}if(mode=="part_change"&&stage=="after_probe_close"){cad.ProbeTestPartChange(doc);injected=true;} if(mode=="safe_failure"&&stage=="before_copy")')
        matrix.CS=matrix.CS.replace(' public object ProbeTestStates', ' public void ProbeTestPartChange(IModelDoc2 doc){var c=UserComponents(doc).First(v=>!v.IsFixed());var part=(IPartDoc)c.GetModelDoc2();var body=((IModeler)Sw.GetModeler()).CreateBodyFromBox3(new[]{.02,.02,.02,0,0,1,.005,.005,.005});if(part.CreateFeatureFromBody3(body,false,0)==null)throw new Exception("TEST_PART_FEATURE_FAILED");} public void ProbeTestExternalChange(IModelDoc2 doc){var moving=UserComponents(doc).First(c=>!c.IsFixed());if(!moving.Select4(false,null,false))throw new Exception("TEST_SELECTION_FAILED");((IAssemblyDoc)doc).FixComponent();doc.ClearSelection2(true);}\n public object ProbeTestStates')
    matrix.main()
