// Development-only native fixture. No user CAD is loaded or distributed.
using System;
using System.IO;
using System.Linq;
using System.Threading;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object BuildBasicConnectionFixture() {
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("FIXTURE_REQUIRES_EMPTY_OWNED_CAD");
        string folder=Path.Combine(Root,"fixtures","basic_joint");
        if(Directory.Exists(folder))throw new Exception("FIXTURE_ALREADY_EXISTS");Directory.CreateDirectory(folder);
        foreach(string name in new[]{"base","moving"}) {
            var doc=New("part");var body=((IModeler)Sw.GetModeler()).CreateBodyFromCyl(new[]{0.0,0,0,0,0,1,.01,.02});
            if(((IPartDoc)doc).CreateFeatureFromBody3(body,false,0)==null)throw new Exception("FIXTURE_BODY_FAILED");
            Save(doc,Path.Combine(folder,name+".SLDPRT"));Sw.CloseDoc(doc.GetTitle());
        }
        var asm=New("assembly");var ad=(IAssemblyDoc)asm;
        foreach(string name in new[]{"base","moving"}) {
            string path=Path.Combine(folder,name+".SLDPRT");int error=0,warning=0;
            Sw.OpenDoc6(path,1,1,"",ref error,ref warning);Sw.ActivateDoc3(asm.GetTitle(),false,0,ref error);
            var component=ad.AddComponent5(path,0,"",false,"",0,0,0) as IComponent2;
            if(component==null)throw new Exception("FIXTURE_INSERT_FAILED");
            asm.ClearSelection2(true);component.Select4(false,null,false);ad.UnfixComponent();asm.ClearSelection2(true);
            var pose=Pose(0,0,name=="base"?0:.05,0);component.Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(pose);
            if(name=="base"){component.Select4(false,null,false);ad.FixComponent();asm.ClearSelection2(true);}
            if(!PoseValidation.Matches(pose,(double[])component.GetTotalTransform(false).ArrayData)||component.IsFixed()!=(name=="base"))throw new Exception("FIXTURE_POSE_OR_FIXED_STATE_FAILED");
        }
        if(!asm.EditRebuild3()||BasicMateFeatures(asm).Length!=0)throw new Exception("FIXTURE_INITIAL_STATE_FAILED");
        string assembly=Path.Combine(folder,"basic_joint.SLDASM");Save(asm,assembly);
        var receipt=new{assembly=assembly,components=2,initial_mates=0,base_fixed=true,moving_floating=true,
            initial_relative_rotation="identity",initial_axis="global_Z",initial_axial_offset_m=.05,
            geometry="two_native_cylinders_with_default_datum_planes",source="generated_test_truth_not_user_design_intent",contact_validated=false};
        Sw.CloseAllDocuments(true);if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("FIXTURE_DOCUMENT_CLOSE_UNCONFIRMED");
        return receipt;
    }
}

class BasicConnectionFixtureControl {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        try {using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")) {
            if(!gate.WaitOne(0))throw new Exception("EXECUTOR_ALREADY_RUNNING");
            try {var cad=new Cad(args[0]);if(cad.Sw.GetProcessID()!=int.Parse(args[1]))throw new Exception("OWNED_PID_MISMATCH");
                File.WriteAllText(args[2],Cad.Json.Serialize(cad.BuildBasicConnectionFixture()));return 0;
            }finally{gate.ReleaseMutex();}}
        }catch(Exception error){Console.Error.WriteLine(error.ToString());return 1;}
    }
}
