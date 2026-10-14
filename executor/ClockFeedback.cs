using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    void WriteStage(string stage,string modelId=null,string planId=null,string checkpointId=null){
        Log("WRITE_STAGE "+stage);Progress(activeJobId,stage,0,0,null);
        if(!string.IsNullOrEmpty(activeJobId)&&modelId!=null)AtomicJson(Path.Combine(Root,"runs","progress",activeJobId+".json"),new{job_id=activeJobId,stage=stage,model_id=modelId,plan_id=planId,checkpoint_id=checkpointId,updated_at=(DateTime.UtcNow-new DateTime(1970,1,1,0,0,0,DateTimeKind.Utc)).TotalSeconds});
    }
    void RegisterEntity(UserModel m,string id,string reference){m.Entities[id]=reference;m.EntityRegistrationRevisions[id]=m.Revision;m.RemovedEntityRegistrations.Remove(id);}
    CadFault MissingEntity(UserModel m,string id,bool mate){
        int? registered=null;int old;if(m.EntityRegistrationRevisions.TryGetValue(id??"",out old))registered=old;
        int? removed=null;bool rollback=m.RemovedEntityRegistrations.TryGetValue(id??"",out removed);
        return new CadFault(mate?"MATE_REFERENCE_NOT_REGISTERED":"DRIVE_ENTITY_NOT_FOUND",rollback?"检查点恢复回退了该参考的登记；请重新查询本模型的参考。":(mate?"本模型尚未登记该参考；先用 list_mate_references 查询相应页面。inspect_model 的 inspection-only ID 不会因可解析就自动登记。":"本模型尚未登记该参考；先用 list_drive_candidates 查询相应页面，inspect_model 的 ID 须核对登记。"),new{model_id=m.Id,entity_id=id,current_revision=m.Revision,last_known_registration_revision=rollback?removed:registered,reason=rollback?"registration_removed_by_checkpoint_restore":"not_registered_in_current_model",checkpoint_id=rollback?m.LastRestoredCheckpoint:null,required_tool=mate?"list_mate_references":"list_drive_candidates",reference_source="unregistered_or_inspection_only",registration_status=rollback?"removed_by_restore":"not_registered",required_query=mate?(object)new{model_id=m.Id,limit=20}:new{model_id=m.Id,group_faces=false,limit=20},automatic_rebinding=false});
    }
    object RestoreDifference(UserModel m,Dictionary<string,object> checkpoint){
        var target=Json.Deserialize<StudyState[]>(Json.Serialize(checkpoint["studies"]));
        var restored=Json.Deserialize<UserModel>(Json.Serialize(checkpoint["model"]));
        try{
            var open=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().FirstOrDefault(d=>d.GetPathName().Equals(m.Path,StringComparison.OrdinalIgnoreCase));
            if(open==null)return new{status="current_document_not_open",target_studies=target,registered_drives_removed=m.Drives.Keys.Except(restored.Drives.Keys).ToArray(),current_study_difference_verified=false};
            var current=StudyStates(open);
            return new{status="observed_before_restore",studies_removed=current.Select(s=>s.name).Except(target.Select(s=>s.name)).ToArray(),studies_restored=target.Select(s=>s.name).Except(current.Select(s=>s.name)).ToArray(),settings_before=current,settings_after_checkpoint=target,registered_drives_removed=m.Drives.Keys.Except(restored.Drives.Keys).ToArray(),registered_references_removed=m.Entities.Keys.Except(restored.Entities.Keys).Count(),scope="whole_copy_files_not_only_time",current_study_difference_verified=true,results_invalidated=true};
        }catch(Exception e){return new{status="current_difference_unavailable",target_studies=target,current_study_difference_verified=false,error=HistoryErrorCode(e),message=e.Message};}
    }
    void ObserveOwnedSave(UserModel m,string stage){
        if(saveOperation==null){using(var scope=BeginSaveObservationOperation("direct_save_observation")){ObserveOwnedSave(m,stage);}return;}
        var observation=new StudyHistory.Observation();ObserveHistory(m,observation,stage);RecordSaveObservation(m,stage,observation.Export(),HistoryCurrentHashes(m));
    }
    void RecordReplayRestoration(Run run,string attempt,int frame,string outcome){
        var model=GetUserModel(run.Assembly);if(model.Revision!=run.EditVersion)throw new CadFault("REPLAY_INPUT_STATE_CHANGED","恢复后模型版本已改变，不更新旧结果输入身份。",new{run_id=run.Id,recorded_revision=run.EditVersion,current_revision=model.Revision});
        var before=run.FileHashes;run.FileHashes=model.Files.ToDictionary(p=>p,p=>FileHash(p));
        string path=Path.Combine(run.Directory,"solve.json");var result=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));
        result["input_file_hashes"]=run.FileHashes;
        result["last_replay_attempt"]=new{attempt_id=attempt,frame=frame,replay_assertion=outcome,restoration_status="restored",input_hash_update_source="verified_owned_snapshot_restoration_after_prechecked_run",hashes_before=before,hashes_after=run.FileHashes,physical_validation_claim=false};
        AtomicJson(path,result);
    }
}
