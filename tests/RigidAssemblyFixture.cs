// Developer-only nested truth fixture, not a user design or distributed CAD.
using System;
using System.IO;
using System.Linq;
using System.Threading;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    IComponent2 RigidFixtureInsert(IModelDoc2 assembly,string path,double[] pose,bool fixedState) {
        int error=0,warning=0;
        Sw.OpenDoc6(path,path.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase)?2:1,1,"",ref error,ref warning);
        Sw.ActivateDoc3(assembly.GetTitle(),false,0,ref error);
        var ad=(IAssemblyDoc)assembly;var c=ad.AddComponent5(path,0,"",false,"",0,0,0) as IComponent2;
        if(c==null)throw new Exception("RIGID_FIXTURE_INSERT_FAILED");
        assembly.ClearSelection2(true);if(!c.Select4(false,null,false))throw new Exception("RIGID_FIXTURE_SELECTION_FAILED");
        ad.UnfixComponent();assembly.ClearSelection2(true);
        c.Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(pose);
        if(fixedState){if(!c.Select4(false,null,false))throw new Exception("RIGID_FIXTURE_FIX_SELECTION_FAILED");ad.FixComponent();assembly.ClearSelection2(true);}
        if(c.IsFixed()!=fixedState||!PoseValidation.Matches(pose,(double[])c.GetTotalTransform(false).ArrayData))throw new Exception("RIGID_FIXTURE_PLACEMENT_FAILED");
        return c;
    }
    public object BuildRigidAssemblyFixture(bool internalLock=false) {
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("RIGID_FIXTURE_REQUIRES_EMPTY_OWNED_CAD");
        string folder=Path.Combine(Root,"fixtures","rigid_tree");if(Directory.Exists(folder))throw new Exception("RIGID_FIXTURE_ALREADY_EXISTS");Directory.CreateDirectory(folder);
        foreach(string name in new[]{"base","shaft","marker"}) {
            var part=New("part");var body=((IModeler)Sw.GetModeler()).CreateBodyFromCyl(new[]{0.0,0,0,0,0,1,.01,.02});
            if(((IPartDoc)part).CreateFeatureFromBody3(body,false,0)==null)throw new Exception("RIGID_FIXTURE_BODY_FAILED");
            Save(part,Path.Combine(folder,name+".SLDPRT"));Sw.CloseDoc(part.GetTitle());
        }
        var inner=New("assembly");
        var innerShaft=RigidFixtureInsert(inner,Path.Combine(folder,"shaft.SLDPRT"),Pose(0,0,0,0),true);
        var innerMarker=RigidFixtureInsert(inner,Path.Combine(folder,"marker.SLDPRT"),Pose(.04,0,.03,0),false);
        if(internalLock)LockPair(inner,innerShaft,innerMarker);
        if(!inner.EditRebuild3()||BasicMateFeatures(inner).Length!=(internalLock?1:0))throw new Exception("RIGID_FIXTURE_INNER_STATE_FAILED");
        RequireMatesHealthy(inner);
        string carrier=Path.Combine(folder,"carrier.SLDASM");Save(inner,carrier);Sw.CloseAllDocuments(true);
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("RIGID_FIXTURE_INNER_CLOSE_FAILED");
        var outer=New("assembly");RigidFixtureInsert(outer,Path.Combine(folder,"base.SLDPRT"),Pose(0,0,0,0),true);
        var moving=RigidFixtureInsert(outer,carrier,Pose(0,0,.05,Math.PI/2),false);
        if(moving.Solving!=0)throw new Exception("RIGID_FIXTURE_NOT_NATIVE_RIGID");
        if(!outer.EditRebuild3()||BasicMateFeatures(outer).Length!=0)throw new Exception("RIGID_FIXTURE_OUTER_STATE_FAILED");
        string source=Path.Combine(folder,"rigid_tree.SLDASM");Save(outer,source);
        var all=UserComponents(outer);if(all.Length!=4)throw new Exception("RIGID_FIXTURE_HIERARCHY_COUNT_FAILED");
        var shaft=all.Single(c=>c.Name2.EndsWith("/shaft-1",StringComparison.Ordinal));
        var marker=all.Single(c=>c.Name2.EndsWith("/marker-1",StringComparison.Ordinal));
        var owning=moving.GetModelDoc2() as IModelDoc2;
        if(owning==null||owning.ConfigurationManager.ActiveConfiguration.Name!=moving.ReferencedConfiguration)throw new Exception("RIGID_FIXTURE_OWNING_CONFIGURATION_FAILED");
        var local=(((IAssemblyDoc)owning).GetComponents(true) as object[]??new object[0]).Cast<IComponent2>().ToDictionary(c=>c.Name2,StringComparer.Ordinal);
        if(!local["shaft-1"].IsFixed()||local["marker-1"].IsFixed()||moving.IsFixed()||shaft.IsFixed()||marker.IsFixed())throw new Exception("RIGID_FIXTURE_FIXED_FRAME_TRUTH_FAILED");
        if(!PoseValidation.Matches(Pose(0,0,.05,Math.PI/2),(double[])moving.GetTotalTransform(false).ArrayData)||
           !PoseValidation.Matches(Pose(0,0,.05,Math.PI/2),(double[])shaft.GetTotalTransform(false).ArrayData)||
           !PoseValidation.Matches(Pose(0,.04,.08,Math.PI/2),(double[])marker.GetTotalTransform(false).ArrayData))throw new Exception("RIGID_FIXTURE_ROOT_CONTEXT_POSE_TRUTH_FAILED");
        var receipt=new{assembly=source,components=4,initial_root_mates=0,initial_internal_mates=internalLock?1:0,root_target=moving.Name2,root_reference="base-1",
            native_rigid_solving=moving.Solving,root_target_fixed=false,fixed_child=shaft.Name2,floating_child=marker.Name2,
            owning_document_fixed_flags=local.Select(c=>new{instance=c.Key,fixed_component=c.Value.IsFixed()}).ToArray(),
            root_context_child_fixed_flags=new[]{new{instance=shaft.Name2,fixed_component=shaft.IsFixed()},new{instance=marker.Name2,fixed_component=marker.IsFixed()}},
            initial_root_pose=Pose(0,0,.05,Math.PI/2),local_child_poses=new[]{new{instance="shaft-1",pose=Pose(0,0,0,0)},new{instance="marker-1",pose=Pose(.04,0,.03,0)}},
            hierarchy=all.Select(c=>new{instance=c.Name2,fixed_component=c.IsFixed(),parent=(c.GetParent() as IComponent2)==null?null:((IComponent2)c.GetParent()).Name2,transform=(double[])c.GetTotalTransform(false).ArrayData}).ToArray(),
            scope="generated_native_truth_not_user_intent_no_CAD_distribution"};
        Sw.CloseAllDocuments(true);if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("RIGID_FIXTURE_FINAL_CLOSE_FAILED");
        return receipt;
    }
}
class RigidAssemblyFixtureControl {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        try{using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")) {
            if(!gate.WaitOne(0))throw new Exception("EXECUTOR_ALREADY_RUNNING");
            try{var cad=new Cad(args[0]);if(cad.Sw.GetProcessID()!=int.Parse(args[1]))throw new Exception("OWNED_PID_MISMATCH");File.WriteAllText(args[2],Cad.Json.Serialize(cad.BuildRigidAssemblyFixture(args.Length>3&&args[3]=="internal-lock")));return 0;}
            finally{gate.ReleaseMutex();}
        }}catch(Exception error){Console.Error.WriteLine(error.ToString());return 1;}
    }
}
