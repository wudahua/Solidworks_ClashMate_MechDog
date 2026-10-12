using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text.RegularExpressions;
using System.Windows.Forms;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    public readonly ISldWorks Sw;
    public readonly string Root;
    public string LastOperationRestoration="not_required";
    public static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 16777216 };
    const string Tutorial = @"C:\Users\Public\Documents\SOLIDWORKS\SOLIDWORKS 2026\samples\tutorial\advdrawings\";
    [DllImport("ole32.dll")]static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
    [DllImport("ole32.dll")]static extern int CreateBindCtx(int reserved,out IBindCtx context);
    static ISldWorks ConnectSession(){
        IRunningObjectTable rot;Marshal.ThrowExceptionForHR(GetRunningObjectTable(0,out rot));IBindCtx context;Marshal.ThrowExceptionForHR(CreateBindCtx(0,out context));IEnumMoniker list;rot.EnumRunning(out list);
        var available=new Dictionary<int,IMoniker>();var m=new IMoniker[1];while(list.Next(1,m,IntPtr.Zero)==0){string name;m[0].GetDisplayName(context,null,out name);var match=Regex.Match(name,"^SolidWorks_PID_([0-9]+)$");if(match.Success)available[int.Parse(match.Groups[1].Value)]=m[0];}
        string selected=System.Environment.GetEnvironmentVariable("SW_MCP_PROCESS_ID");int pid;
        if(!string.IsNullOrEmpty(selected)){if(!int.TryParse(selected,out pid)||!available.ContainsKey(pid))throw new Exception("COM_SESSION_NOT_FOUND: configured SW_MCP_PROCESS_ID is not registered");}
        else{if(available.Count==0)throw new Exception("COM_SESSION_NOT_FOUND");if(available.Count!=1)throw new Exception("AMBIGUOUS_COM_SESSION: set SW_MCP_PROCESS_ID; available="+string.Join(",",available.Keys));pid=available.Keys.First();}
        object result;rot.GetObject(available[pid],out result);var sw=result as ISldWorks;if(sw==null)throw new Exception("COM_SESSION_UNAVAILABLE");if(sw.GetProcessID()!=pid)throw new Exception("COM_SESSION_ID_MISMATCH");Log("COM_CONNECTED pid="+pid);return sw;
    }
    public Cad(string root) {Root=Path.GetFullPath(root);Sw=ConnectSession();bool prior=Sw.UserControl;if(!prior)Sw.UserControl=true;if(!Sw.UserControl)throw new Exception("SESSION_LIFETIME_UNVERIFIED");Log("SESSION_LIFETIME user_control_before="+prior+" after="+Sw.UserControl);LoadRegistrations();}
    public static void Log(string text) { Console.Error.WriteLine(DateTime.UtcNow.ToString("o")+" "+text); }
    public string Fixture { get { return Path.Combine(Root,"fixtures","slider_crank"); } }
    void Save(IModelDoc2 d,string path) { int e=0,w=0; if(!d.Extension.SaveAs(path,0,1,null,ref e,ref w)||e!=0) throw new Exception("SAVE_FAILED "+e); }
    IModelDoc2 New(string ext) { var d=(IModelDoc2)Sw.NewDocument(Tutorial+(ext=="part"?"part.prtdot":"assembly.asmdot"),0,0,0); if(d==null) throw new Exception("TEMPLATE_UNAVAILABLE"); return d; }
    void Part(string name, double[][] boxes, double[][] cylinders) {
        string path=Path.Combine(Fixture,name+".sldprt"); if(File.Exists(path)) { int e=0,w=0; if(Sw.OpenDoc6(path,1,1,"",ref e,ref w)==null) throw new Exception("FIXTURE_PART_OPEN_FAILED"); return; }
        var d=New("part"); var p=(IPartDoc)d; var m=(IModeler)Sw.GetModeler();
        foreach(var box in boxes) if(p.CreateFeatureFromBody3(m.CreateBodyFromBox3(box),false,0)==null) throw new Exception("BODY_CREATE_FAILED");
        foreach(var cyl in cylinders) if(p.CreateFeatureFromBody3(m.CreateBodyFromCyl(cyl),false,0)==null) throw new Exception("CYLINDER_CREATE_FAILED");
        Save(d,path);
    }
    public static double[] Pose(double x,double y,double z,double angle) { double c=Math.Cos(angle),s=Math.Sin(angle); return new[]{c,s,0,-s,c,0,0,0,1,x,y,z,1,0,0,0}; }
    IComponent2 Insert(IAssemblyDoc ad,string name,double[] pose) {
        var c=(IComponent2)ad.AddComponent5(Path.Combine(Fixture,name+".sldprt"),0,"",false,"",pose[9],pose[10],pose[11]);
        if(c==null) throw new Exception("INSERT_FAILED "+name);
        c.Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(pose); return c;
    }
    static IEnumerable<IFace2> Faces(IComponent2 c) { object info; var bodies=c.GetBodies3(0,out info) as object[]; if(bodies==null) throw new Exception("UNRESOLVED_COMPONENT"); return bodies.Cast<IBody2>().SelectMany(b=>((object[])b.GetFaces()).Cast<IFace2>()); }
    static IFace2 Cylinder(IComponent2 c,double localX) { return Faces(c).First(f=>{var s=(ISurface)f.GetSurface(); return s.IsCylinder() && Math.Abs(((double[])s.CylinderParams)[0]-localX)<1e-6;}); }
    void Concentric(IModelDoc2 doc,IComponent2 a,double ax,IComponent2 b,double bx,string label) {
        doc.ClearSelection2(true);
        var sd=((ISelectionMgr)doc.SelectionManager).CreateSelectData(); sd.Mark=1;
        if(!((IEntity)Cylinder(a,ax)).Select4(false,sd)||!((IEntity)Cylinder(b,bx)).Select4(true,sd)) throw new Exception("MATE_SELECTION_FAILED "+label);
        AddMate(doc,1,label);
    }
    void PlaneMate(IModelDoc2 doc,IComponent2 a,IComponent2 b,string plane,string label) {
        doc.ClearSelection2(true);
        string sa=plane+"@"+a.GetSelectByIDString(), sb=plane+"@"+b.GetSelectByIDString();
        Log("PLANE_SELECT "+sa+" | "+sb);
        if(!doc.Extension.SelectByID2(sa,"PLANE",0,0,0,false,1,null,0)||!doc.Extension.SelectByID2(sb,"PLANE",0,0,0,true,1,null,0)) throw new Exception("PLANE_SELECTION_FAILED "+label);
        AddMate(doc,0,label);
    }
    void AddMate(IModelDoc2 doc,int type,string label) {
        int error; var mate=((IAssemblyDoc)doc).AddMate5(type,0,false,0,0,0,1,1,0,0,0,false,false,0,out error);
        Log("MATE "+label+" error="+error+" created="+(mate!=null));
        if(mate==null||error!=(int)swAddMateError_e.swAddMateError_NoError) throw new Exception("MATE_FAILED "+label+" "+error);
        doc.ClearSelection2(true);
    }
    public object BuildFixture() {
        Directory.CreateDirectory(Fixture);
        Part("base",new[]{new[]{.05,-.025,-.015,0.0,0,1,.14,.012,.006}},new[]{new[]{0.0,0,0,0,0,1,.003,.004}});
        Part("crank",new[]{new[]{.01,0,0,0.0,0,1,.02,.006,.004}},new[]{new[]{0.0,0,-.004,0,0,1,.003,.008},new[]{.02,0,0,0.0,0,1,.003,.012}});
        Part("rod",new[]{new[]{.04,0,.008,0.0,0,1,.08,.004,.004}},new[]{new[]{0.0,0,.004,0,0,1,.003,.012},new[]{.08,0,.008,0.0,0,1,.003,.012}});
        Part("slider",new[]{new[]{0.0,0,.016,0,0,1,.014,.012,.006}},new[]{new[]{0.0,0,.01,0,0,1,.003,.014}});
        Part("obstacle",new[]{new[]{0.0,0,.016,0,0,1,.006,.01,.006}},new double[0][]);
        var doc=New("assembly"); var ad=(IAssemblyDoc)doc;
        double theta=Math.PI/6,phi=-Math.Asin(.02/.08*Math.Sin(theta));
        double sx=.02*Math.Cos(theta)+Math.Sqrt(.08*.08-.02*.02*Math.Sin(theta)*Math.Sin(theta));
        var basis=Insert(ad,"base",Pose(0,0,0,0));
        var crank=Insert(ad,"crank",Pose(0,0,0,theta));
        var rod=Insert(ad,"rod",Pose(.02*Math.Cos(theta),.02*Math.Sin(theta),0,phi));
        var slider=Insert(ad,"slider",Pose(sx,0,0,0));
        Concentric(doc,basis,0,crank,0,"base_crank_axis"); PlaneMate(doc,basis,crank,"Front Plane","base_crank_plane");
        Concentric(doc,crank,.02,rod,0,"crank_rod_axis"); PlaneMate(doc,crank,rod,"Front Plane","crank_rod_plane");
        PlaneMate(doc,basis,slider,"Front Plane","slider_z"); PlaneMate(doc,basis,slider,"Top Plane","slider_y_orientation");
        Concentric(doc,rod,.08,slider,0,"rod_slider_axis");
        if(!doc.EditRebuild3()) throw new Exception("FIXTURE_REBUILD_FAILED");
        var mgr=(IMotionStudyManager)doc.Extension.GetMotionStudyManager(); var study=(IMotionStudy)mgr.CreateMotionStudy();
        study.Name="MVP_60rpm"; study.Activate(); study.StudyType=4; if(study.StudyType!=4) throw new Exception("MOTION_LICENSE_UNAVAILABLE");
        var motor=(ISimulationMotorFeatureData)study.CreateDefinition(78); var face=Cylinder(crank,0);
        motor.DirectionReference=face; motor.Location=face; motor.ConstantSpeedMotor(2*Math.PI);
        if(study.CreateFeature(motor)==null) throw new Exception("MOTOR_CREATE_FAILED");
        study.SetDuration(1); ((IMotionStudyProperties)study.GetProperties(4)).SetFrameRate(60);
        Save(doc,Path.Combine(Fixture,"slider_crank_clear.sldasm"));
        var obs=Insert(ad,"obstacle",Pose(.065,0,0,0)); doc.ClearSelection2(true); obs.Select4(false,null,false); ad.FixComponent(); doc.ClearSelection2(true);
        Save(doc,Path.Combine(Fixture,"slider_crank_obstacle.sldasm")); doc.ViewZoomtofit2();
        var metadata=new { crank_radius_m=.02,rod_length_m=.08,initial_angle_deg=30,rpm=60,expected_mechanism_dof=1,assembly_mates=7,
            clear_path=Path.Combine(Fixture,"slider_crank_clear.sldasm"),obstacle_path=Path.Combine(Fixture,"slider_crank_obstacle.sldasm"),
            initial_slider_x_m=sx, study="MVP_60rpm", joint_overlap_pairs=new[]{"base-1|crank-1","crank-1|rod-1","rod-1|slider-1"}};
        File.WriteAllText(Path.Combine(Fixture,"fixture.json"),Json.Serialize(metadata)); return metadata;
    }
}
