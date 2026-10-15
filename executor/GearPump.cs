using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Globalization;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;
using SolidWorks.Interop.swconst;

public partial class Cad {
    string pumpRootOverride,phaseRoot;
    string pumpSuffix="_实验";
    double phaseOffset;
    string PumpRoot {get{return pumpRootOverride??Path.Combine(Root,"fixtures","gear_pump");}}
    string PumpPath {get{return Path.Combine(PumpRoot,pumpRootOverride==null?"齿轮泵_运动验证.SLDASM":"齿轮泵_相位验证_"+Path.GetFileName(PumpRoot).Substring(0,8)+".SLDASM");}}
    Dictionary<string,object> PumpMetadata(){return Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(PumpRoot,"fixture.json")));}
    IComponent2 ResolvePump(IModelDoc2 doc,string role){var refs=(Dictionary<string,object>)PumpMetadata()["persistent_references"];if(!refs.ContainsKey(role))throw new Exception("ENTITY_NOT_FOUND");int e;var c=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String((string)refs[role]),out e) as IComponent2;if(c==null||e!=0)throw new Exception("PERSISTENT_REFERENCE_UNRESOLVED "+e);return c;}
    public object PumpEntities(string assembly){ConfigureModel(assembly);if(assembly!="gear_pump"&&assembly!="gear_phase")throw new Exception("ENTITY_LIST_REQUIRES_GEAR_PUMP");using(var s=new Scope(this,PumpPath,null)){return ((Dictionary<string,object>)PumpMetadata()["persistent_references"]).Keys.Select(k=>new {entity=k,instance=ResolvePump(s.Doc,k).Name2,reference_kind="solidworks_persistent_reference"}).ToArray();}}
    public object RecoverPump(){using(var s=new Scope(this,PumpPath,null)){
        Fingerprint(s.Doc,s.DocumentPath);Log("RECOVERY_DOCUMENT_OPEN");((IInterferenceDetectionMgr)((IAssemblyDoc)s.Doc).InterferenceDetectionManager).Done();Log("RECOVERY_INTERFERENCE_DONE");
        var study=(IMotionStudy)((IMotionStudyManager)s.Doc.Extension.GetMotionStudyManager()).GetMotionStudy("齿轮泵_30rpm");double previous=study.GetTime();study.Activate();study.SetTime(0);Application.DoEvents();
        var actual=Transforms(s.Doc);var map=Json.Deserialize<Dictionary<string,string>>(File.ReadAllText(Path.Combine(PumpRoot,"instance-map.json")));var source=Json.Deserialize<List<Dictionary<string,object>>>(File.ReadAllText(Path.Combine(PumpRoot,"source-components.json")));
        double delta=source.Max(v=>((System.Collections.IEnumerable)v["pose"]).Cast<object>().Select(Convert.ToDouble).Zip(actual[map[(string)v["instance"]]],(a,b)=>Math.Abs(a-b)).Max());
        if(Math.Abs(study.GetTime())>1e-8||delta>1e-5)throw new Exception("RECOVERY_INITIAL_POSE_MISMATCH "+delta);
        return new {process_id=Sw.GetProcessID(),previous_time_s=previous,restored_time_s=study.GetTime(),maximum_delta_from_original_import=delta,status="verified_initial_pose"};
    }}
    public object StaticCheck(string assembly,double threshold){if(double.IsNaN(threshold)||double.IsInfinity(threshold)||threshold<0)throw new Exception("INVALID_THRESHOLD");using(var s=new Scope(this,PathFor(assembly),null)){Fingerprint(s.Doc,s.DocumentPath);var events=Interferences(s.Doc,threshold);return new {assembly=assembly,assertion=events.Length==0?"pass":"fail",claim="current_pose_only",component_scope="all_resolved_components",excluded_pairs=new string[0],event_count=events.Length,events=events,volume_threshold_mm3=threshold};}}
    static int YawRow(double[] pose){return Enumerable.Range(0,3).OrderByDescending(j=>pose[j*3]*pose[j*3]+pose[j*3+1]*pose[j*3+1]).First();}
    static double[] Unwrapped(double[][] poses){int j=YawRow(poses[0]);var angle=new double[poses.Length];double last=Math.Atan2(poses[0][j*3+1],poses[0][j*3]);for(int i=1;i<poses.Length;i++){double a=Math.Atan2(poses[i][j*3+1],poses[i][j*3]);angle[i]=angle[i-1]+Math.Atan2(Math.Sin(a-last),Math.Cos(a-last));last=a;}return angle;}
    object SolvePump(string studyName,double duration,int fps,string runId){
        Log("LOAD_MOTION_SOLVE "+Sw.LoadAddIn(@"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\cmotionsw.dll"));
        if(Sw.RevisionNumber()!="34.0.0")throw new Exception("UNCALIBRATED_VERSION");if(studyName!="齿轮泵_30rpm"||duration<=0||duration>2||(fps!=30&&fps!=60)||Math.Abs(duration*fps-Math.Round(duration*fps))>1e-8)throw new Exception("INVALID_PUMP_SOLVER_OPTIONS");
        var scope=new Scope(this,PumpPath,studyName);Run r=null;double rpm1=0,rpm2=0,maxRatioError=0,maxSpeedError=0,maxFixedDelta=0;
        try{
            Fingerprint(scope.Doc,scope.DocumentPath);var driving=ResolvePump(scope.Doc,"driving_gear");var driven=ResolvePump(scope.Doc,"driven_gear");
            if(scope.Study.StudyType!=4)scope.Study.StudyType=4;
            if(!scope.Doc.EditRebuild3()||scope.Study.StudyType!=4)throw new Exception("PUMP_REBUILD_OR_STUDY_INVALID");scope.Study.SetDuration(duration);((IMotionStudyProperties)scope.Study.GetProperties(4)).SetFrameRate(fps);
            Log("PUMP_SOLVE_BEGIN "+runId);if(!scope.Study.Calculate())throw new Exception("SOLVER_FAILED");var result=(IMotionStudyResults)scope.Study.GetResults(4);if(result==null||result.IsOutOfDate())throw new Exception("RESULTS_STALE");
            int n=(int)Math.Round(duration*fps)+1;var poses=Transforms(scope.Doc).Keys.ToDictionary(k=>k,k=>new double[n][]);var times=new double[n];
            for(int i=0;i<n;i++){scope.EnsureActive();times[i]=(double)i/fps;scope.Study.SetTime(Argument(times[i],duration));Application.DoEvents();foreach(var p in Transforms(scope.Doc))poses[p.Key][i]=p.Value;}
            var a=Unwrapped(poses[driving.Name2]);var b=Unwrapped(poses[driven.Name2]);rpm1=a[n-1]/duration*30/Math.PI;rpm2=b[n-1]/duration*30/Math.PI;
            for(int i=1;i<n;i++){maxRatioError=Math.Max(maxRatioError,Math.Abs(a[i]+b[i]));maxSpeedError=Math.Max(maxSpeedError,Math.Abs(Math.Abs((a[i]-a[i-1])*fps)-Math.PI));}
            foreach(IComponent2 c in (object[])((IAssemblyDoc)scope.Doc).GetComponents(false))if(c.IsFixed())foreach(var p in poses[c.Name2])maxFixedDelta=Math.Max(maxFixedDelta,p.Zip(poses[c.Name2][0],(x,y)=>Math.Abs(x-y)).Max());
            string dir=Path.Combine(Root,"runs",runId);Directory.CreateDirectory(dir);
            using(var csv=new StreamWriter(Path.Combine(dir,"trajectory.csv"))){csv.WriteLine("frame,time_s,driving_angle_deg,driven_angle_deg");for(int i=0;i<n;i++)csv.WriteLine(string.Join(",",new[]{(double)i,times[i],a[i]*180/Math.PI,b[i]*180/Math.PI}.Select(v=>v.ToString("R",CultureInfo.InvariantCulture))));}
            var audit=new {driving_rpm=rpm1,driven_rpm=rpm2,maximum_gear_phase_sum_error_rad=maxRatioError,maximum_driving_speed_error_rad_s=maxSpeedError,maximum_fixed_transform_delta=maxFixedDelta};File.WriteAllText(Path.Combine(dir,"kinematics-audit.json"),Json.Serialize(audit));
            if(Math.Abs(Math.Abs(rpm1)-30)>.01||Math.Abs(rpm1+rpm2)>.01||maxRatioError>1e-4||maxSpeedError>.001||maxFixedDelta>1e-7)throw new Exception("PUMP_KINEMATICS_FAILED "+Json.Serialize(audit));
            r=new Run{Id=runId,Assembly=pumpRootOverride==null?"gear_pump":"gear_phase",ModelRoot=PumpRoot,Path=PumpPath,Study=studyName,Fingerprint=Fingerprint(scope.Doc,scope.DocumentPath),Duration=duration,Fps=fps,Directory=dir,Times=times,Poses=poses};
        }finally{scope.Dispose();}if(!scope.Restored)throw new Exception("RESTORATION_FAILED");runs.Add(runId,r);
        var summary=new {run_id=runId,assembly=r.Assembly,study=studyName,duration_s=duration,output_fps=fps,frames=r.Times.Length,driving_rpm=rpm1,driven_rpm=rpm2,maximum_gear_phase_sum_error_rad=maxRatioError,maximum_driving_speed_error_rad_s=maxSpeedError,maximum_fixed_transform_delta=maxFixedDelta,restoration=new{status="restored",maximum_transform_delta=scope.RestoreDelta},trajectory_csv=Path.Combine(r.Directory,"trajectory.csv"),fingerprint=r.Fingerprint};File.WriteAllText(Path.Combine(r.Directory,"solve.json"),Json.Serialize(summary));return summary;
    }
    object MeasurePump(Run r,string entity,string type,string component){
        if(type!="angular_velocity"||(entity!="driving_gear"&&entity!="driven_gear")||(component!="magnitude"&&component!="z"))throw new Exception("UNSUPPORTED_PUMP_MEASURE");
        var s=new Scope(this,r.Path,r.Study);object summary=null;
        try{ValidateRun(r,s);var c=ResolvePump(s.Doc,entity);var angles=Unwrapped(r.Poses[c.Name2]);var observed=Enumerable.Range(1,angles.Length-1).Select(i=>(angles[i]-angles[i-1])*r.Fps*180/Math.PI).ToArray();double reference=observed.Average();if(component=="magnitude")reference=Math.Abs(reference);
            var cosmos=(ICosmosMotionStudyResults)s.Study.GetResults(4);var pf=(IMotionPlotFeatureData)cosmos.CreatePlotFeatureData();var x=(IMotionPlotAxisFeatureData)cosmos.CreatePlotXAxisFeatureData();x.Type=0;var y=(IMotionPlotAxisFeatureData)cosmos.CreatePlotYAxisFeatureData();y.Type=10;y.Component=component=="z"?2:3;y.Entities=new DispatchWrapper[]{new DispatchWrapper(Faces(c).First())};var output=cosmos.GetValues(pf,x,new DispatchWrapper[]{new DispatchWrapper(y)}) as IMotionPlotFeatureOutput;if(output==null)throw new Exception("MEASURE_UNAVAILABLE");var times=(double[])output.GetXAxis();var values=(double[])output.GetYAxis(y);
            if(values.Length!=r.Times.Length||times.Length!=values.Length||values.Any(v=>double.IsNaN(v)||double.IsInfinity(v))||times.Zip(r.Times,(a,b)=>Math.Abs(a-b)).Max()>1e-8)throw new Exception("INCOMPLETE_MEASURE");
            var factors=new[]{1.0,180/Math.PI};var errors=factors.Select(f=>values.Max(v=>Math.Abs(v*f-reference))).ToArray();int best=errors[1]<errors[0]?1:0;double scale=factors[best];if(errors[best]>.01||Math.Abs(errors[0]-errors[1])<.01)throw new Exception("AMBIGUOUS_ANGULAR_UNITS");
            string raw=Path.Combine(r.Directory,entity+"_"+component+"_raw.csv"),csvPath=Path.Combine(r.Directory,entity+"_"+component+".csv");using(var rawWriter=new StreamWriter(raw))using(var writer=new StreamWriter(csvPath)){rawWriter.WriteLine("time_s,value_raw");writer.WriteLine("time_s,value_deg_per_s");for(int i=0;i<values.Length;i++){rawWriter.WriteLine(times[i].ToString("R",CultureInfo.InvariantCulture)+","+values[i].ToString("R",CultureInfo.InvariantCulture));values[i]*=scale;writer.WriteLine(times[i].ToString("R",CultureInfo.InvariantCulture)+","+values[i].ToString("R",CultureInfo.InvariantCulture));}}
            summary=new{run_id=r.Id,entity=entity,instance=c.Name2,measure_type=type,component=component,coordinate_frame="assembly_global",unit="deg/s",sample_count=values.Length,min=values.Min(),max=values.Max(),mean=values.Average(),raw_csv_path=raw,csv_path=csvPath,unit_calibration=new{method="independent_unwrapped_component_transform_derivative",raw_to_output_scale=scale,observed_reference_deg_s=reference,maximum_error_deg_s=errors[best]},restoration_status="restored"};
        }finally{s.Dispose();}if(!s.Restored)throw new Exception("RESTORATION_FAILED");return summary;
    }
    Dictionary<string,string> HashFiles(string dir) {
        var result=new Dictionary<string,string>();
        using(var sha=SHA256.Create()) foreach(string p in Directory.GetFiles(dir).OrderBy(p=>p)) {
            using(var f=new FileStream(p,FileMode.Open,FileAccess.Read,FileShare.ReadWrite)) result[Path.GetFileName(p)]=BitConverter.ToString(sha.ComputeHash(f));
        }
        return result;
    }
    static double[] ApplyPose(double[] t,double[] p,bool point){return Enumerable.Range(0,3).Select(j=>t[12]*(p[0]*t[j]+p[1]*t[3+j]+p[2]*t[6+j])+(point?t[9+j]:0)).ToArray();}
    double[] WorldPoint(IComponent2 c,double[] p) {return ApplyPose((double[])c.Transform2.ArrayData,p,true);}
    double[] WorldVector(IComponent2 c,double[] p) {return ApplyPose((double[])c.Transform2.ArrayData,p,false);}
    IFace2 PumpAxis(IComponent2 c,double x,double y) {
        var pose=(double[])c.Transform2.ArrayData;
        return Faces(c).Where(f=>((ISurface)f.GetSurface()).IsCylinder()).OrderBy(f=>{
            var v=(double[])((ISurface)f.GetSurface()).CylinderParams;var w=ApplyPose(pose,v.Take(3).ToArray(),true);var a=ApplyPose(pose,v.Skip(3).Take(3).ToArray(),false);
            return Math.Abs(v[6]-.006)*100+Math.Abs(a[2]*a[2]-1)+Math.Abs(w[0]-x)+Math.Abs(w[1]-y);
        }).First();
    }
    IFace2 PumpPlane(IComponent2 c) {var pose=(double[])c.Transform2.ArrayData;return Faces(c).Where(f=>{var s=(ISurface)f.GetSurface();return s.IsPlane()&&Math.Abs(ApplyPose(pose,((double[])s.PlaneParams).Take(3).ToArray(),false)[2])>.999;}).OrderByDescending(f=>f.GetArea()).First();}
    void SelectMateFaces(IModelDoc2 doc,IFace2 a,IFace2 b) {doc.ClearSelection2(true);var s=((ISelectionMgr)doc.SelectionManager).CreateSelectData();s.Mark=1;if(!((IEntity)a).Select4(false,s)||!((IEntity)b).Select4(true,s)) throw new Exception("MATE_SELECTION_FAILED");}
    void CheckMate(IFeature f,string label) {if(f==null) throw new Exception("MATE_CREATE_FAILED "+label);bool warning;int e=f.GetErrorCode2(out warning);Log("MATE_CREATED "+label+" feature="+f.Name+" error="+e+" warning="+warning);if(e!=0)throw new Exception("MATE_FEATURE_ERROR "+label+" "+e);}
    IFace2 FaceReference(IModelDoc2 doc,string reference){int e;var face=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out e) as IFace2;if(face==null||e!=0)throw new Exception("FACE_REFERENCE_UNRESOLVED "+e);return face;}
    void ShaftSupport(IModelDoc2 doc,IComponent2 shaft,Dictionary<string,string> refs,string prefix,double distance) {
        var initial=(double[])shaft.Transform2.ArrayData;
        SelectMateFaces(doc,FaceReference(doc,refs[prefix+"_axis"]),FaceReference(doc,refs[prefix+"_support"]));int e;
        var mate=((IAssemblyDoc)doc).AddMate5(1,2,false,0,0,0,1,1,0,0,0,false,false,0,out e);
        if(mate==null||e!=1) throw new Exception("SHAFT_CONCENTRIC_FAILED "+e);doc.ClearSelection2(true);
        SelectMateFaces(doc,FaceReference(doc,refs[prefix+"_plane"]),FaceReference(doc,refs["body_plane"]));
        mate=((IAssemblyDoc)doc).AddMate5(5,2,false,distance,distance,distance,1,1,0,0,0,false,false,0,out e);
        if(mate==null||e!=1) throw new Exception("SHAFT_AXIAL_FAILED "+e);doc.ClearSelection2(true);
        doc.EditRebuild3();var current=(double[])shaft.Transform2.ArrayData;
        Log("SHAFT_AXIAL "+shaft.Name2+" distance="+distance+" delta_z="+(current[11]-initial[11]));
        if(Math.Abs(current[11]-initial[11])>1e-5){mate.Flipped=!mate.Flipped;if(!doc.EditRebuild3())throw new Exception("AXIAL_FLIP_REBUILD_FAILED");current=(double[])shaft.Transform2.ArrayData;Log("SHAFT_AXIAL_FLIPPED delta_z="+(current[11]-initial[11]));if(Math.Abs(current[11]-initial[11])>1e-5)throw new Exception("AXIAL_POSITION_NOT_PRESERVED");}
    }
    void LockPair(IModelDoc2 doc,IComponent2 a,IComponent2 b) {
        var data=(ILockMateFeatureData)((IAssemblyDoc)doc).CreateMateData(16);
        data.EntitiesToMate=new DispatchWrapper[]{new DispatchWrapper(a),new DispatchWrapper(b)};
        CheckMate((IFeature)((IAssemblyDoc)doc).CreateMate(data),"lock "+a.Name2+" "+b.Name2);
    }
    object[] Interferences(IModelDoc2 doc,double threshold) {
        var mgr=(IInterferenceDetectionMgr)((IAssemblyDoc)doc).InterferenceDetectionManager;
        try {mgr.TreatCoincidenceAsInterference=false;mgr.IgnoreHiddenBodies=false;var hits=mgr.GetInterferences() as object[];
            return hits==null?new object[0]:hits.Cast<IInterference>().Where(h=>h.Volume*1e9>threshold).Select(h=>(object)new {parts=((object[])h.Components).Cast<IComponent2>().Select(c=>c.Name2).OrderBy(n=>n).ToArray(),volume_mm3=h.Volume*1e9}).ToArray();
        } finally {mgr.Done();}
    }
    public object BuildGearPump() {
        if(File.Exists(PumpPath))throw new Exception("EXPERIMENT_ALREADY_EXISTS");
        foreach(IModelDoc2 staging in Sw.GetDocuments() as object[]??new object[0]){
            if(staging.GetType()!=2||staging.GetPathName()!="")continue;
            var cs=((IAssemblyDoc)staging).GetComponents(false) as object[];
            if(cs!=null&&cs.Length==18&&cs.Cast<IComponent2>().All(c=>Path.GetFullPath(c.GetPathName()).StartsWith(Path.Combine(PumpRoot,"parts")+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))){Log("CLOSE_FAILED_STAGING "+staging.GetTitle());Sw.CloseDoc(staging.GetTitle());}
        }
        string source=Path.Combine(Root,"OutSolid_简易单级齿轮泵");var hashes=HashFiles(source);
        Directory.CreateDirectory(PumpRoot);Directory.CreateDirectory(Path.Combine(PumpRoot,"source_snapshot"));Directory.CreateDirectory(Path.Combine(PumpRoot,"parts"));
        foreach(string p in Directory.GetFiles(source)) {File.Copy(p,Path.Combine(PumpRoot,"source_snapshot",Path.GetFileName(p)),true);if(Path.GetExtension(p).Equals(".SLDPRT",StringComparison.OrdinalIgnoreCase)){string copy=Path.Combine(PumpRoot,"parts",Path.GetFileNameWithoutExtension(p)+pumpSuffix+".SLDPRT");if(!File.Exists(copy))File.Copy(p,copy);}}
        File.WriteAllText(Path.Combine(PumpRoot,"source-hashes-before.json"),Json.Serialize(hashes));
        var prior=(IModelDoc2)Sw.ActiveDoc;IModelDoc2 original=null;bool alreadyOpen=false;
        var records=new List<Dictionary<string,object>>();
        try {
            string op=Path.Combine(source,"齿轮泵总装.SLDASM");alreadyOpen=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Any(d=>d.GetPathName()==op);
            int e=0,w=0;original=(IModelDoc2)Sw.OpenDoc6(op,2,3,"",ref e,ref w);if(original==null||e!=0)throw new Exception("SOURCE_OPEN_FAILED "+e);
            foreach(IComponent2 c in (object[])((IAssemblyDoc)original).GetComponents(false))records.Add(new Dictionary<string,object>{{"instance",c.Name2},{"part",Path.GetFileNameWithoutExtension(c.GetPathName())},{"configuration",c.ReferencedConfiguration},{"pose",(double[])c.Transform2.ArrayData}});
        } finally {if(original!=null&&!alreadyOpen)Sw.CloseDoc(original.GetTitle());if(prior!=null){int e=0;Sw.ActivateDoc3(prior.GetTitle(),false,0,ref e);}}
        if(phaseOffset!=0)foreach(var r in records.Where(v=>new[]{"短轴-1","GB_Spur_gear_S14A75H50L12.0N-1","GB_CONNECTING_PIECE_KEYS_CWK 4X18-1"}.Contains((string)v["instance"])))r["pose"]=RotateWorld((double[])r["pose"],.083258518,.041402892,phaseOffset);
        File.WriteAllText(Path.Combine(PumpRoot,"source-components.json"),Json.Serialize(records));
        var doc=New("assembly");var ad=(IAssemblyDoc)doc;var comps=new Dictionary<string,IComponent2>();
        foreach(var r in records) {
            string path=Path.Combine(PumpRoot,"parts",(string)r["part"]+pumpSuffix+".SLDPRT");int e=0,w=0;if(Sw.OpenDoc6(path,1,1,"",ref e,ref w)==null||e!=0)throw new Exception("COPY_PART_OPEN_FAILED");
            var t=(double[])r["pose"];var c=(IComponent2)ad.AddComponent5(path,0,(string)r["configuration"],false,"",t[9],t[10],t[11]);if(c==null)throw new Exception("COPY_INSERT_FAILED");
            Sw.ActivateDoc3(doc.GetTitle(),false,0,ref e);c.ReferencedConfiguration=(string)r["configuration"];c.Transform2=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(t);comps.Add((string)r["instance"],c);
            doc.ClearSelection2(true);c.Select4(false,null,false);ad.FixComponent();doc.ClearSelection2(true);
        }
        var mapping=comps.ToDictionary(k=>k.Key,k=>k.Value.Name2);File.WriteAllText(Path.Combine(PumpRoot,"instance-map.json"),Json.Serialize(mapping));
        var baseline=Interferences(doc,.001);File.WriteAllText(Path.Combine(PumpRoot,"static-before-mates.json"),Json.Serialize(new {event_count=baseline.Length,events=baseline,scope="all_18_components",threshold_mm3=.001}));
        Log("BASELINE_INTERFERENCES "+baseline.Length);
        var longS=comps["长轴-1"];var shortS=comps["短轴-1"];var gear1=comps["GB_Spur_gear_S14A75H50L12.0N-2"];var gear2=comps["GB_Spur_gear_S14A75H50L12.0N-1"];
        if(gear1.ReferencedConfiguration!=gear2.ReferencedConfiguration)throw new Exception("GEAR_CONFIGURATIONS_DIFFER");
        var key1=comps["GB_CONNECTING_PIECE_KEYS_CWK 4X18-2"];var key2=comps["GB_CONNECTING_PIECE_KEYS_CWK 4X18-1"];var body=comps["泵体-1"];
        var boundFaces=new Dictionary<string,IFace2>{{"driving_axis",PumpAxis(longS,.0832585185445,.0064028925158)},{"driving_support",PumpAxis(body,.0832585185445,.0064028925158)},{"driven_axis",PumpAxis(shortS,.083258518,.041402892)},{"driven_support",PumpAxis(body,.083258518,.041402892)},{"driving_plane",PumpPlane(longS)},{"driven_plane",PumpPlane(shortS)},{"body_plane",PumpPlane(body)},{"gear1_axis",PumpAxis(gear1,.0832585185445,.0064028925158)},{"gear2_axis",PumpAxis(gear2,.083258518,.041402892)}};
        var faceRefs=boundFaces.ToDictionary(k=>k.Key,k=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(k.Value)));
        double bodyZ=WorldPoint(body,((double[])((ISurface)boundFaces["body_plane"].GetSurface()).PlaneParams).Skip(3).Take(3).ToArray())[2];
        double driveDistance=Math.Abs(WorldPoint(longS,((double[])((ISurface)boundFaces["driving_plane"].GetSurface()).PlaneParams).Skip(3).Take(3).ToArray())[2]-bodyZ);
        double drivenDistance=Math.Abs(WorldPoint(shortS,((double[])((ISurface)boundFaces["driven_plane"].GetSurface()).PlaneParams).Skip(3).Take(3).ToArray())[2]-bodyZ);
        Log("BOUND_PERSISTENT_FACES "+faceRefs.Count);
        File.WriteAllText(Path.Combine(PumpRoot,"face-references.json"),Json.Serialize(faceRefs));
        foreach(var c in new[]{longS,shortS,gear1,gear2,key1,key2}){doc.ClearSelection2(true);c.Select4(false,null,false);ad.UnfixComponent();doc.ClearSelection2(true);}
        LockPair(doc,longS,gear1);LockPair(doc,longS,key1);LockPair(doc,shortS,gear2);LockPair(doc,shortS,key2);
        ShaftSupport(doc,longS,faceRefs,"driving",driveDistance);ShaftSupport(doc,shortS,faceRefs,"driven",drivenDistance);
        var g=(IGearMateFeatureData)ad.CreateMateData(10);g.EntitiesToMate=new DispatchWrapper[]{new DispatchWrapper(FaceReference(doc,faceRefs["gear1_axis"])),new DispatchWrapper(FaceReference(doc,faceRefs["gear2_axis"]))};g.GearRatioNumerator=1;g.GearRatioDenominator=1;g.Reverse=false;CheckMate((IFeature)ad.CreateMate(g),"gear_1_to_1");
        if(!doc.EditRebuild3())throw new Exception("PUMP_REBUILD_FAILED");
        Log("LOAD_MOTION "+Sw.LoadAddIn(@"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\cmotionsw.dll"));
        var mgr=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();var study=(IMotionStudy)mgr.CreateMotionStudy();study.Name="齿轮泵_30rpm";study.Activate();study.StudyType=4;if(study.StudyType!=4)throw new Exception("MOTION_ANALYSIS_REQUIRED");
        var motor=(ISimulationMotorFeatureData)study.CreateDefinition(78);var face=FaceReference(doc,faceRefs["driving_axis"]);motor.DirectionReference=face;motor.Location=face;motor.ConstantSpeedMotor(Math.PI);if(study.CreateFeature(motor)==null)throw new Exception("PUMP_MOTOR_CREATE_FAILED");
        study.SetDuration(2);((IMotionStudyProperties)study.GetProperties(4)).SetFrameRate(30);
        var refs=new Dictionary<string,string>();foreach(var kv in new Dictionary<string,IComponent2>{{"driving_gear",gear1},{"driven_gear",gear2},{"driving_shaft",longS},{"driven_shaft",shortS},{"pump_body",body},{"pump_cover",comps["泵盖-1"]}})refs[kv.Key]=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(kv.Value));
        var initialPoseDelta=records.ToDictionary(r=>(string)r["instance"],r=>((double[])comps[(string)r["instance"]].Transform2.ArrayData).Zip((double[])r["pose"],(a,b)=>Math.Abs(a-b)).Max());
        File.WriteAllText(Path.Combine(PumpRoot,"mate-position-deltas.json"),Json.Serialize(initialPoseDelta));
        if(initialPoseDelta.Values.Max()>1e-5)throw new Exception("INITIAL_POSITION_CHANGED "+initialPoseDelta.Values.Max());
        var after=Interferences(doc,.001);File.WriteAllText(Path.Combine(PumpRoot,"static-after-mates.json"),Json.Serialize(new {event_count=after.Length,events=after,scope="all_18_components",threshold_mm3=.001}));
        Save(doc,PumpPath);doc.ViewZoomtofit2();
        var hashesAfter=HashFiles(source);if(hashes.Any(k=>hashesAfter[k.Key]!=k.Value))throw new Exception("SOURCE_FILES_CHANGED");
        File.WriteAllText(Path.Combine(PumpRoot,"source-hashes-after.json"),Json.Serialize(hashesAfter));
        var metadata=new {assembly="gear_pump",path=PumpPath,study=study.Name,rpm=30,component_count=comps.Count,expected_mates=9,gear_configuration=gear1.ReferencedConfiguration,ratio=1,source_files_unchanged=true,source_file_count=hashes.Count,roles=new {driving_gear=gear1.Name2,driven_gear=gear2.Name2,driving_shaft=longS.Name2,driven_shaft=shortS.Name2,pump_body=body.Name2,pump_cover=comps["泵盖-1"].Name2},persistent_references=refs,baseline_before_events=baseline.Length,baseline_after_events=after.Length};
        File.WriteAllText(Path.Combine(PumpRoot,"fixture.json"),Json.Serialize(metadata));return metadata;
    }
}
