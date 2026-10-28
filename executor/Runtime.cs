using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Globalization;
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    class Run {
        public string Id,Path,Study,Fingerprint,Directory,Assembly,ModelRoot;
        public int EditVersion;
        public bool Generic,AllowNativeGridSubset;
        public Dictionary<string,string> ComponentNames;
        public double Duration;
        public int Fps;
        public Dictionary<string,double[][]> Poses;
        public double[] Times;
        public Dictionary<string,string> FileHashes;
    }
    readonly Dictionary<string,Run> runs=new Dictionary<string,Run>();
    string PathFor(string assembly) {ConfigureModel(assembly);if(assembly=="gear_pump"||assembly=="gear_phase")return PumpPath;if(assembly=="parameter_trial"){if(parameterPath==null)throw new Exception("EXPERIMENT_NOT_REGISTERED");return parameterPath;}if(assembly!="clear"&&assembly!="obstacle")throw new Exception("UNSUPPORTED_ASSEMBLY");return Path.Combine(Fixture,"slider_crank_"+assembly+".sldasm");}
    class Scope : IDisposable {
        Cad cad; IModelDoc2 previous;
        public IModelDoc2 Doc;
        public IMotionStudy Study;
        public string InputSnapshotPath {get{return ownedSnapshot==null?null:ownedSnapshot.InputSnapshotPath;}}
        public double OriginalTime;
        string originalStudy;
        double originalActiveTime;
        string expectedPath,expectedConfiguration;
        string previousTitle,previousPath,targetStudyName;
        Dictionary<string,double[]> original;
        OwnedMotionSnapshot ownedSnapshot;
        public bool Restored;
        public double RestoreDelta;
        public Dictionary<string,double[]> InitialPoses {get{return original;}}
        public string DocumentPath {get{return expectedPath;}}
        public StudyState[] InitialStudyStates {get{return ownedSnapshot==null?null:ownedSnapshot.InputStudies;}}
        public StudyHistory.Observation HistoryObservation;
        SolvePerformance timing;
        void Timing(string name){if(timing!=null)timing.Phase(name);}
        public Scope(Cad owner,string path,string studyName,SolvePerformance measurement=null) {
            timing=measurement;Timing("scope_read_active_context");
            cad=owner;owner.LastContextRestoration="pending"; previous=(IModelDoc2)owner.Sw.ActiveDoc;
            previousTitle=previous==null?null:previous.GetTitle();previousPath=previous==null?null:previous.GetPathName();targetStudyName=studyName;
            try {
                owner.LastContextRestoration="pending";
                Log("SCOPE_OPEN_BEGIN "+path);
                Timing("scope_open_document");
                int e=0,w=0; Doc=(IModelDoc2)owner.Sw.OpenDoc6(path,2,1,"",ref e,ref w);
                if(Doc==null||e!=0) throw new Exception("ASSEMBLY_OPEN_FAILED "+e);
                Log("SCOPE_OPEN_DONE "+path);
                Timing("scope_validate_and_activate_document");
                if(!Doc.GetPathName().Equals(Path.GetFullPath(path),StringComparison.OrdinalIgnoreCase))throw new Exception("ASSEMBLY_OPEN_PATH_MISMATCH");
                var registered=owner.userModels.Values.FirstOrDefault(m=>m.Path.Equals(path,StringComparison.OrdinalIgnoreCase));
                if(registered!=null&&!string.IsNullOrEmpty(registered.Configuration)&&Doc.ConfigurationManager.ActiveConfiguration.Name!=registered.Configuration)throw new Exception("MODEL_CONFIGURATION_CHANGED");
                expectedPath=Doc.GetPathName();expectedConfiguration=Doc.ConfigurationManager.ActiveConfiguration.Name;
                var current=(IModelDoc2)owner.Sw.ActiveDoc;if(current==null||!string.Equals(current.GetPathName(),expectedPath,StringComparison.OrdinalIgnoreCase))owner.Sw.ActivateDoc3(Doc.GetTitle(),false,0,ref e);
                Log("SCOPE_ACTIVATE_DONE "+path);
                Timing("scope_enumerate_initial_studies");
                var manager=(IMotionStudyManager)Doc.Extension.GetMotionStudyManager();
                foreach(string name in Names(manager)) { var s=(IMotionStudy)manager.GetMotionStudy(name); if(s.IsActive){originalStudy=name;originalActiveTime=s.GetTime();} }
                if(studyName!=null) {
                    Timing("scope_snapshot_capture_and_save");
                    if(registered!=null)ownedSnapshot=new OwnedMotionSnapshot(owner,registered,Doc);
                    // Saving the owned snapshot can invalidate Motion manager/study COM proxies.
                    manager=(IMotionStudyManager)Doc.Extension.GetMotionStudyManager();
                    Timing("scope_capture_initial_poses");
                    original=Transforms(Doc);
                    Timing("scope_select_and_activate_study");
                    Study=(IMotionStudy)manager.GetMotionStudy(studyName);
                    if(Study==null) throw new Exception("STUDY_NOT_FOUND");
                    owner.LastOperationRestoration="pending";
                    OriginalTime=Study.GetTime(); Study.Activate();
                }
            } catch(Exception failure) { try{Dispose();}catch(Exception rollback){owner.LastOperationRestoration="unknown";throw new CadFault("RESTORATION_FAILED","打开或激活失败，且无法核验原窗口恢复。",new{original_error=failure.ToString(),rollback_error=rollback.ToString()});}if(failure is COMException)owner.LastOperationRestoration="unknown";throw; }
        }
        public void RefreshStudy() {
            // Rebuild/Calculate can invalidate the old document/study proxies.
            // Resolve the recorded input first; never activate or select another input.
            var current=cad.Sw.GetOpenDocumentByName(expectedPath) as IModelDoc2;
            var active=cad.Sw.ActiveDoc as IModelDoc2;
            if(current==null||active==null||!string.Equals(current.GetPathName(),expectedPath,StringComparison.OrdinalIgnoreCase)||!string.Equals(active.GetPathName(),expectedPath,StringComparison.OrdinalIgnoreCase)||current.ConfigurationManager.ActiveConfiguration.Name!=expectedConfiguration||active.ConfigurationManager.ActiveConfiguration.Name!=expectedConfiguration)throw new Exception("SESSION_CONFLICT: study refresh input changed");
            var selected=(IMotionStudy)((IMotionStudyManager)current.Extension.GetMotionStudyManager()).GetMotionStudy(targetStudyName);
            if(selected==null||!selected.IsActive)throw new Exception("SESSION_CONFLICT: expected study is not active");
            Doc=current;Study=selected;
        }
        public void EnsureActive() {
            var active=(IModelDoc2)cad.Sw.ActiveDoc;
            if(active==null||!string.Equals(active.GetPathName(),expectedPath,StringComparison.OrdinalIgnoreCase)||!string.Equals(Doc.GetPathName(),expectedPath,StringComparison.OrdinalIgnoreCase)||Doc.ConfigurationManager.ActiveConfiguration.Name!=expectedConfiguration)
                throw new Exception("SESSION_CONFLICT: active document or configuration changed");
        }
        public void Dispose() {
            Timing("scope_restore_snapshot_and_context");
            Exception restoreCause=null;
            try {
                if(Study!=null&&original!=null) {
                    if(ownedSnapshot!=null){Doc=ownedSnapshot.Restore(HistoryObservation);Study=(IMotionStudy)((IMotionStudyManager)Doc.Extension.GetMotionStudyManager()).GetMotionStudy(targetStudyName);var diagnostic=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(ownedSnapshot.Diagnostics));RestoreDelta=Convert.ToDouble(diagnostic["maximum_transform_delta"]);Restored=true;}
                    else {
                    Study.SetTime(OriginalTime); Application.DoEvents();
                    if(originalStudy!=null&&originalStudy!=Study.Name){var originalActive=(IMotionStudy)((IMotionStudyManager)Doc.Extension.GetMotionStudyManager()).GetMotionStudy(originalStudy);originalActive.Activate();originalActive.SetTime(originalActiveTime);Application.DoEvents();}
                    var after=Transforms(Doc);
                    RestoreDelta=original.Max(k=>k.Value.Zip(after[k.Key],(a,b)=>Math.Abs(a-b)).Max());
                    Restored=RestoreDelta<1e-7 && Math.Abs(Study.GetTime()-OriginalTime)<1e-7;
                    }
                } else Restored=true;
            } catch(Exception e){restoreCause=e;Restored=false;} finally {
                try{if(previousTitle!=null) {var active=(IModelDoc2)cad.Sw.ActiveDoc;if(active==null||!string.Equals(active.GetPathName(),previousPath,StringComparison.OrdinalIgnoreCase)){int e=0;var activated=cad.Sw.ActivateDoc3(previousTitle,false,0,ref e);if(activated==null||e!=0)Restored=false;}}}catch(Exception e){restoreCause=e;Restored=false;}
                cad.LastContextRestoration=Restored?"restored":"unknown";
                if(Study!=null&&original!=null||!Restored)cad.LastOperationRestoration=Restored?"restored":"unknown";
                if(!Restored)throw new CadFault("RESTORATION_FAILED","无法确认完整状态已恢复。",new{maximum_transform_delta=RestoreDelta,state_difference=ownedSnapshot==null?null:ownedSnapshot.Diagnostics,cause=restoreCause==null?null:restoreCause.ToString(),cause_details=restoreCause==null?null:FailureEvidence(restoreCause)});
            }
        }
    }
    static string[] Names(IMotionStudyManager mgr) { return (mgr.GetMotionStudyNames() as object[]??new object[0]).Cast<string>().ToArray(); }
    static Dictionary<string,double[]> Transforms(IModelDoc2 d) { return ReadTransforms(d,null); }
    static Dictionary<string,double[]> ReadTransforms(IModelDoc2 d,Dictionary<string,object> profile) {
        var timer=System.Diagnostics.Stopwatch.StartNew();var components=((object[])((IAssemblyDoc)d).GetComponents(false)).Cast<IComponent2>().ToArray();long inventory=timer.ElapsedTicks,flags=0,names=0,transforms=0,arrays=0;int reads=0;
        var result=new Dictionary<string,double[]>();foreach(var c in components){long start=timer.ElapsedTicks;bool suppressed=c.IsSuppressed();flags+=timer.ElapsedTicks-start;if(suppressed)continue;
            start=timer.ElapsedTicks;string name=c.Name2;names+=timer.ElapsedTicks-start;start=timer.ElapsedTicks;var transform=c.GetTotalTransform(false);transforms+=timer.ElapsedTicks-start;start=timer.ElapsedTicks;var values=(double[])transform.ArrayData;arrays+=timer.ElapsedTicks-start;result.Add(name,values);reads++;}
        if(profile!=null){double ms=1000.0/System.Diagnostics.Stopwatch.Frequency;profile["inventory_ms"]=inventory*ms;profile["suppression_ms"]=flags*ms;profile["names_ms"]=names*ms;profile["get_total_transform_ms"]=transforms*ms;profile["array_data_ms"]=arrays*ms;profile["total_ms"]=timer.Elapsed.TotalMilliseconds;profile["observed_component_count"]=components.Length;profile["pose_count"]=reads;profile["instrumented_COM_calls"]=1+components.Length+3*reads;profile["COM_count_scope"]="explicit_method_calls_in_reader_not_internal_RPC_or_solver";}
        return result;
    }
    string Fingerprint(IModelDoc2 doc,string knownPath=null) {
        string path=knownPath;
        for(int attempt=0;;attempt++) {
            try{
                string actualPath=doc.GetPathName();if(path==null)path=actualPath;
                if(!string.Equals(path,actualPath,StringComparison.OrdinalIgnoreCase))throw new Exception("SESSION_CONFLICT: fingerprint document identity changed");
                return FingerprintCore(doc);
            }
            catch(COMException e) {
                if(path==null||attempt>=2||(e.HResult!=unchecked((int)0x80010100)&&e.HResult!=unchecked((int)0x80010001)&&e.HResult!=unchecked((int)0x8001010A)))throw;
                Log("FINGERPRINT_READ_RETRY "+(attempt+1)+" hresult="+e.HResult);
                Application.DoEvents();System.Threading.Thread.Sleep(100);
                doc=(IModelDoc2)Sw.GetOpenDocumentByName(path);
                if(doc==null)throw;
            }
        }
    }
    string FingerprintCore(IModelDoc2 doc) {
        var paths=((object[])((IAssemblyDoc)doc).GetComponents(false)).Cast<IComponent2>().Select(c=>c.GetPathName()).Concat(new[]{doc.GetPathName()}).Distinct().OrderBy(p=>p).ToArray();
        using(var sha=SHA256.Create()) {
            var lines=new List<string>();
            foreach(var p in paths) {
                bool pump=doc.GetPathName().Equals(PumpPath,StringComparison.OrdinalIgnoreCase);
                string allowed=pump?Path.Combine(PumpRoot,"parts"):Fixture;
                bool ownedParameter=parameterPath!=null&&doc.GetPathName().Equals(parameterPath,StringComparison.OrdinalIgnoreCase)&&p.Equals(parameterPath,StringComparison.OrdinalIgnoreCase);
                string userRoot;bool ownedUser=userRoots.TryGetValue(doc.GetPathName(),out userRoot)&&Path.GetFullPath(p).StartsWith(userRoot+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase);
                if(!ownedUser&&!ownedParameter&&!(pump&&p.Equals(PumpPath,StringComparison.OrdinalIgnoreCase))&&!Path.GetFullPath(p).StartsWith(allowed+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)) throw new CadFault("EXTERNAL_REFERENCE_UNSUPPORTED","打开后原生组件解析到隔离目录之外，未继续保存或求解。可能涉及本机标准件搜索/Toolbox替换；不能仅凭磁盘引用重定向判定隔离成功。",new{assembly_path=doc.GetPathName(),resolved_component_path=p,expected_owned_directory=userRoot,automatic_external_file_save=false});
                using(var stream=new FileStream(p,FileMode.Open,FileAccess.Read,FileShare.ReadWrite)) lines.Add(p+":"+BitConverter.ToString(sha.ComputeHash(stream)));
            }
            lines.Add(doc.ConfigurationManager.ActiveConfiguration.Name);
            foreach(IComponent2 c in (object[])((IAssemblyDoc)doc).GetComponents(false))lines.Add(c.Name2+":"+c.ReferencedConfiguration+":"+c.IsFixed());
            return BitConverter.ToString(sha.ComputeHash(System.Text.Encoding.UTF8.GetBytes(string.Join("\n",lines))));
        }
    }
    public object Capabilities() { return new { revision=Sw.RevisionNumber(),process_id=Sw.GetProcessID(), protocol_version=1, scope="registered_models_and_owned_experiments", supported_assemblies=new[]{"clear","obstacle","gear_pump","gear_phase","parameter_trial"}, phase_experiment_registered=phaseRoot!=null,parameter_experiment_registered=parameterPath!=null,
        motion_type=4, calibrated_revision="34.0.0", rotary_input="rpm * 2*pi/60, tested on revision 34.0.0", sampling="verified solver output frames", continuous_collision=false,
        templates_valid=File.Exists(Tutorial+"part.prtdot")&&File.Exists(Tutorial+"assembly.asmdot") }; }
    public object Inspect(string assembly) {
        using(var scope=new Scope(this,PathFor(assembly),null)) {
            var doc=scope.Doc; var ad=(IAssemblyDoc)doc;
            var comps=((object[])ad.GetComponents(false)).Cast<IComponent2>().Select(c=>new { instance=c.Name2,path=c.GetPathName(),fixed_component=c.IsFixed(),transform=(double[])c.Transform2.ArrayData }).ToArray();
            int mates=0; var feature=(IFeature)doc.FirstFeature();
            while(feature!=null) { if(feature.GetTypeName2()=="MateGroup") { var sub=(IFeature)feature.GetFirstSubFeature(); while(sub!=null) { if(sub.GetSpecificFeature2() is IMate2) mates++; sub=(IFeature)sub.GetNextSubFeature(); } } feature=(IFeature)feature.GetNextFeature(); }
            return new { assembly=assembly,path=doc.GetPathName(),configuration=doc.ConfigurationManager.ActiveConfiguration.Name,components=comps,mate_count=mates,expected_dof=1,dof_basis=assembly=="gear_pump"?"two supported shafts, four rigid locks and one 1:1 gear mate; validated by trajectory":"planar slider-crank topology; validated by solved trajectory" };
        }
    }
    public object ListStudies(string assembly) {
        using(var scope=new Scope(this,PathFor(assembly),null)) { var mgr=(IMotionStudyManager)scope.Doc.Extension.GetMotionStudyManager(); return Names(mgr).Select(n=>{var s=(IMotionStudy)mgr.GetMotionStudy(n); return new { name=n,type=s.StudyType,duration_s=s.GetDuration(),output_fps=((IMotionStudyProperties)s.GetProperties(s.StudyType)).GetFrameRate() };}).ToArray(); }
    }
    static double Argument(double t,double duration) { return MotionTimeSelection.Argument(t,duration); }
    public object Solve(string assembly,string studyName,double duration,int fps,string runId) {
        ConfigureModel(assembly);if(assembly=="gear_pump"||assembly=="gear_phase")return SolvePump(studyName,duration,fps,runId);
        Log("LOAD_MOTION_SOLVE "+Sw.LoadAddIn(@"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\cmotionsw.dll"));
        if(Sw.RevisionNumber()!="34.0.0") throw new Exception("UNCALIBRATED_VERSION");
        if(duration<=0||duration>2||(fps!=30&&fps!=60)) throw new Exception("INVALID_SOLVER_OPTIONS");
        if(Math.Abs(duration*fps-Math.Round(duration*fps))>1e-8) throw new Exception("DURATION_MUST_ALIGN_TO_FRAME");
        var scope=new Scope(this,PathFor(assembly),studyName); Run run=null;
        double maxPositionError=0,maxCrankError=0;
        try {
            Fingerprint(scope.Doc,scope.DocumentPath); // Reject external dependencies before writing solver settings or rebuilding.
            if(!scope.Doc.EditRebuild3()) throw new Exception("REBUILD_FAILED");
            scope.Study.Activate();
            if(scope.Study.StudyType!=4)scope.Study.StudyType=4;
            Log("STUDY_STATUS name="+scope.Study.Name+" type="+scope.Study.StudyType+" active="+scope.Study.IsActive+" feature_count="+scope.Study.GetMotionFeaturesCount());
            if(scope.Study.StudyType!=4) throw new Exception("MOTION_ANALYSIS_REQUIRED");
            // Only the registered fixture's existing calibrated motor is used; no arbitrary motor writes.
            var features=scope.Study.GetMotionFeatures() as object[];
            var motors=new List<ISimulationMotorFeatureData>();
            if(features!=null) foreach(IFeature f in features) { Log("MOTION_FEATURE "+f.Name+" "+f.GetTypeName2()); var m=f.GetDefinition() as ISimulationMotorFeatureData; if(m!=null) { Log("MOTOR_MAGNITUDE "+m.Magnitude); motors.Add(m); } }
            if(motors.Count==0) {
                var f=((IAssemblyDoc)scope.Doc).FeatureByName("旋转马达1") as IFeature;
                if(f!=null) { var m=f.GetDefinition() as ISimulationMotorFeatureData; if(m!=null) {Log("MOTOR_FALLBACK "+m.Magnitude);motors.Add(m);} }
            }
            if(motors.Count>1||(motors.Count==1&&Math.Abs(motors[0].Magnitude-2*Math.PI)>1e-5)) throw new Exception("FIXTURE_MOTOR_CHANGED count="+motors.Count);
            scope.Study.SetDuration(duration); ((IMotionStudyProperties)scope.Study.GetProperties(4)).SetFrameRate(fps);
            Log("SOLVE_BEGIN "+runId);
            if(!scope.Study.Calculate()) throw new Exception("SOLVER_FAILED");
            var result=(IMotionStudyResults)scope.Study.GetResults(4);
            if(result==null||result.IsOutOfDate()) throw new Exception("RESULTS_STALE");
            int n=(int)Math.Round(duration*fps)+1;
            var poses=Transforms(scope.Doc).Keys.ToDictionary(k=>k,k=>new double[n][]);
            var times=new double[n];
            string dir=Path.Combine(Root,"runs",runId); Directory.CreateDirectory(dir);
            using(var csv=new StreamWriter(Path.Combine(dir,"trajectory.csv"))) {
                csv.WriteLine("frame,time_s,set_time_argument_s,slider_x_m,expected_slider_x_m,crank_angle_deg");
                for(int i=0;i<n;i++) {
                    scope.EnsureActive();
                    double t=(double)i/fps; times[i]=t;
                    scope.Study.SetTime(Argument(t,duration)); Application.DoEvents();
                    var trans=Transforms(scope.Doc); foreach(var kv in trans) poses[kv.Key][i]=kv.Value;
                    double theta=Math.PI/6+2*Math.PI*t;
                    double expected=.02*Math.Cos(theta)+Math.Sqrt(.08*.08-.02*.02*Math.Sin(theta)*Math.Sin(theta));
                    double crank=Math.Atan2(trans["crank-1"][1],trans["crank-1"][0]);
                    double angleError=Math.Abs(Math.Atan2(Math.Sin(crank-theta),Math.Cos(crank-theta)));
                    double positionError=Math.Abs(trans["slider-1"][9]-expected);
                    maxPositionError=Math.Max(maxPositionError,positionError); maxCrankError=Math.Max(maxCrankError,angleError);
                    csv.WriteLine(string.Join(",",new[]{(double)i,t,Argument(t,duration),trans["slider-1"][9],expected,crank*180/Math.PI}.Select(v=>v.ToString("R",CultureInfo.InvariantCulture))));
                }
            }
            if(assembly=="parameter_trial"&&poses[Obstacle(scope.Doc).Name2].Any(p=>p.Zip(Pose(parameterValueMm/1000,0,0,0),(a,b)=>Math.Abs(a-b)).Max()>1e-8))throw new Exception("PARAMETER_NOT_APPLIED_TO_SOLVER");
            if(maxPositionError>1e-5||maxCrankError>1e-4) throw new Exception("TRAJECTORY_VALIDATION_FAILED position_m="+maxPositionError+" angle_rad="+maxCrankError);
            if(result.IsOutOfDate()) throw new Exception("RESULTS_STALE");
            run=new Run { Id=runId,Assembly=assembly,EditVersion=assembly=="parameter_trial"?parameterVersion:0,Path=scope.Doc.GetPathName(),Study=studyName,Fingerprint=Fingerprint(scope.Doc,scope.DocumentPath),Duration=duration,Fps=fps,Directory=dir,Times=times,Poses=poses };
        } finally { scope.Dispose(); }
        if(!scope.Restored) throw new Exception("RESTORATION_FAILED delta="+scope.RestoreDelta);
        runs.Add(runId,run);
        var summary=new { run_id=runId,assembly=assembly,study=studyName,duration_s=duration,output_fps=fps,frames=run.Times.Length,
            maximum_position_error_m=maxPositionError,maximum_crank_angle_error_rad=maxCrankError,restoration=new { status="restored",maximum_transform_delta=scope.RestoreDelta },
            trajectory_csv=Path.Combine(run.Directory,"trajectory.csv"),fingerprint=run.Fingerprint };
        File.WriteAllText(Path.Combine(run.Directory,"solve.json"),Json.Serialize(summary)); return summary;
    }
    Run GetRun(string id) { Run r; if(!runs.TryGetValue(id,out r)) {if(System.Text.RegularExpressions.Regex.IsMatch(id??"","^[a-f0-9]{32}$")){string path=Path.Combine(Root,"runs",id,"solve.json");if(File.Exists(path)){var saved=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));if(saved.ContainsKey("probe_input_scope"))throw new CadFault("PROBE_RUN_REQUIRES_HISTORY_MODE","隔离探测结果已保存，请以离线历史模式读取摘要或曲线。",new{run_id=id,probe_input_scope=saved["probe_input_scope"],required_parameter="allow_unverified_history",required_value=true,offline_tools=new[]{"get_run_artifacts","read_run_poses","get_motion_summary","export_motion_curve"},current_model_validity="not_checked_offline",cad_replay_allowed=false});}}throw new Exception("RUN_NOT_FOUND_OR_EXECUTOR_RESTARTED");}if(r.Generic)GetUserModel(r.Assembly);ConfigureModel(r.Assembly);if(r.Assembly=="gear_phase"&&r.ModelRoot!=null)pumpRootOverride=r.ModelRoot;return r; }
    void ValidateRun(Run r,Scope scope) {
        if(r.Generic&&r.EditVersion!=GetUserModel(r.Assembly).Revision||r.Assembly=="parameter_trial"&&r.EditVersion!=parameterVersion||Fingerprint(scope.Doc,scope.DocumentPath)!=r.Fingerprint) throw new Exception("MODEL_REVISION_CHANGED");
        var result=(IMotionStudyResults)scope.Study.GetResults(4);
        if(result==null||result.IsOutOfDate()) throw new Exception("RESULTS_STALE");
        if(Math.Abs(scope.Study.GetDuration()-r.Duration)>1e-8||((IMotionStudyProperties)scope.Study.GetProperties(4)).GetFrameRate()!=r.Fps) throw new Exception("STUDY_SETTINGS_CHANGED");
    }
    public object Measure(string id,string entity,string type,string component) {
        var r=GetRun(id);if(r.Assembly=="gear_pump"||r.Assembly=="gear_phase")return MeasurePump(r,entity,type,component); var scope=new Scope(this,r.Path,r.Study); object summary=null;
        try {
            ValidateRun(r,scope);
            int axis; string unit; double scale=1;
            if(type=="linear_velocity"&&entity=="slider-1"&&component=="x") {
                axis=7;unit="m/s";
                var units=((Array)scope.Doc.GetUnits()).Cast<object>().Select(Convert.ToInt32).ToArray();
                Log("MEASURE_DOCUMENT_LENGTH_UNIT "+units[0]);
                if(units[0]!=0) throw new Exception("UNCALIBRATED_DOCUMENT_UNITS");
                // GetValues has returned both mm/s and m/s across documents in this session.
                // Choose only after checking the whole curve against this registered fixture's analytic solution.
            } else if(type=="angular_velocity"&&entity=="crank-1"&&component=="magnitude") { axis=10;unit="deg/s"; }
            else throw new Exception("UNSUPPORTED_MEASURE: supported slider linear x and crank angular magnitude");
            int cmp=component=="x"?0:component=="y"?1:component=="z"?2:component=="magnitude"?3:-1; if(cmp<0) throw new Exception("UNSUPPORTED_COMPONENT");
            var c=((object[])((IAssemblyDoc)scope.Doc).GetComponents(false)).Cast<IComponent2>().FirstOrDefault(v=>v.Name2==entity);
            if(c==null) throw new Exception("ENTITY_NOT_FOUND");
            var cosmos=(ICosmosMotionStudyResults)scope.Study.GetResults(4);
            var pf=(IMotionPlotFeatureData)cosmos.CreatePlotFeatureData(); var x=(IMotionPlotAxisFeatureData)cosmos.CreatePlotXAxisFeatureData(); x.Type=0;
            var y=(IMotionPlotAxisFeatureData)cosmos.CreatePlotYAxisFeatureData(); y.Type=axis;y.Component=cmp;y.Entities=new DispatchWrapper[]{new DispatchWrapper(Faces(c).First())};
            var output=cosmos.GetValues(pf,x,new DispatchWrapper[]{new DispatchWrapper(y)}) as IMotionPlotFeatureOutput;
            if(output==null) throw new Exception("MEASURE_UNAVAILABLE"); var times=(double[])output.GetXAxis();var values=(double[])output.GetYAxis(y);
            if(times.Length!=r.Times.Length||values.Length!=times.Length||values.Any(v=>double.IsNaN(v)||double.IsInfinity(v))||times.Zip(r.Times,(a,b)=>Math.Abs(a-b)).Max()>1e-8) throw new Exception("INCOMPLETE_MEASURE");
            double referenceError;
            if(axis==7) {
                Func<double,double> expected=t=>{double a=Math.PI/6+2*Math.PI*t;return -.02*2*Math.PI*Math.Sin(a)-.02*.02*2*Math.PI*Math.Sin(a)*Math.Cos(a)/Math.Sqrt(.08*.08-.02*.02*Math.Sin(a)*Math.Sin(a));};
                double errorSI=values.Zip(times,(v,t)=>Math.Abs(v-expected(t))).Max();
                double errorMM=values.Zip(times,(v,t)=>Math.Abs(v*.001-expected(t))).Max();
                scale=errorMM<errorSI ? .001 : 1; referenceError=Math.Min(errorSI,errorMM);
                if(referenceError>2e-5) throw new Exception("MEASURE_UNIT_OR_REFERENCE_MISMATCH");
            } else { referenceError=values.Max(v=>Math.Abs(v-360)); if(referenceError>.01) throw new Exception("ANGULAR_REFERENCE_MISMATCH"); }
            Log("MEASURE_CALIBRATION scale="+scale+" reference_error="+referenceError);
            string rawCsv=Path.Combine(r.Directory,entity+"_"+type+"_"+component+"_raw.csv");
            using(var writer=new StreamWriter(rawCsv)) {writer.WriteLine("time_s,value_raw");for(int i=0;i<times.Length;i++) writer.WriteLine(times[i].ToString("R",CultureInfo.InvariantCulture)+","+values[i].ToString("R",CultureInfo.InvariantCulture));}
            values=values.Select(v=>v*scale).ToArray();
            string csv=Path.Combine(r.Directory,entity+"_"+type+"_"+component+".csv");
            using(var writer=new StreamWriter(csv)) { writer.WriteLine("time_s,value_"+unit.Replace("/","_per_")); for(int i=0;i<times.Length;i++) writer.WriteLine(times[i].ToString("R",CultureInfo.InvariantCulture)+","+values[i].ToString("R",CultureInfo.InvariantCulture)); }
            int peak=Array.IndexOf(values,values.Max()); int absolute=Array.IndexOf(values,values.OrderByDescending(v=>Math.Abs(v)).First());
            summary=new { run_id=id,entity=entity,measure_type=type,component=component,coordinate_frame="assembly_global",unit=unit,sample_count=times.Length,min=values.Min(),max=values.Max(),
                peak_time_s=times[peak],max_absolute=Math.Abs(values[absolute]),max_absolute_time_s=times[absolute],mean=values.Average(),mean_definition="sample arithmetic mean",csv_path=csv,raw_csv_path=rawCsv,
                unit_calibration=new { raw_to_output_scale=scale,maximum_reference_error=referenceError,method="analytic_reference_for_registered_fixture_only" },restoration_status="restored" };
        } finally { scope.Dispose(); }
        if(!scope.Restored) throw new Exception("RESTORATION_FAILED"); return summary;
    }
    public object CheckMotion(string id,int frameStep,double volumeThreshold) {
        var scanTimer=System.Diagnostics.Stopwatch.StartNew();
        var r=GetRun(id); if(frameStep<1||frameStep>r.Times.Length||double.IsNaN(volumeThreshold)||double.IsInfinity(volumeThreshold)||volumeThreshold<0) throw new Exception("INVALID_SAMPLING_OPTIONS");
        var scope=new Scope(this,r.Path,r.Study); var events=new List<object>(); int count=0; double maxDelta=0;
        var excludedPairs=r.Assembly=="gear_pump"||r.Assembly=="gear_phase"?new string[0]:new[]{"base-1|crank-1","crank-1|rod-1","rod-1|slider-1"};
        var indices=Enumerable.Range(0,r.Times.Length).Where(i=>i%frameStep==0).Concat(new[]{r.Times.Length-1}).Distinct().OrderBy(i=>i).ToArray();
        try {
            ValidateRun(r,scope);
            foreach(int i in indices) {
                Log("SCAN_FRAME_BEGIN run="+id+" frame="+i+" of="+r.Times.Length);Progress(activeJobId,"native_manager_scan",count,indices.Length,id);
                scope.EnsureActive();
                scope.Study.SetTime(Argument(r.Times[i],r.Duration)); Application.DoEvents();var actual=Transforms(scope.Doc);
                double delta=actual.Max(k=>k.Value.Zip(r.Poses[k.Key][i],(a,b)=>Math.Abs(a-b)).Max());maxDelta=Math.Max(maxDelta,delta);
                if(delta>1e-7) throw new Exception("POSE_MISMATCH frame="+i);
                var mgr=(IInterferenceDetectionMgr)((IAssemblyDoc)scope.Doc).InterferenceDetectionManager;
                try {
                    mgr.TreatCoincidenceAsInterference=false;mgr.IgnoreHiddenBodies=false;
                    var ints=mgr.GetInterferences() as object[];
                    if(ints!=null) foreach(IInterference interference in ints) {
                        var names=((object[])interference.Components).Cast<IComponent2>().Select(c=>c.Name2).OrderBy(n=>n).ToArray();
                        string pair=string.Join("|",names); bool excluded=excludedPairs.Contains(pair);
                        double volume=interference.Volume*1e9;
                        if(!excluded && volume>volumeThreshold) events.Add(new { event_id="event_"+events.Count,frame=i,time_s=r.Times[i],parts=names,volume_mm3=volume });
                    }
                    count++;
                    Progress(activeJobId,"native_manager_scan",count,indices.Length,id);
                } finally { mgr.Done(); }
                Log("SCAN_FRAME_DONE run="+id+" frame="+i+" accumulated_events="+events.Count);
            }
            ValidateRun(r,scope);
        } finally { scope.Dispose(); }
        if(!scope.Restored) throw new Exception("RESTORATION_FAILED");
        string path=Path.Combine(r.Directory,"interference-step-"+frameStep+".json");
        var report=new { run_id=id,assertion=events.Count==0?"pass":"fail",claim="discrete_sampled_frames_only",continuous_collision=false,checked_frames=count,total_output_frames=r.Times.Length,
            checked_frame_indices=indices,maximum_time_step_s=(double)frameStep/r.Fps,volume_threshold_mm3=volumeThreshold,
            excluded_joint_pairs=excludedPairs,events=events,
            first_detected_event=events.FirstOrDefault(),maximum_pose_difference=maxDelta,restoration_status="restored",engine="native_interference_manager",elapsed_s=scanTimer.Elapsed.TotalSeconds,report_path=path };
        File.WriteAllText(path,Json.Serialize(report));
        reports[id]=path;
        return new { run_id=id,assertion=events.Count==0?"pass":"fail",claim="discrete_sampled_frames_only",checked_frames=count,event_count=events.Count,
            first_detected_event=events.FirstOrDefault(),maximum_time_step_s=(double)frameStep/r.Fps,restoration_status="restored",engine="native_interference_manager",elapsed_s=scanTimer.Elapsed.TotalSeconds,report_path=path };
    }
    public object Dispatch(Dictionary<string,object> request) {
        LastOperationRestoration="not_required";
        LastContextRestoration="not_required";
        string op=(string)request["op"];var p=(Dictionary<string,object>)request["params"];
        activeJobId=p.ContainsKey("job_id")?(string)p["job_id"]:null;activeRequestId=request.ContainsKey("id")?request["id"] as string:null;
        switch(op) {
            case "_survey_assembly_connections": return SurveyAssemblyConnections((string)p["model_id"]);
            case "_preview_assembly_connections": return PreviewAssemblyConnections((string)p["model_id"],(string)p["proposal_json"]);
            case "_apply_assembly_connections": return ApplyAssemblyConnections((string)p["plan_id"],Convert.ToBoolean(p["confirmed"]));
            case "_test_connection_rollback": return ApplyAssemblyConnections((string)p["plan_id"],true,true);
            case "_test_connection_suppression": return TestConnectionSuppression((string)p["model_id"],Convert.ToInt32(p["native_feature_id"]));
            case "_probe_assembly_connection_pose": return ProbeAssemblyConnectionPose((string)p["model_id"],(string)p["component_id"],(string)p["target_json"],(string)p["checkpoint_id"],(string)p["probe_id"],p.ContainsKey("goal_index")?Convert.ToInt32(p["goal_index"]):-1,p.ContainsKey("allowed_trial")&&Convert.ToBoolean(p["allowed_trial"]));
            case "_survey_external_gear_pair": return SurveyExternalGearPair((string)p["model_id"],p.ContainsKey("include_completion_references")&&Convert.ToBoolean(p["include_completion_references"]));
            case "_preview_external_gear_pair": return PreviewExternalGearPair((string)p["model_id"],(string)p["recommendation_json"],Convert.ToDouble(p["numerator"]),Convert.ToDouble(p["denominator"]));
            case "_apply_external_gear_pair": return ApplyExternalGearPair((string)p["plan_id"],Convert.ToBoolean(p["confirmed"]));
            case "_test_external_gear_rollback": return ApplyExternalGearPair((string)p["plan_id"],true,true);
            case "_preview_gear_transmission": return PreviewGearTransmission((string)p["model_id"]);
            case "_apply_gear_transmission": return ApplyGearTransmission((string)p["plan_id"],Convert.ToBoolean(p["confirmed"]));
            case "_test_gear_transmission_rollback": return ApplyGearTransmission((string)p["plan_id"],true,true);
            case "get_environment": return UserEnvironment();
            case "list_mate_references": return ListMateReferences((string)p["model_id"],(string)p["component_id"],(string)p["kind"],Convert.ToInt32(p["limit"]),(string)p["cursor"],p.ContainsKey("detail_level")&&(string)p["detail_level"]=="compact",p.ContainsKey("face_offset")?Convert.ToInt32(p["face_offset"]):0,p.ContainsKey("mate_context_budget_s")?Convert.ToDouble(p["mate_context_budget_s"]):10,p.ContainsKey("geometry_scan_budget_s")?Convert.ToDouble(p["geometry_scan_budget_s"]):10,p.ContainsKey("edge_offset")?Convert.ToInt32(p["edge_offset"]):0);
            case "_circular_reference_state": {var model=GetUserModel((string)p["model_id"]);using(var scope=new Scope(this,model.Path,null))return CircularQueryState(model,scope.Doc);}
            case "preview_mate": return PreviewBasicMate((string)p["model_id"],(string)p["entity_a"],(string)p["entity_b"],(string)p["mate_type"],(string)p["alignment"],Convert.ToDouble(p["distance_mm"]),Convert.ToBoolean(p["lock_rotation"]),(string)p["baseline_run_id"],p.ContainsKey("maximum_translation_mm")?Convert.ToDouble(p["maximum_translation_mm"]):1,p.ContainsKey("maximum_rotation_deg")?Convert.ToDouble(p["maximum_rotation_deg"]):1);
            case "apply_mate": return ApplyBasicMate((string)p["plan_id"],Convert.ToBoolean(p["confirmed"]));
            case "verify_motion_preservation": return VerifyRequestedMotion((string)p["model_id"],(string)p["study"],(string)p["component_id"],(string)p["entity_id"],(string)p["expected_motion"],Convert.ToDouble(p["minimum_travel"]),Convert.ToDouble(p["duration_s"]),Convert.ToInt32(p["output_fps"]),(string)p["run_id"],(string)p["plan_id"],p.ContainsKey("reference_component_id")?(string)p["reference_component_id"]:"");
            case "_test_mate_rollback": return ApplyBasicMate((string)p["plan_id"],true,true);
            case "_import_gear_assembly": return ImportGearAssembly((string)p["path"],p.ContainsKey("materialize_virtual_components")&&Convert.ToBoolean(p["materialize_virtual_components"]),p.ContainsKey("import_id")?(string)p["import_id"]:null);
            case "_import_constraint_assembly": return ImportConstraintAssembly((string)p["path"],p.ContainsKey("materialize_virtual_components")&&Convert.ToBoolean(p["materialize_virtual_components"]),p.ContainsKey("import_id")?(string)p["import_id"]:null);
            case "import_assembly": return ImportUserAssembly((string)p["path"],p.ContainsKey("configuration")?(string)p["configuration"]:null,null,null,p.ContainsKey("import_id")?(string)p["import_id"]:null,p.ContainsKey("materialize_virtual_components")&&Convert.ToBoolean(p["materialize_virtual_components"]));
            case "list_models": return UserListModels();
            case "inspect_model": return InspectUserModel((string)p["model_id"],p.ContainsKey("detail_level")?(string)p["detail_level"]:"full");
            case "list_motion_studies": return UserStudies((string)p["model_id"],p.ContainsKey("inspect_native_drives")&&Convert.ToBoolean(p["inspect_native_drives"]));
            case "probe_motion_compatibility": return ProbeUserCompatibility((string)p["model_id"],(string)p["study"],Convert.ToDouble(p["duration_s"]),Convert.ToInt32(p["output_fps"]),(string)p["run_id"],p.ContainsKey("checkpoint_id")?(string)p["checkpoint_id"]:"");
            case "preflight_motion": return PreflightUserMotion((string)p["model_id"],p.ContainsKey("study")?(string)p["study"]:null);
            case "list_drive_candidates": return UserDriveCandidates((string)p["model_id"],p.ContainsKey("component_id")?(string)p["component_id"]:"",p.ContainsKey("kind")?(string)p["kind"]:"",p.ContainsKey("limit")?Convert.ToInt32(p["limit"]):20,p.ContainsKey("cursor")?(string)p["cursor"]:null,p.ContainsKey("group_faces")?Convert.ToBoolean(p["group_faces"]):true,p.ContainsKey("detail_level")&&(string)p["detail_level"]=="compact",p.ContainsKey("face_offset")?Convert.ToInt32(p["face_offset"]):0,p.ContainsKey("mate_context_budget_s")?Convert.ToDouble(p["mate_context_budget_s"]):10,p.ContainsKey("geometry_scan_budget_s")?Convert.ToDouble(p["geometry_scan_budget_s"]):10);
            case "create_motion_study": return CreateUserStudy((string)p["model_id"],(string)p["study"],(string)p["component_id"],(string)p["entity_id"],(string)p["motor_type"],Convert.ToDouble(p["speed"]),Convert.ToBoolean(p["reverse_direction"]),p.ContainsKey("reference_component_id")?(string)p["reference_component_id"]:"",p.ContainsKey("duration_s")?Convert.ToDouble(p["duration_s"]):1,p.ContainsKey("output_fps")?Convert.ToInt32(p["output_fps"]):30);
            case "convert_motion_study": return ConvertUserStudy((string)p["model_id"],(string)p["study"]);
            case "run_user_study": return RunUserStudy((string)p["model_id"],(string)p["study"],Convert.ToDouble(p["duration_s"]),Convert.ToInt32(p["output_fps"]),(string)p["run_id"],false,p.ContainsKey("allow_native_grid_subset")&&p["allow_native_grid_subset"] is bool&&(bool)p["allow_native_grid_subset"]);
            case "get_motion_summary": return UserRunSummary((string)p["run_id"]);
            case "export_motion_curve": return ExportUserCurve((string)p["run_id"],(string)p["component_id"],(string)p["quantity"],(string)p["axis"]);
            case "replay_motion_frame": if(p.ContainsKey("use_input_snapshot")&&Convert.ToBoolean(p["use_input_snapshot"]))return ReplayFrozenSnapshot((string)p["run_id"],Convert.ToInt32(p["frame"]));return ReplayUserFrame((string)p["run_id"],Convert.ToInt32(p["frame"]),p.ContainsKey("diagnostic_limit")?Convert.ToInt32(p["diagnostic_limit"]):20);
            case "create_model_checkpoint": return CreateUserCheckpoint((string)p["model_id"]);
            case "reset_study_time": if(p.ContainsKey("reset_output_fps")&&Convert.ToInt32(p["reset_output_fps"])>0){if(!p.ContainsKey("create_new_model")||!Convert.ToBoolean(p["create_new_model"]))throw new Exception("RESET_FPS_REQUIRES_NEW_MODEL");return ResetStudyInNewModel((string)p["model_id"],(string)p["study"],Convert.ToInt32(p["reset_output_fps"]),p.ContainsKey("allow_recalculate")&&Convert.ToBoolean(p["allow_recalculate"]),p.ContainsKey("checkpoint_id")?(string)p["checkpoint_id"]:"");}return ResetUserStudyTime((string)p["model_id"],(string)p["study"],p.ContainsKey("allow_recalculate")&&Convert.ToBoolean(p["allow_recalculate"]));
            case "restore_model_checkpoint": try{return RestoreUserCheckpoint((string)p["model_id"],(string)p["checkpoint_id"]);}catch{LastOperationRestoration="unknown";throw;}
            case "get_capabilities": return Capabilities();
            case "inspect_assembly": return Inspect((string)p["assembly"]);
            case "list_studies": return ListStudies((string)p["assembly"]);
            case "list_entities": return PumpEntities((string)p["assembly"]);
            case "check_interference": return StaticCheck((string)p["assembly"],Convert.ToDouble(p["volume_threshold_mm3"]));
            case "run_study": return Solve((string)p["assembly"],(string)p["study"],Convert.ToDouble(p["duration_s"]),Convert.ToInt32(p["output_fps"]),(string)p["run_id"]);
            case "query_measure": return Measure((string)p["run_id"],(string)p["entity"],(string)p["measure_type"],(string)p["component"]);
            case "check_interference_during_motion": return p.ContainsKey("engine")&&(string)p["engine"]=="hybrid"?FastCheck((string)p["run_id"],Convert.ToInt32(p["frame_step"]),Convert.ToDouble(p["volume_threshold_mm3"]),activeJobId):CheckMotion((string)p["run_id"],Convert.ToInt32(p["frame_step"]),Convert.ToDouble(p["volume_threshold_mm3"]));
            case "diagnose_gear_phase": ConfigureModel("gear_pump");return DiagnosePhase();
            case "create_phase_experiment": return CreatePhase(Convert.ToDouble(p["phase_offset_deg"]));
            case "get_event_detail": return EventDetail((string)p["run_id"],(string)p["event_id"],false);
            case "locate_event": return EventDetail((string)p["run_id"],(string)p["event_id"],true);
            case "verify_exception_restoration": return VerifyExceptionRestoration((string)p["run_id"]);
            case "create_parameter_experiment": return CreateParameterExperiment();
            case "list_editable_parameters": return EditableParameters();
            case "create_checkpoint": return CreateCheckpoint();
            case "set_parameter": return SetParameter((string)p["parameter"],Convert.ToDouble(p["value_mm"]));
            case "restore_checkpoint": return RestoreCheckpoint((string)p["checkpoint_id"]);
            case "run_parameter_search": return ParameterSearch(Convert.ToInt32(p["max_trials"]),Convert.ToDouble(p["time_budget_s"]));
            case "_test_executor_loss": return TestExecutorLoss((string)p["run_id"]);
            case "_test_history_state": return TestHistoryState((string)p["model_id"],(string)p["study"],(string)p["mode"],p.ContainsKey("fps")?Convert.ToInt32(p["fps"]):0);
            case "_test_run_restoration_failure": if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TESTS_DISABLED");return RunUserStudy((string)p["model_id"],(string)p["study"],Convert.ToDouble(p["duration_s"]),Convert.ToInt32(p["output_fps"]),(string)p["run_id"],true);
            case "_test_set_study_time": if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TESTS_DISABLED");return TestSetUserStudyTime((string)p["model_id"],(string)p["study"],Convert.ToDouble(p["time_s"]));
            default: throw new Exception("UNKNOWN_OPERATION");
        }
    }
}

