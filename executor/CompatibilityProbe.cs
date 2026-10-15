using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object ProbeUserCompatibility(string id,string study,double duration,int fps,string runId,string checkpointId="") {
        if(!System.Text.RegularExpressions.Regex.IsMatch(runId??"","^[a-f0-9]{32}$"))throw new CadFault("INVALID_RUN_ID","运行标识格式无效。");
        if(string.IsNullOrWhiteSpace(study)||duration<=0||duration>1||double.IsNaN(duration)||double.IsInfinity(duration)||fps<5||fps>120||Math.Abs(duration*fps-Math.Round(duration*fps))>1e-8)throw new CadFault("INVALID_COMPATIBILITY_PROBE_BUDGET","显式探测须指定算例，最多1秒、121帧。",new{duration_s=duration,output_fps=fps});
        var original=GetUserModel(id);if(original.Purpose=="compatibility_probe")throw new CadFault("NESTED_COMPATIBILITY_PROBE_REJECTED","不能对探测副本继续生成嵌套探测。");
        if(original.Files.Count(p=>p.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase))!=1)throw new CadFault("COMPATIBILITY_PROBE_UNSUPPORTED","暂只验收顶层刚体零件装配。",new{model_id=id});
        var hashes=original.Files.ToDictionary(p=>p,p=>FileHash(p));var doc=Sw.GetOpenDocumentByName(original.Path) as IModelDoc2;
        var poses=doc==null?null:Transforms(doc);var states=doc==null?null:StudyStates(doc);
        string mechanics=doc==null?null:Json.Serialize(new{input_documents=ProbeWorkingState.InputDocumentIdentity(doc),components=ProbeWorkingState.ComponentIdentity(doc),mates=ProbeWorkingState.MateIdentity(doc),health=ProbeWorkingState.MateHealthIdentity(doc),configuration=doc.ConfigurationManager.ActiveConfiguration.Name,stamp=doc.GetUpdateStamp()});
        string activePath=(Sw.ActiveDoc as IModelDoc2)==null?null:((IModelDoc2)Sw.ActiveDoc).GetPathName();
        var snapshots=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);UserModel source=original;string descriptorHash=null;
        if(!string.IsNullOrEmpty(checkpointId)) {
            if(!System.Text.RegularExpressions.Regex.IsMatch(checkpointId,"^[a-f0-9]{32}$"))throw new CadFault("INVALID_CHECKPOINT_ID","检查点格式无效。");
            string directory=Path.Combine(original.Directory,"checkpoints",checkpointId),descriptor=Path.Combine(directory,"checkpoint.json");OwnedPath(descriptor,"user_assemblies");
            var data=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(descriptor));descriptorHash=FileHash(descriptor);
            if((string)data["model_id"]!=id)throw new Exception("CHECKPOINT_MODEL_MISMATCH");
            source=Json.Deserialize<UserModel>(Json.Serialize(data["model"]));var files=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(data["files"]));
            if(source.Id!=id||!source.Files.OrderBy(p=>p).SequenceEqual(original.Files.OrderBy(p=>p))||!source.Files.All(files.ContainsKey))throw new Exception("CHECKPOINT_FILE_SET_MISMATCH");
            foreach(string path in source.Files){string snapshot=Path.Combine(directory,Path.GetFileName(path));OwnedPath(snapshot,"user_assemblies");if(FileHash(snapshot)!=files[path])throw new Exception("CHECKPOINT_INTEGRITY_FAILED");snapshots[path]=snapshot;}
        } else {
            var observation=new StudyHistory.Observation();ObserveHistory(original,observation,"before_explicit_compatibility_probe");var observed=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(observation.Export()));
            if(!(bool)observed["complete"]||(bool)observed["dirty_documents_observed"])throw new CadFault("PROBE_REQUIRES_EXPLICIT_CHECKPOINT","当前副本有未保存或打开后复脏的状态。请建立检查点，并将其checkpoint_id显式传给preflight_motion；快照探测不证明当前未保存内存状态。",new{model_id=id,input_observation=observation.Export(),required_tool="create_model_checkpoint",next_tool="preflight_motion",required_parameter="checkpoint_id",implicit_save_performed=false});
            snapshots=original.Files.ToDictionary(p=>p,p=>p,StringComparer.OrdinalIgnoreCase);
        }
        string folder=Path.Combine(Root,"runs",runId);Directory.CreateDirectory(folder);Dictionary<string,string> renames;
        var probe=CopyProbeInputs(source,snapshots,folder,out renames);object worker=null;Exception failure=null;
        try{LastOperationRestoration="pending";WriteStage("compatibility_isolated_probe",id);worker=RunIsolatedProbe(folder,new Dictionary<string,object>{{"kind","compatibility"},{"model",probe},{"study",study},{"duration_s",duration},{"output_fps",fps},{"run_id",runId}});}catch(Exception error){failure=error;}
        bool unchanged=hashes.All(p=>FileHash(p.Key)==p.Value);
        try {
            var afterDoc=Sw.GetOpenDocumentByName(original.Path) as IModelDoc2;unchanged&=(doc==null)==(afterDoc==null);
            if(doc!=null){var actual=Transforms(doc);unchanged&=poses.Count==actual.Count&&poses.All(p=>actual.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,actual[p.Key]));VerifyStudyStates(doc,states);
                unchanged&=mechanics==Json.Serialize(new{input_documents=ProbeWorkingState.InputDocumentIdentity(doc),components=ProbeWorkingState.ComponentIdentity(doc),mates=ProbeWorkingState.MateIdentity(doc),health=ProbeWorkingState.MateHealthIdentity(doc),configuration=doc.ConfigurationManager.ActiveConfiguration.Name,stamp=doc.GetUpdateStamp()});}
            string now=(Sw.ActiveDoc as IModelDoc2)==null?null:((IModelDoc2)Sw.ActiveDoc).GetPathName();unchanged&=string.Equals(activePath,now,StringComparison.OrdinalIgnoreCase);
        }catch{unchanged=false;}
        if(!unchanged){LastOperationRestoration="unknown";throw new CadFault("COMPATIBILITY_PROBE_ORIGINAL_CHANGED","原副本未通过前后核验；停止CAD写入。",new{model_id=id,evidence_directory=folder});}
        Dictionary<string,object> workerRecord=null;bool workerExited=false;string workerResult=Path.Combine(folder,"worker-result.json");if(File.Exists(workerResult)){workerRecord=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(workerResult));workerExited=Convert.ToBoolean(workerRecord["owned_process_exited"]);}
        if(!workerExited){LastOperationRestoration="unknown";throw new CadFault("COMPATIBILITY_PROBE_RECOVERY_REQUIRED","临时实例退出未确认；保留进程和完成证据，不自动重试。",new{model_id=id,evidence_directory=folder,original_copy_unchanged=true,original_failure=failure==null?null:FailureEvidence(failure)});}
        string savedRun=Path.Combine(folder,"runs",runId),savedManifest=Path.Combine(savedRun,"solve.json");
        if(File.Exists(savedManifest)) {
            var saved=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(savedManifest));
            foreach(string name in new[]{"component-poses.csv","time-axis.json","component-motion-overview.json"}) {
                string input=Path.Combine(savedRun,name),output=Path.Combine(folder,name);if(File.Exists(input)){byte[] bytes=File.ReadAllBytes(input);File.WriteAllBytes(output,bytes);if(FileHash(output)!=FileHash(input))throw new Exception("PROBE_ARTIFACT_COPY_MISMATCH");}
            }
            string csv=Path.Combine(folder,"component-poses.csv");if(File.Exists(csv)&&(!saved.ContainsKey("poses_sha256")||FileHash(csv)!=(string)saved["poses_sha256"]))throw new Exception("PROBE_ARTIFACT_HASH_MISMATCH");
            saved["history_usage"]=new{scope="isolated_probe_snapshot_only",summary_tool="get_run_artifacts",summary_arguments=new{run_id=runId},curve_export_option="allow_unverified_history=true",current_model_validity="not_checked_offline"};
            saved["parent_model_id"]=id;saved["probe_input_scope"]=string.IsNullOrEmpty(checkpointId)?"saved_disk_input_only":"explicit_checkpoint_snapshot_not_current_unsaved_memory";saved["probe_checkpoint_id"]=checkpointId;saved["poses_csv"]=csv;
            AtomicJson(Path.Combine(folder,"solve.json"),saved);
        }
        LastOperationRestoration="restored";LastContextRestoration="restored";
        object workerSummary=worker==null?null:new{completed=true,success=true,owned_solidworks_pid=workerRecord["owned_solidworks_pid"],owned_process_exited=workerRecord["owned_process_exited"],native_exit_code=workerRecord["native_exit_code"],full_record_path=workerResult,full_record_sha256=FileHash(workerResult).Replace("-","").ToLowerInvariant()};
        var result=new{model_id=id,probe_model_id=probe.Id,probe_model_registration_scope="isolated_worker_only_not_main_model_registry",checkpoint_id=checkpointId,checkpoint_descriptor_sha256=descriptorHash,run_id=runId,solver_compatibility_status=failure==null?"pass":"inconclusive",compatibility_probe=new{attempted=true,independent_copy=true,independent_solidworks_process=true,duration_s=duration,output_fps=fps,scope=string.IsNullOrEmpty(checkpointId)?"saved_disk_input_only":"explicit_checkpoint_snapshot_not_current_unsaved_memory",checkpoint_revision=source.Revision,current_revision=original.Revision,current_memory_compatibility_proven=false,full_run_guaranteed=false,root_cause="not_proven",failure=failure==null?null:workerRecord!=null&&workerRecord["failure"]!=null?workerRecord["failure"]:FailureEvidence(failure)},worker=workerSummary,saved_result_query=new{tool="get_run_artifacts",run_id=runId},worker_evidence_path=workerResult,worker_evidence_sha256=FileHash(workerResult).Replace("-","").ToLowerInvariant(),original_copy_unchanged=true,restoration_status="restored",source_files_unchanged=UserSourcesUnchanged(original)};
        AtomicJson(Path.Combine(folder,"compatibility-probe.json"),result);return result;
    }
}
