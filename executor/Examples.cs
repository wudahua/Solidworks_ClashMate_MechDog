using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    IModelDoc2 ExampleDocument(string kind){string template=System.Environment.GetEnvironmentVariable(kind=="part"?"SW_MCP_PART_TEMPLATE":"SW_MCP_ASSEMBLY_TEMPLATE");if(string.IsNullOrEmpty(template))return New(kind);if(!File.Exists(template))throw new Exception("EXAMPLE_TEMPLATE_NOT_FOUND");var doc=(IModelDoc2)Sw.NewDocument(template,0,0,0);if(doc==null)throw new Exception("TEMPLATE_UNAVAILABLE");return doc;}
    string ExamplePart(string dir,string name,bool cylinder){var doc=ExampleDocument("part");var modeler=(IModeler)Sw.GetModeler();var body=cylinder?modeler.CreateBodyFromCyl(new[]{0.0,0,0,0,0,1,.006,.015}):modeler.CreateBodyFromBox3(new[]{0.0,0,0,0,0,1,.018,.014,.008});if(((IPartDoc)doc).CreateFeatureFromBody3(body,false,0)==null)throw new Exception("EXAMPLE_BODY_FAILED");string path=Path.Combine(dir,name+".SLDPRT");Save(doc,path);return path;}
    IComponent2 ExampleInsert(IAssemblyDoc doc,string part){var c=(IComponent2)doc.AddComponent5(part,0,"",false,"",0,0,0);if(c==null)throw new Exception("EXAMPLE_INSERT_FAILED");c.Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(Pose(0,0,0,0));return c;}
    public object BuildMotionExamples(){
        var previous=(IModelDoc2)Sw.ActiveDoc;string previousTitle=previous==null?null:previous.GetTitle();var owned=new List<string>();string dir=Path.Combine(Root,"examples","generated",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(dir);
        try{string support=ExamplePart(dir,"support",true),rotor=ExamplePart(dir,"rotor",true),rail=ExamplePart(dir,"rail",false),carriage=ExamplePart(dir,"carriage",false);owned.AddRange(new[]{support,rotor,rail,carriage});
            var output=new Dictionary<string,string>();foreach(string kind in new[]{"rotary","linear","fixed","rotary_unmated","linear_unmated"}){var doc=ExampleDocument("assembly");var ad=(IAssemblyDoc)doc;var a=ExampleInsert(ad,kind.StartsWith("linear")?rail:support);var b=ExampleInsert(ad,kind.StartsWith("linear")?carriage:rotor);
                if(!kind.EndsWith("_unmated")){if(kind=="linear"){PlaneMate(doc,a,b,"Front Plane","front");PlaneMate(doc,a,b,"Top Plane","top");}else{Concentric(doc,a,0,b,0,"axle");PlaneMate(doc,a,b,"Front Plane","front");}}
                if(kind=="fixed"){doc.ClearSelection2(true);b.Select4(false,null,false);ad.FixComponent();doc.ClearSelection2(true);}if(!doc.EditRebuild3())throw new Exception("EXAMPLE_REBUILD_FAILED");doc.ViewZoomtofit2();string path=Path.Combine(dir,kind+".SLDASM");Save(doc,path);owned.Add(path);output[kind]=path;}
            AtomicJson(Path.Combine(dir,"examples.json"),output);return new{directory=dir,assemblies=output,origin="procedural_geometry_created_by_this_project",third_party_cad_assets=false};
        }finally{CloseUserDocuments(owned.ToArray());if(previousTitle!=null){int e=0;Sw.ActivateDoc3(previousTitle,false,0,ref e);}}
    }
}
