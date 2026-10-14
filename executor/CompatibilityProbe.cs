using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    // Explicit short solve of a second imported copy; original documents are never saved.
    public object ProbeUserCompatibility(string id,string study,double duration,int fps,string runId) {
        if(!System.Text.RegularExpressions.Regex.IsMatch(runId??"","^[a-f0-9]{32}$"))throw new CadFault("INVALID_RUN_ID","运行标识格式无效。");
        if(string.IsNullOrWhiteSpace(study)||duration<=0||duration>1||double.IsNaN(duration)||double.IsInfinity(duration)||fps<5||fps>120||Math.Abs(duration*fps-Math.Round(duration*fps))>1e-8)throw new CadFault("INVALID_COMPATIBILITY_PROBE_BUDGET","显式探测须指定算例，最多1秒、121帧。",new{duration_s=duration,output_fps=fps});
        var original=GetUserModel(id);if(original.Purpose=="compatibility_probe")throw new CadFault("NESTED_COMPATIBILITY_PROBE_REJECTED","不能对探测副本继续生成嵌套探测。");
        if(original.Files.Count(p=>p.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase))!=1)throw new CadFault("COMPATIBILITY_PROBE_UNSUPPORTED","独立副本短算探测暂只验收顶层刚体零件装配。",new{model_id=id});
        UserModel probe=null;string checkpoint=null;object solve=null;Exception primary=null,cleanup=null;object originalChange=null;
        using(var sourceScope=new Scope(this,original.Path,null)){
            var hashes=original.Files.ToDictionary(p=>p,p=>FileHash(p));var poses=Transforms(sourceScope.Doc);var states=StudyStates(sourceScope.Doc);
            var observation=new StudyHistory.Observation();ObserveHistory(original,observation,"before_explicit_compatibility_probe");
            var observed=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(observation.Export()));
            if(!(bool)observed["complete"]||(bool)observed["dirty_documents_observed"])throw new CadFault("PROBE_REQUIRES_SAVED_INPUT","独立探测只复制已保存输入；当前副本有未保存或未完整观测的状态。请先显式保存检查点后再探测。",new{model_id=id,input_observation=observation.Export(),required_tool="create_model_checkpoint",implicit_save_performed=false});
            try {
                var imported=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(ImportUserAssembly(original.Path,original.Configuration,"compatibility_probe",id,runId)));
                probe=GetUserModel((string)imported["model_id"]);probe.Purpose="compatibility_probe";probe.ParentModelId=id;SaveUserModel(probe);
                checkpoint=(string)Json.Deserialize<Dictionary<string,object>>(Json.Serialize(imported["checkpoint"]))["checkpoint_id"];
                solve=RunUserStudy(probe.Id,study,duration,fps,runId);
            }catch(Exception error){primary=error;UserModel partial;if(probe==null&&userModels.TryGetValue("user_"+runId,out partial))probe=partial;}
            finally {
                if(probe!=null)try{CloseUserDocuments(probe.Files);if((Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Any(d=>probe.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)))throw new Exception("PROBE_DOCUMENT_STILL_OPEN");}catch(Exception error){cleanup=error;}
            }
            bool unchanged=hashes.All(p=>FileHash(p.Key)==p.Value);var after=Transforms(sourceScope.Doc);unchanged&=poses.Count==after.Count&&poses.All(p=>after.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,after[p.Key]));try{VerifyStudyStates(sourceScope.Doc,states);}catch{unchanged=false;}
            originalChange=PoseChange(poses,after);
            if(!unchanged){LastOperationRestoration="unknown";throw new CadFault("COMPATIBILITY_PROBE_ORIGINAL_CHANGED","探测后原副本状态未通过核验；停止后续 CAD 请求。",new{model_id=id,affected_model_id=id,probe_model_id=probe==null?null:probe.Id,original_pose_change=originalChange,original_failure=primary==null?null:FailureEvidence(primary)});}
        }
        if(cleanup!=null||LastOperationRestoration=="unknown"){
            LastOperationRestoration="unknown";throw new CadFault("COMPATIBILITY_PROBE_RECOVERY_REQUIRED","探测副本清理或恢复未确认；原副本核验未改变，恢复必须针对探测副本。",new{model_id=id,affected_model_id=probe==null?id:probe.Id,probe_model_id=probe==null?null:probe.Id,checkpoint_id=checkpoint,original_copy_unchanged=true,original_failure=primary==null?null:FailureEvidence(primary),cleanup_failure=cleanup==null?null:FailureEvidence(cleanup)});
        }
        LastOperationRestoration="restored";
        var result=new{model_id=id,probe_model_id=probe==null?null:probe.Id,checkpoint_id=checkpoint,run_id=runId,solver_compatibility_status=primary==null?"pass":"inconclusive",compatibility_probe=new{attempted=true,independent_copy=true,duration_s=duration,output_fps=fps,scope="this_saved_input_and_short_interval_only",full_run_guaranteed=false,root_cause="not_proven",failure=primary==null?null:FailureEvidence(primary)},solve=solve,original_copy_unchanged=true,original_pose_change=originalChange,restoration_status="restored",source_files_unchanged=UserSourcesUnchanged(original)};
        AtomicJson(Path.Combine(Root,"runs",runId,"compatibility-probe.json"),result);return result;
    }
}
