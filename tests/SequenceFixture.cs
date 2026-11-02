// Developer-only three-document tree with explicit rigid-joint truth.
using System;
using System.IO;
using System.Linq;
using System.Threading;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object BuildSequenceFixture(string id) {
        if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TESTS_DISABLED");
        var m=GetUserModel(id);string inner=m.Path;int error=0,warning=0;
        var child=Sw.OpenDoc6(inner,2,1,"",ref error,ref warning) as IModelDoc2;
        if(child==null||UserComponents(child).Length!=4||BasicMateFeatures(child).Length!=0)
            throw new Exception("SEQUENCE_FIXTURE_INPUT_TRUTH_FAILED");
        string folder=Path.GetDirectoryName(inner),basePath=Path.Combine(folder,"outer_base.SLDPRT");
        string root=Path.Combine(folder,"sequence_root.SLDASM");
        if(File.Exists(basePath)||File.Exists(root))throw new Exception("SEQUENCE_FIXTURE_EXISTS");
        var part=New("part");var body=((IModeler)Sw.GetModeler()).CreateBodyFromCyl(new[]{0.0,0,0,0,0,1,.01,.02});
        if(((IPartDoc)part).CreateFeatureFromBody3(body,false,0)==null)throw new Exception("SEQUENCE_BODY_FAILED");
        Save(part,basePath);Sw.CloseDoc(part.GetTitle());
        var outer=New("assembly");RigidFixtureInsert(outer,basePath,Pose(0,0,0,0),true);
        var moving=RigidFixtureInsert(outer,inner,Pose(.1,.2,.05,Math.PI/2),false);
        if(moving.Solving!=0||moving.IsFixed()||!outer.EditRebuild3()||BasicMateFeatures(outer).Length!=0)
            throw new Exception("SEQUENCE_ROOT_TRUTH_FAILED");
        Save(outer,root);var all=UserComponents(outer);
        if(all.Length!=6)throw new Exception("SEQUENCE_ACCOUNTING_FAILED");
        var descendants=all.Where(c=>(c.GetModelDoc2() as IModelDoc2).GetType()==2).ToArray();
        if(descendants.Length!=2||descendants.Any(c=>c.Solving!=0))throw new Exception("SEQUENCE_LAYERS_FAILED");
        var truth=new{assembly=root,root_target=moving.Name2,root_reference="outer_base-1",document_count=3,components=6,
            scope_instances=descendants.Select(c=>c.Name2).OrderBy(n=>n).ToArray(),
            hierarchy=all.Select(c=>new{instance=c.Name2,transform=(double[])c.GetTotalTransform(false).ArrayData}).ToArray(),
            initial_total_mates=0,expected_total_added=9,expected_bounded_trials=18,
            developer_fixture=true,real_user_multilayer_model=false,original_sources_unchanged=UserSourcesUnchanged(m)};
        VerifyUserSources(m);Sw.CloseAllDocuments(true);
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("SEQUENCE_DOCUMENT_CLOSE_FAILED");
        return truth;
    }
}
class SequenceFixtureControl {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        try{using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")) {
            if(!gate.WaitOne(0))throw new Exception("EXECUTOR_ALREADY_RUNNING");
            try{var cad=new Cad(args[0]);if(cad.Sw.GetProcessID()!=int.Parse(args[1]))throw new Exception("OWNED_PID_MISMATCH");
                File.WriteAllText(args[2],Cad.Json.Serialize(cad.BuildSequenceFixture(args[3])));return 0;}
            finally{gate.ReleaseMutex();}
        }}catch(Exception error){Console.Error.WriteLine(error.ToString());return 1;}
    }
}
