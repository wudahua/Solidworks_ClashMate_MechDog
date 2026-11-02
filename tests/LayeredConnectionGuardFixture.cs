// Development-only fault injection in one freshly imported owned CAD instance.
using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object CheckOuterLayerGuardFixture(string id,string instance) {
        var original=GetUserModel(id);string root=original.Path;
        var selected=SelectConnectionLayer(id,instance);var cp=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(id)));
        var before=VerifyConnectionLayer(id);string changed=null;
        using(var scope=new Scope(this,root,null)) {
            var doc=scope.Doc;var ad=(IAssemblyDoc)doc;
            var component=UserComponents(doc).FirstOrDefault(c=>ConnectionTopLevel(c)&&c.IsFixed());
            if(component==null)throw new Exception("GUARD_FIXTURE_NO_FIXED_ROOT_BODY");
            changed=component.Name2;doc.ClearSelection2(true);
            if(!component.Select4(false,null,false))throw new Exception("GUARD_FIXTURE_SELECT_FAILED");
            ad.UnfixComponent();doc.ClearSelection2(true);
            if(component.IsFixed())throw new Exception("GUARD_FIXTURE_NO_ACTUAL_DISTURBANCE");
        }
        string refused=null;
        try {VerifyConnectionLayer(id);throw new Exception("GUARD_FIXTURE_UNSAFE_CHANGE_ACCEPTED");}
        catch(CadFault error) {refused=error.Code;if(refused!="CONNECTION_EVIDENCE_FAILED")throw;}
        var restored=RestoreUserCheckpoint(id,(string)cp["checkpoint_id"]);
        var after=VerifyConnectionLayer(id);var model=GetUserModel(id);
        VerifyUserSources(model);Sw.CloseAllDocuments(true);
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("GUARD_FIXTURE_CLOSE_UNCONFIRMED");
        return new{passed=true,selection=selected,initial_guard=before,disturbed_non_target_root_instance=changed,
            actual_fixed_flag_disturbance=true,refusal_code=refused,whole_file_checkpoint_restore=restored,final_guard=after,
            original_sources_unchanged=UserSourcesUnchanged(model),source="actual_native_fault_injection_not_mock",force_kill=false};
    }
}
class LayeredConnectionGuardFixtureControl {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        try {using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")) {
            if(!gate.WaitOne(0))throw new Exception("EXECUTOR_ALREADY_RUNNING");
            try {var cad=new Cad(args[0]);if(cad.Sw.GetProcessID()!=int.Parse(args[1]))throw new Exception("OWNED_PID_MISMATCH");
                File.WriteAllText(args[2],Cad.Json.Serialize(cad.CheckOuterLayerGuardFixture(args[3],args[4])));return 0;}
            finally{gate.ReleaseMutex();}
        }}catch(Exception error){Console.Error.WriteLine(error.ToString());return 1;}
    }
}
