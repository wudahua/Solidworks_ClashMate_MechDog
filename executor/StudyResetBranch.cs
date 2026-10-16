using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    // Explicit alternative when the old high-fps state cannot be proved recoverable:
    // edit a new registered branch, never overwrite the original model/checkpoint.
    public object ResetStudyInNewModel(string id,string studyName,int fps,bool allowRecalculate,string checkpointId="") {
        if(!allowRecalculate||fps<5||fps>1000)throw new CadFault("INVALID_RESET_BRANCH_OPTIONS","降低帧率归零须显式允许计算，并指定5–1000fps；仅在新副本执行。");
        if(!System.Text.RegularExpressions.Regex.IsMatch(checkpointId??"","^[a-f0-9]{32}$"))throw new CadFault("RESET_BRANCH_REQUIRES_CHECKPOINT","新副本归零须明确指定checkpoint_id；先创建检查点，再从该冻结输入创建新模型，不隐式保存当前脏内存。",new{required_tool="create_model_checkpoint",required_parameter="checkpoint_id"});
        var original=GetUserModel(id);string descriptor=Path.Combine(original.Directory,"checkpoints",checkpointId,"checkpoint.json");OwnedPath(descriptor,"user_assemblies");string descriptorHash=FileHash(descriptor);
        var data=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(descriptor));var source=Json.Deserialize<UserModel>(Json.Serialize(data["model"]));var hashes=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(data["files"]));
        if((string)data["model_id"]!=id||source.Id!=id||source.Configuration!=(string)data["configuration"]||!source.Files.OrderBy(p=>p,StringComparer.OrdinalIgnoreCase).SequenceEqual(original.Files.OrderBy(p=>p,StringComparer.OrdinalIgnoreCase),StringComparer.OrdinalIgnoreCase)||hashes.Count!=source.Files.Length)throw new Exception("CHECKPOINT_MODEL_MISMATCH");
        if(source.Files.Count(p=>p.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase))!=1)throw new CadFault("RESET_BRANCH_SCOPE_UNSUPPORTED","新副本归零仅验收单层刚体零件装配。未修改原模型。");
        StudyState initial=Json.Deserialize<StudyState[]>(Json.Serialize(data["studies"])).SingleOrDefault(v=>v.name==studyName);if(initial==null)throw new Exception("STUDY_NOT_FOUND_IN_CHECKPOINT");
        if(initial.type!=1&&initial.type!=4)throw new CadFault("RESET_BRANCH_STUDY_TYPE_UNVALIDATED","新副本降帧归零仅验收Animation和Motion Analysis算例。");
        if(!StudyCacheBudget.Allows(initial.duration_s,fps))throw new CadFault("RESET_CALCULATION_BUDGET_EXCEEDED","新副本的目标设置仍超过归零预算，未修改模型。",StudyCacheBudget.Describe(initial.duration_s,fps));
        var snapshots=source.Files.ToDictionary(p=>p,p=>Path.Combine(Path.GetDirectoryName(descriptor),Path.GetFileName(p)),StringComparer.OrdinalIgnoreCase);
        foreach(var entry in snapshots){OwnedPath(entry.Value,"user_assemblies");if(!hashes.ContainsKey(entry.Key)||FileHash(entry.Value)!=hashes[entry.Key])throw new Exception("CHECKPOINT_INTEGRITY_FAILED");}
        string context=ReplayCurrentContext(original),uid=Guid.NewGuid().ToString("N"),directory=Path.Combine(UserFolder,uid),files=Path.Combine(directory,"files");Directory.CreateDirectory(files);
        var mapping=source.Files.Select((p,i)=>new{path=p,copy=Path.Combine(files,"branch_"+uid.Substring(0,8)+"_"+i.ToString("D4")+Path.GetExtension(p))}).ToDictionary(p=>p.path,p=>p.copy,StringComparer.OrdinalIgnoreCase);
        var branch=new UserModel{Id="user_"+uid,Directory=directory,Path=mapping[source.Path],Files=source.Files.Select(p=>mapping[p]).ToArray(),Configuration=source.Configuration,SourceHashes=snapshots.Values.ToDictionary(p=>p,p=>FileHash(p)),Purpose="reset_branch",ParentModelId=id,ImportState="incomplete"};SaveUserModel(branch);
        LastOperationRestoration="pending";try {
            Progress(activeJobId,"copy_reset_checkpoint",0,0,null);foreach(var entry in mapping){File.Copy(snapshots[entry.Key],entry.Value);File.SetAttributes(entry.Value,FileAttributes.Normal);}
            foreach(var entry in mapping)foreach(string reference in DiskDependencies(snapshots[entry.Key],false))if(!mapping.ContainsKey(reference)||!Sw.ReplaceReferencedDocument(entry.Value,reference,mapping[reference]))throw new Exception("RESET_BRANCH_REDIRECT_FAILED");
            RequireCopyReferenceClosure(branch,false);
            string workerFolder=Path.Combine(Root,"runs","probes","reset_"+Guid.NewGuid().ToString("N").Substring(0,8));Directory.CreateDirectory(workerFolder);
            WriteStage("reset_branch_isolated_worker",id,null,checkpointId);
            var worker=RunIsolatedProbe(workerFolder,new Dictionary<string,object>{{"kind","reset_branch"},{"model",branch},{"study",studyName},{"initial",initial},{"output_fps",fps}});
            var completed=Json.Deserialize<UserModel>(File.ReadAllText(Path.Combine(branch.Directory,"model.json")));
            if(completed.Id!=branch.Id||completed.Directory!=branch.Directory||completed.Path!=branch.Path||!completed.Files.SequenceEqual(branch.Files))throw new Exception("RESET_BRANCH_MANIFEST_CHANGED");branch=completed;
            if(context!=ReplayCurrentContext(original))throw new CadFault("RESET_BRANCH_ORIGINAL_CHANGED","新副本归零后原模型上下文未通过核验，停止后续写入。");
            if(FileHash(descriptor)!=descriptorHash||snapshots.Any(p=>FileHash(p.Value)!=hashes[p.Key]))throw new Exception("RESET_BRANCH_SNAPSHOT_CHANGED");VerifyUserSources(original);branch.ImportState="complete";SaveUserModel(branch);LastOperationRestoration="restored";
            return new{model_id=branch.Id,source_model_id=id,source_checkpoint_id=checkpointId,input_scope="explicit_checkpoint_not_current_unsaved_memory",native_drive_registrations_copied=false,new_registered_model=true,study=studyName,time_s=0,output_fps=fps,previous_output_fps=initial.fps,study_settings_preserved=fps==initial.fps,settings_changed=fps!=initial.fps,original_model_unchanged=true,independent_owned_worker=true,worker_evidence_path=worker["evidence_path"],reopen_validation=((Dictionary<string,object>)worker["result"])["reopen_validation"],recalculated_for_reset=true,results_invalidated=true,new_geometry_queries_required=true,pose_validation="clock_settings_and_stopped_state_no_independent_frame0_oracle",restoration_status="restored",next_tools=new[]{"inspect_model","list_motion_studies","list_mate_references"}};
        }catch(Exception failure){branch.ImportState="incomplete";SaveUserModel(branch);bool unchanged=false;try{unchanged=context==ReplayCurrentContext(original);}catch{}bool cleanupUnknown=HistoryErrorCode(failure)=="ISOLATED_PROBE_RECOVERY_REQUIRED";LastOperationRestoration=unchanged&&!cleanupUnknown?"restored":"unknown";throw new CadFault("RESET_BRANCH_FAILED","新副本归零未通过，已隔离该副本；没有用它替换原模型。",new{model_id=branch.Id,source_model_id=id,checkpoint_id=checkpointId,worker_cleanup_confirmed=HistoryErrorCode(failure)!="ISOLATED_PROBE_RECOVERY_REQUIRED",original_model_unchanged=unchanged,branch_usable=false,original_failure=FailureEvidence(failure)});}
    }
    object ResetBranchWorker(UserModel branch,Dictionary<string,object> request) {
        string studyName=(string)request["study"];int fps=Convert.ToInt32(request["output_fps"]);var initial=Json.Deserialize<StudyState>(Json.Serialize(request["initial"]));Dictionary<string,double[]> expected;
        using(var scope=new Scope(this,branch.Path,null)) {
            Fingerprint(scope.Doc,scope.DocumentPath);InspectUserCore(branch,scope.Doc);
            var manager=(IMotionStudyManager)scope.Doc.Extension.GetMotionStudyManager();var study=(IMotionStudy)manager.GetMotionStudy(studyName);
            if(study==null||study.StudyType!=initial.type||Math.Abs(study.GetDuration()-initial.duration_s)>1e-8||!StudyCacheBudget.Allows(initial.duration_s,fps))throw new Exception("RESET_BRANCH_STUDY_SETTINGS_MISMATCH");study.Stop();
            if(!study.IsActive&&!manager.ActivateMotionStudy(studyName))throw new Exception("STUDY_ACTIVATION_REJECTED");
            var properties=(IMotionStudyProperties)study.GetProperties(study.StudyType);if(!properties.SetFrameRate(fps)||properties.GetFrameRate()!=fps)throw new Exception("SOLVER_SETTINGS_UNVERIFIED");
            if(!study.Calculate())throw new Exception("SOLVER_FAILED");study=(IMotionStudy)((IMotionStudyManager)scope.Doc.Extension.GetMotionStudyManager()).GetMotionStudy(studyName);study.Stop();Application.DoEvents();study.SetTime(0);Application.DoEvents();study.Stop();
            if(Math.Abs(study.GetTime())>1e-8||study.IsPlaying||((IMotionStudyProperties)study.GetProperties(study.StudyType)).GetFrameRate()!=fps||Math.Abs(study.GetDuration()-initial.duration_s)>1e-8||study.StudyType!=initial.type)throw new Exception("STUDY_RESET_UNVERIFIED");
            expected=Transforms(scope.Doc);SaveOwnedDocuments(branch);Save(scope.Doc,branch.Path);branch.Revision++;SaveUserModel(branch);
        }
        CloseUserDocuments(branch.Files);object validation;
        using(var reopened=new Scope(this,branch.Path,null)) {
            var study=(IMotionStudy)((IMotionStudyManager)reopened.Doc.Extension.GetMotionStudyManager()).GetMotionStudy(studyName);var actual=Transforms(reopened.Doc);
            bool matches=expected.Count==actual.Count&&expected.All(p=>actual.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,actual[p.Key]));
            if(study==null||Math.Abs(study.GetTime())>1e-8||study.IsPlaying||study.StudyType!=initial.type||((IMotionStudyProperties)study.GetProperties(study.StudyType)).GetFrameRate()!=fps||Math.Abs(study.GetDuration()-initial.duration_s)>1e-8||!matches)throw new CadFault("RESET_BRANCH_REOPEN_UNVERIFIED","新副本重开后归零设置或全部姿态未通过，不登记为可用。",new{pose_matches=matches,pose_change=PoseChange(expected,actual)});
            validation=new{verified=true,time_s=study.GetTime(),output_fps=fps,checked_components=actual.Count,pose_change=PoseChange(expected,actual),claim="one_observed_reopen_not_future_restore_guarantee"};
        }
        return new{reopen_validation=validation,restoration_status="restored"};
    }

}
