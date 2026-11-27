using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    class ApertureResult {
        public string Model, Study, OriginalStudy, OriginalModelTab;
        public string DiscardCheckpoint;
        public Dictionary<string,double[]> Initial;
        public Dictionary<int,bool> MateMask;
    }

    ApertureResult apertureCandidate;

    static void ApertureRequire(bool condition, string reason) {
        if(!condition)throw new CadFault("CONNECTION_EVIDENCE_FAILED","开口仿真未通过原生校验。",new{reason});
    }

    public object ApertureVertices(string modelId, string[] ids) {
        var model=GetUserModel(modelId);
        using(var scope=new Scope(this,model.Path,null)) {
            var doc=scope.Doc;
            ApertureRequire(ids.Length==4&&ids.Distinct().Count()==4,"four_unique_outputs_required");
            return new{outputs=ids.Select(id=>{
                var c=ResolveUserComponent(model,doc,id);
                ApertureRequire(!c.IsFixed()&&!c.IsSuppressed(),"floating_jaw_required");
                var points=SolidBodies(c).SelectMany(body=>(body.GetVertices() as object[]??new object[0]).Cast<IVertex>())
                    .Take(2001).Select(v=>(double[])v.GetPoint()).ToArray();
                ApertureRequire(points.Length>0&&points.Length<=2000,"jaw_vertices_empty_or_exceeds_read_limit");
                return new{component_id=id,instance=c.Name2,local_points_m=points};
            }).ToArray()};
        }
    }

    string PutApertureBack(UserModel model, ApertureResult state, bool keep) {
        var doc=(IModelDoc2)Sw.GetOpenDocumentByName(model.Path);
        ApertureRequire(doc!=null,"aperture_document_lost");
        var manager=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();
        var trial=(IMotionStudy)manager.GetMotionStudy(state.Study);
        ApertureRequire(trial!=null&&trial.IsActive,"aperture_candidate_changed");
        trial.Stop();trial.SetTime(0);Application.DoEvents();
        ApertureRequire(Math.Abs(trial.GetTime())<1e-8,"aperture_zero_clock_failed");
        VerifyUserSources(model);
        if(keep) {
            VerifyNewStudyMateState(doc,state.MateMask,state.Initial,"before_saving_aperture_study");
            Save(doc,model.Path);
            var active=(IMotionStudy)((IMotionStudyManager)doc.Extension.GetMotionStudyManager()).GetMotionStudy(state.Study);
            var results=active==null?null:(IMotionStudyResults)active.GetResults(4);
            ApertureRequire(active!=null&&results!=null&&!results.IsOutOfDate()&&Math.Abs(active.GetTime())<1e-8,"saved_aperture_results_not_current");
        } else {
            if(state.OriginalModelTab!=null) {
                ApertureRequire(!Names(manager).Contains(state.OriginalModelTab)&&manager.ActivateMotionStudy(state.OriginalModelTab)&&
                    !StudyStates(doc).Any(s=>s.active),"aperture_original_model_tab_activation_failed");
            } else {
                var previous=(IMotionStudy)manager.GetMotionStudy(state.OriginalStudy);
                ApertureRequire(previous!=null&&previous.Activate()&&previous.IsActive,"aperture_original_study_activation_failed");
                ApertureRequire(Math.Abs(previous.GetTime())<1e-8,"original_study_clock_changed");
            }
            VerifyNewStudyMateState(doc,state.MateMask,state.Initial,"after_restoring_original_tab");
            ApertureRequire(manager.DeleteMotionStudy(state.Study),"aperture_probe_removal_failed");
        }
        VerifyNewStudyMateState(doc,state.MateMask,state.Initial,keep?"after_saving_aperture_study":"after_removing_aperture_probe");
        VerifyUserSources(model);
        apertureCandidate=null;
        LastOperationRestoration="restored";
        return FileHash(model.Path);
    }

    void VerifyApertureDiscardCheckpoint(UserModel model,IModelDoc2 doc,string checkpoint) {
        ApertureRequire(System.Text.RegularExpressions.Regex.IsMatch(checkpoint??"","^[a-f0-9]{32}$"),"aperture_discard_checkpoint_required");
        var directory=Path.Combine(model.Directory,"checkpoints",checkpoint);
        var saved=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(OwnedPath(Path.Combine(directory,"checkpoint.json"),"user_assemblies")));
        var files=(Dictionary<string,object>)saved["files"];
        ApertureRequire((string)saved["model_id"]==model.Id&&(string)saved["configuration"]==model.Configuration&&
            files.Count==model.Files.Length&&model.Files.All(path=>files.ContainsKey(path)&&FileHash(path)==(string)files[path])&&
            (string)saved["mate_parameters"]==ImportMateParameters(doc)&&Json.Serialize(saved["studies"])==Json.Serialize(StudyStates(doc)),
            "aperture_discard_checkpoint_state_mismatch");
        var before=Json.Deserialize<Dictionary<string,double[]>>(Json.Serialize(saved["poses"]));
        var actual=Transforms(doc);
        ApertureRequire(before.Count==actual.Count&&before.All(p=>actual.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,actual[p.Key])),
            "aperture_discard_checkpoint_pose_mismatch");
    }

    void RestoreApertureDiscard(ApertureResult state) {
        try {
            RestoreUserCheckpoint(state.Model,state.DiscardCheckpoint);
            var model=GetUserModel(state.Model);
            using(var scope=new Scope(this,model.Path,null)) {
                var manager=(IMotionStudyManager)scope.Doc.Extension.GetMotionStudyManager();
                ApertureRequire(!Names(manager).Contains(state.Study),"aperture_probe_still_present_after_checkpoint_restore");
                VerifyNewStudyMateState(scope.Doc,state.MateMask,state.Initial,"after_restoring_aperture_checkpoint");
            }
            VerifyUserSources(model);
            apertureCandidate=null;
            LastOperationRestoration="restored";
        } catch {LastOperationRestoration="unknown";throw;}
    }

    public object RunApertureCycle(string modelId, string driverId, string referenceId, string entityId, bool reverse,
        double strokeMm, int frameStep, bool candidate, string runId, string jobId,string discardCheckpoint) {
        ApertureResult discard=null;
        object result;
        try {
            result=RunApertureTrial(modelId,driverId,referenceId,entityId,reverse,strokeMm,frameStep,candidate,runId,jobId,discardCheckpoint,ref discard);
        } catch(Exception failure) {
            if(discard!=null&&LastContextRestoration!="unknown") {
                try {RestoreApertureDiscard(discard);}
                catch(Exception cleanup) {
                    throw new CadFault("RESTORATION_FAILED","开口试算失败后未能核验检查点恢复。",new{
                        original_failure=FailureEvidence(failure),cleanup_failure=FailureEvidence(cleanup)});
                }
            }
            throw;
        }
        if(discard!=null)RestoreApertureDiscard(discard);
        return result;
    }

    object RunApertureTrial(string modelId,string driverId,string referenceId,string entityId,bool reverse,double strokeMm,
        int frameStep,bool candidate,string runId,string jobId,string discardCheckpoint,ref ApertureResult discard) {
        ApertureRequire(System.Text.RegularExpressions.Regex.IsMatch(runId??"","^[a-f0-9]{32}$")&&!Double.IsNaN(strokeMm)&&!Double.IsInfinity(strokeMm)&&strokeMm>0&&strokeMm<=20&&
            (candidate?frameStep==1:frameStep==5),"aperture_trial_parameters_out_of_bounds");
        var model=GetUserModel(modelId);
        ApertureRequire(apertureCandidate==null,"another_aperture_candidate_requires_finalization");
        LoadUserMotion();
        using(var scope=new Scope(this,model.Path,null)) {
            var doc=scope.Doc;
            var manager=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();
            var existing=Names(manager).Select(n=>(IMotionStudy)manager.GetMotionStudy(n)).ToArray();
            var original=existing.SingleOrDefault(s=>s.IsActive);
            ApertureRequire(original==null||Math.Abs(original.GetTime())<1e-8,"saved_zero_time_required");
            // A zero-clock historical study can reapply its old mate mask.
            // A probe started in model view must return to that model view.
            var modelTab=original==null?ConnectionModelTab():null;
            ApertureRequire(modelTab==null||!Names(manager).Contains(modelTab),"aperture_model_tab_ambiguous");
            var components=UserComponents(doc);
            ApertureRequire(components.Length>=6&&components.Length<=128&&components.All(c=>!c.IsSuppressed()&&c.GetModelDoc2() is IPartDoc),"aperture_requires_flat_resolved_parts");
            var moving=ResolveUserComponent(model,doc,driverId);
            var support=ResolveUserComponent(model,doc,referenceId);
            string persistent;
            int status;
            ApertureRequire(model.Entities.TryGetValue(entityId,out persistent),"aperture_drive_entity_missing");
            var face=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(persistent),out status) as IFace2;
            var owner=face==null?null:((IEntity)face).GetComponent() as IComponent2;
            ApertureRequire(status==0&&owner!=null&&owner.Name2==moving.Name2&&!moving.IsFixed()&&support.IsFixed()&&((ISurface)face.GetSurface()).IsPlane(),"aperture_drive_binding_changed");
            var directory=Path.Combine(Root,"runs",runId);
            ApertureRequire(!Directory.Exists(directory),"aperture_run_id_already_used");
            Directory.CreateDirectory(directory);
            var state=new ApertureResult{Model=model.Id,Study="Aperture_"+runId.Substring(0,12),OriginalStudy=original==null?null:original.Name,OriginalModelTab=modelTab,
                Initial=Transforms(doc),MateMask=EGAllMates(doc).ToDictionary(f=>f.GetID(),f=>EGSuppressed(f))};
            ApertureRequire(!Names(manager).Contains(state.Study),"aperture_study_already_exists");
            if(state.MateMask.Values.Any(s=>s)) {
                // Deleting a trial can activate an old study and overwrite the
                // known model mask. Discard by the sealed pre-trial file state.
                VerifyApertureDiscardCheckpoint(model,doc,discardCheckpoint);
                state.DiscardCheckpoint=discardCheckpoint;
            }
            var fixedNames=components.Where(c=>c.IsFixed()).Select(c=>c.Name2).ToArray();
            VerifyUserSources(model);
            var basePairs=NativePairTotals(doc,.001,new string[0]);
            bool created=false,discardAttempted=false;
            try {
                LastOperationRestoration="pending";
                Progress(jobId,"aperture_motor",0,0,runId);
                var study=(IMotionStudy)manager.CreateMotionStudy();
                ApertureRequire(study!=null,"aperture_study_creation_failed");
                study.Name=state.Study;
                created=true;
                ApertureRequire(study.Activate(),"aperture_study_activation_failed");
                study.StudyType=4;
                ApertureRequire(study.StudyType==4,"motion_analysis_required");
                VerifyNewStudyMateState(doc,state.MateMask,state.Initial,"aperture_study_before_calculate");
                var motor=(ISimulationMotorFeatureData)study.CreateDefinition(77);
                motor.DirectionReference=face;motor.Location=face;motor.ReverseDirection=reverse;motor.RelativeComponent=(Component2)support;
                motor.InterpolatedMotor((int)swSimulationMotorDriveType_e.swSimulationMotorDrive_Displacement,(int)swInterpolationType_e.swCubicInterpolation);
                var spline=Path.Combine(directory,"displacement.csv");
                File.WriteAllLines(spline,Enumerable.Range(0,41).Select(i=>ApertureNumber(i/10.0)+","+ApertureNumber(strokeMm*.0005*(1-Math.Cos(Math.PI*i/20.0)))));
                ApertureRequire(motor.LoadSplineData(spline),"aperture_spline_load_failed");
                var motorFeature=study.CreateFeature(motor) as IFeature;
                var readback=motorFeature==null?null:motorFeature.GetDefinition() as ISimulationMotorFeatureData;
                var relative=readback==null?null:readback.RelativeComponent as IComponent2;
                ApertureRequire(readback!=null&&relative!=null&&relative.Name2==support.Name2&&readback.ReverseDirection==reverse&&readback.MotionType==4&&readback.DriveType==0&&
                    Math.Abs(readback.GetInterpolatedValue(0))<1e-9&&Math.Abs(readback.GetInterpolatedValue(2)-strokeMm*.001)<1e-9&&Math.Abs(readback.GetInterpolatedValue(4))<1e-9,"aperture_motor_readback_failed");
                var properties=(IMotionStudyProperties)study.GetProperties(4);
                ApertureRequire((Math.Abs(study.GetDuration()-4)<1e-8||study.SetDuration(4))&&(properties.GetFrameRate()==10||properties.SetFrameRate(10)),"aperture_native_time_grid_rejected");
                Progress(jobId,"aperture_calculate",0,0,runId);
                ApertureRequire(study.Calculate(),"aperture_solver_failed");
                var results=(IMotionStudyResults)study.GetResults(4);
                ApertureRequire(results!=null&&!results.IsOutOfDate()&&properties.GetFrameRate()==10&&Math.Abs(study.GetDuration()-4)<1e-8,"aperture_solved_grid_unverified");
                var rows=new List<object>();
                var posesPath=Path.Combine(directory,"aperture-poses.csv");
                var interferences=Path.Combine(directory,"aperture-interference.json");
                IDictionary<string,double[]> lastPoses=null;
                try {
                    using(var writer=new StreamWriter(posesPath)) {
                        writer.WriteLine("frame,time_s,instance,x_m,y_m,z_m,r00,r01,r02,r10,r11,r12,r20,r21,r22");
                        for(int frame=0;frame<=40;frame+=frameStep) {
                            double time=frame/10.0;
                            Progress(jobId,"aperture_interference_sampling",frame/frameStep,40/frameStep+1,runId);
                            study.SetTime(Argument(time,4));Application.DoEvents();
                            ApertureRequire(Math.Abs(study.GetTime()-time)<1e-7&&!study.IsPlaying,"aperture_frame_clock_unverified");
                            var poses=Transforms(doc);
                            ApertureRequire(poses.Count==state.Initial.Count&&state.Initial.Keys.All(poses.ContainsKey),"aperture_fixed_component_or_scope_changed");
                            if(frame==0)AperturePoseReview.RequireEndpoint(frame,state.Initial,poses,directory,runId,strokeMm,AtomicJson);
                            if(frame==40)lastPoses=poses;
                            else ApertureRequire(fixedNames.All(n=>PoseValidation.Matches(state.Initial[n],poses[n])),"aperture_fixed_component_or_scope_changed");
                            foreach(var p in poses)writer.WriteLine(frame+","+ApertureNumber(time)+",\""+p.Key.Replace("\"","\"\"")+"\","+
                                string.Join(",",p.Value.Skip(9).Take(3).Concat(p.Value.Take(9)).Select(ApertureNumber)));
                            var intersections=NativePairTotals(doc,.001,new string[0]);
                            rows.Add(new{frame,time_s=time,new_or_increased=intersections.Where(p=>p.Value-(basePairs.ContainsKey(p.Key)?basePairs[p.Key]:0)>.01)
                                .ToDictionary(p=>p.Key,p=>p.Value)});
                        }
                    }
                    AtomicJson(interferences,new{baseline_mm3=basePairs,rows,threshold_mm3=.01});
                } catch(Exception evidenceFailure) {
                    if(lastPoses!=null&&(evidenceFailure is IOException||evidenceFailure is UnauthorizedAccessException))
                        AperturePoseReview.RequireEndpoint(40,state.Initial,lastPoses,directory,runId,strokeMm,AtomicJson);
                    throw;
                }
                AperturePoseReview.RequireEndpoint(40,state.Initial,lastPoses,directory,runId,strokeMm,AtomicJson,posesPath,interferences);
                study.SetTime(0);Application.DoEvents();
                VerifyNewStudyMateState(doc,state.MateMask,state.Initial,"aperture_trial_after_sampling_and_reset");
                VerifyUserSources(model);
                if(candidate)apertureCandidate=state;
                else if(state.DiscardCheckpoint!=null)discard=state;
                else {
                    discardAttempted=true;
                    PutApertureBack(model,state,false);
                }
                if(discard==null)LastOperationRestoration="restored";
                return new{run_id=runId,state.Study,poses_path=posesPath,interference_path=interferences,initial_restored=true,
                    driver=moving.Name2,reference=support.Name2,frame_count=40/frameStep+1,stroke_mm=strokeMm,restoration_status="restored"};
            } catch(Exception failure) {
                if(failure is COMException||failure is NativeCommandStateException) { scope.DeferRestoration(failure);LastOperationRestoration="unknown";throw; }
                if(!created||discardAttempted) { LastOperationRestoration="unknown";throw; }
                if(state.DiscardCheckpoint!=null) {discard=state;throw;}
                try { PutApertureBack(model,state,false); }
                catch(Exception cleanup) { scope.DeferRestoration(cleanup);LastOperationRestoration="unknown";throw new CadFault("RESTORATION_FAILED","算例失败后无法确认试算清理，保留现场。",new{original=failure.Message,cleanup=cleanup.Message,original_failure=FailureEvidence(failure),cleanup_failure=FailureEvidence(cleanup)}); }
                throw;
            }
        }
    }

    public object FinishApertureCycle(string modelId, string study, bool keep) {
        var model=GetUserModel(modelId);var state=apertureCandidate;
        ApertureRequire(state!=null&&state.Model==modelId&&state.Study==study,"aperture_candidate_binding_missing");
        LastOperationRestoration="pending";
        if(!keep&&state.DiscardCheckpoint!=null) {
            RestoreApertureDiscard(state);
            return new{study,saved=false,assembly_path=model.Path,sha256=FileHash(model.Path),restoration_status="restored"};
        }
        try { return new{study,saved=keep,assembly_path=model.Path,sha256=PutApertureBack(model,state,keep),restoration_status="restored"}; }
        catch { LastOperationRestoration="unknown";throw; }
    }

    static string ApertureNumber(double value){return value.ToString("R",CultureInfo.InvariantCulture);}
}
