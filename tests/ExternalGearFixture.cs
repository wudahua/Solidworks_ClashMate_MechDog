// Development-only source. The fixture declares trial ratio weights, never
// measured tooth counts. Only copied parts and generated reference anchors save.
using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public partial class Cad {
    double[] EGFixturePose(double[] from,double[] to,double[] point,double[] target) {
        from=from.Select(v=>v/Math.Sqrt(from.Sum(x=>x*x))).ToArray();to=to.Select(v=>v/Math.Sqrt(to.Sum(x=>x*x))).ToArray();
        double c=GTDot(from,to);var cross=new[]{from[1]*to[2]-from[2]*to[1],from[2]*to[0]-from[0]*to[2],from[0]*to[1]-from[1]*to[0]};
        double[,] r=new double[3,3];
        if(c<-.999999){var axis=Math.Abs(from[0])<.9?new[]{1.0,0,0}:new[]{0.0,1,0};cross=new[]{from[1]*axis[2]-from[2]*axis[1],from[2]*axis[0]-from[0]*axis[2],from[0]*axis[1]-from[1]*axis[0]};double n=Math.Sqrt(cross.Sum(v=>v*v));cross=cross.Select(v=>v/n).ToArray();for(int i=0;i<3;i++)for(int j=0;j<3;j++)r[i,j]=2*cross[i]*cross[j]-(i==j?1:0);}
        else {double[,] k={{0,-cross[2],cross[1]},{cross[2],0,-cross[0]},{-cross[1],cross[0],0}};for(int i=0;i<3;i++)for(int j=0;j<3;j++){double square=0;for(int a=0;a<3;a++)square+=k[i,a]*k[a,j];r[i,j]=(i==j?1:0)+k[i,j]+square/(1+c);}}
        var pose=Pose(0,0,0,0);for(int i=0;i<3;i++)for(int j=0;j<3;j++)pose[i*3+j]=r[j,i];
        var shifted=ApplyPose(pose,point,true);for(int i=0;i<3;i++)pose[9+i]=target[i]-shifted[i];return pose;
    }
    public object BuildExternalGearFixture(string originals,bool partial) {
        string folder=Path.Combine(Root,"fixtures",partial?"external_pair_partial":"external_pair_empty");if(Directory.Exists(folder))throw new Exception("FIXTURE_ALREADY_EXISTS");Directory.CreateDirectory(folder);
        var mapping=new Dictionary<string,string>{{"rotor_A", "齿轮轴.SLDPRT"},{"rotor_B","大轴.SLDPRT"},{"wheel_B","大齿轮.SLDPRT"}};
        var sourceHashes=mapping.Values.ToDictionary(n=>Path.Combine(originals,n),n=>FileHash(Path.Combine(originals,n)));
        foreach(var row in mapping) {
            string path=Path.Combine(folder,row.Key+".SLDPRT");File.Copy(Path.Combine(originals,row.Value),path);File.SetAttributes(path,FileAttributes.Normal);
            if(DiskDependencies(path,true).Length!=0)throw new Exception("FIXTURE_SOURCE_PART_EXTERNAL_DEPENDENCIES");
            int e=0,w=0;var doc=Sw.OpenDoc6(path,1,1,"",ref e,ref w) as IModelDoc2;if(doc==null||e!=0||!doc.GetPathName().Equals(path,StringComparison.OrdinalIgnoreCase))throw new Exception("FIXTURE_COPY_OPEN_FAILED");
            doc.Extension.ToolboxPartType=0;
            if(row.Key!="rotor_B")doc.Extension.CustomPropertyManager[""].Add3("ClashMateTrialTeeth",(int)swCustomInfoType_e.swCustomInfoNumber,row.Key=="rotor_A"?"20":"40",(int)swCustomPropertyAddOption_e.swCustomPropertyDeleteAndAdd);
            Save(doc,path);Sw.CloseDoc(doc.GetTitle());
        }
        foreach(string name in new[]{"anchor_A","anchor_B"}) {
            var doc=New("part");var body=((IModeler)Sw.GetModeler()).CreateBodyFromCyl(new[]{0.0,-.04,0,0,1,0,.02,.01});
            if(((IPartDoc)doc).CreateFeatureFromBody3(body,false,0)==null)throw new Exception("FIXTURE_ANCHOR_FAILED");
            Save(doc,Path.Combine(folder,name+".SLDPRT"));Sw.CloseDoc(doc.GetTitle());
        }
        var asm=New("assembly");var ad=(IAssemblyDoc)asm;var cs=new Dictionary<string,IComponent2>();
        foreach(string name in new[]{"anchor_A","anchor_B","rotor_A","rotor_B","wheel_B"}) {
            string path=Path.Combine(folder,name+".SLDPRT");int e=0,w=0;Sw.OpenDoc6(path,1,1,"",ref e,ref w);Sw.ActivateDoc3(asm.GetTitle(),false,0,ref e);
            var c=ad.AddComponent5(path,0,"",false,"",0,0,0) as IComponent2;if(c==null)throw new Exception("FIXTURE_INSERT_FAILED");cs[name]=c;
            asm.ClearSelection2(true);c.Select4(false,null,false);if(name.StartsWith("anchor"))ad.FixComponent();else ad.UnfixComponent();asm.ClearSelection2(true);
            if(name.StartsWith("anchor"))c.Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(Pose(name=="anchor_A"?0:.2,0,0,0));
            else {
                // AddComponent5 can insert with a nonidentity transform even
                // at xyz=0. Assign an absolute pose from native PART coordinates,
                // rather than applying a world-space delta as an absolute pose.
                var face=GTCylinder(asm,c);var parameters=(double[])((ISurface)face.GetSurface()).CylinderParams;
                var axis=parameters.Skip(3).Take(3).ToArray();var point=parameters.Take(3).ToArray();
                c.Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(EGFixturePose(axis,new[]{0.0,1,0},point,new[]{name=="rotor_A"?0:.2,0,0}));
            }
        }
        // Fixing before transform can ignore assignments. Reassert anchor poses
        // while floating, then ground them, with no mate-driven repositioning.
        foreach(string name in new[]{"anchor_A","anchor_B"}) {asm.ClearSelection2(true);cs[name].Select4(false,null,false);ad.UnfixComponent();cs[name].Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(Pose(name=="anchor_A"?0:.2,0,0,0));cs[name].Select4(false,null,false);ad.FixComponent();asm.ClearSelection2(true);}
        if(partial) {
            var p=new TransmissionPlan{References=new Dictionary<string,string>(),Axis=new[]{0.0,1,0},AxialDistances=new double[2]};
            foreach(string side in new[]{"input","output"}) {
                var a=cs[side=="input"?"rotor_A":"wheel_B"];var b=cs[side=="input"?"anchor_A":"rotor_B"];
                var fa=GTCylinder(asm,a);var fb=GTCylinder(asm,b);var pa=GTPlane(asm,a,p.Axis);var pb=GTPlane(asm,b,p.Axis);
                p.References[side+"_axis"]=GTReference(asm,fa);p.References[side+"_support"]=GTReference(asm,fb);p.References[side+"_plane"]=GTReference(asm,pa);p.References[side+"_body_plane"]=GTReference(asm,pb);
                int i=side=="input"?0:1;p.AxialDistances[i]=Math.Abs(GTDot(GTSub((double[])MateGeometry(asm,pa,a)["reference_point_global_m"],(double[])MateGeometry(asm,pb,b)["reference_point_global_m"]),p.Axis));GTShaftSupport(asm,a,p,side,i);
            }
        }
        if(!asm.EditRebuild3())throw new Exception("FIXTURE_REBUILD_FAILED");RequireMatesHealthy(asm);string assembly=Path.Combine(folder,"external_pair.SLDASM");Save(asm,assembly);
        foreach(var hash in sourceHashes)if(FileHash(hash.Key)!=hash.Value)throw new Exception("FIXTURE_ORIGINAL_CHANGED");
        var result=new{assembly=assembly,partial_existing_mates=partial,initial_mates=BasicMateFeatures(asm).Length,components=5,
            source_hashes=sourceHashes,trial_ratio_weights=new[]{20,40},measured_tooth_counts=false,
            contact_geometry_validated=false,description="Real reducer gear/shaft part copies, generated fixed cylindrical axis references, declared 1:2 trial ratio; not a physical mesh/contact model"};
        File.WriteAllText(Path.Combine(folder,"fixture.json"),Json.Serialize(result));return result;
    }
}

class ExternalGearFixtureControl {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        try {using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")) {
            if(!gate.WaitOne(0))throw new Exception("EXECUTOR_ALREADY_RUNNING");
            try {var cad=new Cad(args[0]);int pid=int.Parse(args[1]);if(cad.Sw.GetProcessID()!=pid)throw new Exception("OWNED_PID_MISMATCH");
                var result=cad.BuildExternalGearFixture(args[2],bool.Parse(args[3]));File.WriteAllText(args[4],Cad.Json.Serialize(result));return 0;
            }finally{gate.ReleaseMutex();}}
        }catch(Exception error){Console.Error.WriteLine(error.ToString());return 1;}
    }
}
