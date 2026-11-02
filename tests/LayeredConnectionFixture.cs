// Developer fixture only: wrap an already registered isolated assembly copy.
using System;
using System.IO;
using System.Linq;
using System.Threading;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object WrapConnectionFixture(string modelId,string label,int copies) {
        if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TESTS_DISABLED");
        if(copies<1||copies>2||!System.Text.RegularExpressions.Regex.IsMatch(label,"^[a-z0-9_]{1,24}$"))throw new Exception("FIXTURE_OPTIONS_INVALID");
        var m=GetUserModel(modelId);string inner=m.Path;int error=0,warning=0;
        var child=Sw.OpenDoc6(inner,2,1,"",ref error,ref warning) as IModelDoc2;
        if(child==null)throw new Exception("FIXTURE_INNER_NOT_OPEN");Fingerprint(child,inner);
        int count=UserComponents(child).Length,mates=BasicMateFeatures(child).Length;
        string folder=Path.GetDirectoryName(inner),basePath=Path.Combine(folder,"cm_fixture_base_"+label+".SLDPRT");
        string outerPath=Path.Combine(folder,"cm_outer_"+label+".SLDASM");
        if(File.Exists(basePath)||File.Exists(outerPath))throw new Exception("FIXTURE_ALREADY_EXISTS");
        var baseDoc=New("part");var body=((IModeler)Sw.GetModeler()).CreateBodyFromCyl(new[]{0.0,0,0,0,0,1,.01,.02});
        if(((IPartDoc)baseDoc).CreateFeatureFromBody3(body,false,0)==null)throw new Exception("FIXTURE_BASE_BODY_FAILED");
        Save(baseDoc,basePath);Sw.CloseDoc(baseDoc.GetTitle());
        var outer=New("assembly");RigidFixtureInsert(outer,basePath,Pose(0,0,0,0),true);
        var instance=RigidFixtureInsert(outer,inner,Pose(.1,.2,.05,Math.PI/2),true);
        if(instance.Solving!=0)throw new Exception("FIXTURE_PARENT_MODE_INVALID");
        if(copies==2)RigidFixtureInsert(outer,inner,Pose(.3,.2,.05,Math.PI/2),true);
        if(!outer.EditRebuild3()||BasicMateFeatures(outer).Length!=0)throw new Exception("FIXTURE_OUTER_STATE_INVALID");
        Save(outer,outerPath);var all=UserComponents(outer);
        if(all.Length!=1+copies*(1+count))throw new Exception("FIXTURE_COMPONENT_ACCOUNTING_FAILED");
        var receipt=new{assembly=outerPath,scope_instance=instance.Name2,inner_assembly=inner,scope_components=count,
            initial_internal_mates=mates,copies=copies,outer_mates=0,parent_native_rigid=true,
            outer_poses=all.Select(c=>new{instance=c.Name2,transform=(double[])c.GetTotalTransform(false).ArrayData}).ToArray(),
            developer_fixture=true,user_intent_inferred=false,original_sources_unchanged=UserSourcesUnchanged(m)};
        VerifyUserSources(m);Sw.CloseAllDocuments(true);
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("FIXTURE_CLOSE_NOT_CONFIRMED");
        return receipt;
    }
}
class LayeredConnectionFixtureControl {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        try{using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")) {
            if(!gate.WaitOne(0))throw new Exception("EXECUTOR_ALREADY_RUNNING");
            try{var cad=new Cad(args[0]);if(cad.Sw.GetProcessID()!=int.Parse(args[1]))throw new Exception("OWNED_PID_MISMATCH");
                File.WriteAllText(args[2],Cad.Json.Serialize(cad.WrapConnectionFixture(args[3],args[4],int.Parse(args[5]))));return 0;}
            finally{gate.ReleaseMutex();}
        }}catch(Exception error){Console.Error.WriteLine(error.ToString());return 1;}
    }
}
