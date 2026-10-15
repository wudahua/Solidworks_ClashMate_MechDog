using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Collections.Generic;

public partial class Cad {
    sealed class SaveOperation {
        public string Id=Guid.NewGuid().ToString("N"),Name,RequestId,JobId;
        public int Depth;
        public Dictionary<string,SaveTrace> Models=new Dictionary<string,SaveTrace>();
    }
    sealed class SaveTrace {
        public int Count;public bool Complete=true,Dirty;
        public string LegacyArchiveId;
        public List<object> Rows=new List<object>();
        public Dictionary<string,string> PreviousHashes;
    }
    sealed class SaveOperationScope:IDisposable {
        Cad Owner;
        public SaveOperationScope(Cad owner){Owner=owner;}
        public void Dispose(){if(Owner!=null){if(--Owner.saveOperation.Depth==0)Owner.saveOperation=null;Owner=null;}}
    }
    SaveOperation saveOperation;
    string activeRequestId;
    IDisposable BeginSaveObservationOperation(string name){
        if(saveOperation==null)saveOperation=new SaveOperation{Name=name,RequestId=activeRequestId,JobId=activeJobId};
        saveOperation.Depth++;return new SaveOperationScope(this);
    }
    static string SaveAuditPath(UserModel model,string relative){
        string boundary=Path.GetFullPath(model.Directory),path=Path.GetFullPath(Path.Combine(boundary,relative));
        if(!path.StartsWith(boundary+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("SAVE_OBSERVATION_PATH_OUTSIDE_MODEL");
        string current=path;while(current!=null&&current.Length>=boundary.Length){if((File.Exists(current)||Directory.Exists(current))&&(File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0)throw new IOException("SAVE_OBSERVATION_REPARSE_POINT");current=Path.GetDirectoryName(current);}return path;
    }
    object SaveObservation(UserModel model){
        SaveTrace trace;
        if(saveOperation==null||!saveOperation.Models.TryGetValue(model.Id,out trace))return new{model_id=model.Id,scope="current_operation",stage_count=0,stages=new object[0],history_query=new{tool="get_run_artifacts",model_id=model.Id,operation_id=""},warning="no_save_observation_recorded_in_this_operation"};
        string directory=SaveAuditPath(model,Path.Combine("save-observations",saveOperation.Id));
        var rows=trace.Rows.ToList();
        Func<object> response=()=>new{schema_version=1,model_id=model.Id,model_revision=model.Revision,scope="current_operation",operation_id=saveOperation.Id,operation_name=saveOperation.Name,request_id=saveOperation.RequestId,job_id=saveOperation.JobId,stage_count=trace.Count,returned_stage_count=rows.Count,stages_truncated=rows.Count<trace.Count,stages=rows.ToArray(),complete=trace.Complete,dirty_documents_observed=trace.Dirty,payload_budget_bytes=4096,full_history_directory=directory,history_query=new{tool="get_run_artifacts",model_id=model.Id,operation_id=saveOperation.Id,limit=5,include_file_hashes=false},archived_legacy_query=trace.LegacyArchiveId==null?null:new{tool="get_run_artifacts",model_id=model.Id,operation_id=trace.LegacyArchiveId},warning="observations_only_dirty_or_saved_hash_changes_do_not_prove_mechanical_input_changes"};
        while(Encoding.UTF8.GetByteCount(Json.Serialize(response()))>4096){if(rows.Count==0)throw new IOException("SAVE_OBSERVATION_SUMMARY_BUDGET_EXCEEDED");rows.RemoveAt(0);}
        return response();
    }
    void RecordSaveObservation(UserModel model,string stage,object observation,Dictionary<string,string> hashes){
        SaveTrace trace;if(!saveOperation.Models.TryGetValue(model.Id,out trace)){trace=new SaveTrace();saveOperation.Models[model.Id]=trace;}
        string previous=SaveAuditPath(model,"last-save-observation.json");
        if(File.Exists(previous)){
            if(new FileInfo(previous).Length>8388608)throw new IOException("LEGACY_OBSERVATION_ARCHIVE_BUDGET_EXCEEDED");
            byte[] raw=File.ReadAllBytes(previous);Dictionary<string,object> old=null;try{old=Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(raw).TrimStart('\ufeff'));}catch{}
            if(old==null||!old.ContainsKey("operation_id")){
                string sha;using(var hash=System.Security.Cryptography.SHA256.Create())sha=BitConverter.ToString(hash.ComputeHash(raw)).Replace("-","").ToLowerInvariant();
                string archive=SaveAuditPath(model,Path.Combine("save-observations","legacy",sha+".json"));Directory.CreateDirectory(Path.GetDirectoryName(archive));
                if(File.Exists(archive)){if(FileHash(archive).Replace("-","").ToLowerInvariant()!=sha)throw new IOException("LEGACY_OBSERVATION_ARCHIVE_HASH_MISMATCH");}else using(var stream=new FileStream(archive,FileMode.CreateNew,FileAccess.Write)){stream.Write(raw,0,raw.Length);}
                trace.LegacyArchiveId="legacy_"+sha;
            }
        }
        int sequence=trace.Count+1;string timestamp=DateTime.UtcNow.ToString("o");
        var observed=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(observation));bool complete=Convert.ToBoolean(observed["complete"]),dirty=Convert.ToBoolean(observed["dirty_documents_observed"]);
        int? changes=trace.PreviousHashes==null?(int?)null:hashes.Keys.Union(trace.PreviousHashes.Keys).Count(p=>!hashes.ContainsKey(p)||!trace.PreviousHashes.ContainsKey(p)||hashes[p]!=trace.PreviousHashes[p]);
        string relative=Path.Combine("save-observations",saveOperation.Id,sequence.ToString("D10")+".json"),path=SaveAuditPath(model,relative);Directory.CreateDirectory(Path.GetDirectoryName(path));
        var record=new{schema_version=1,model_id=model.Id,operation_id=saveOperation.Id,operation_name=saveOperation.Name,request_id=saveOperation.RequestId,job_id=saveOperation.JobId,sequence_number=sequence,stage=stage,observed_at_utc=timestamp,model_revision=model.Revision,revision_scope="at_observation_time_before_any_later_commit",observation=observation,file_hashes=hashes};
        if(Encoding.UTF8.GetByteCount(Json.Serialize(record))>1048576)throw new IOException("SAVE_OBSERVATION_RECORD_BUDGET_EXCEEDED");
        if(File.Exists(path))throw new IOException("SAVE_OBSERVATION_SEQUENCE_COLLISION");AtomicJson(path,record);AtomicMetadata.Write(path+".sha256",FileHash(path).Replace("-","").ToLowerInvariant());
        trace.Count=sequence;trace.Complete&=complete;trace.Dirty|=dirty;trace.PreviousHashes=hashes;
        trace.Rows.Add(new{sequence_number=sequence,stage=stage,observed_at_utc=timestamp,model_revision=model.Revision,revision_scope="at_observation_time_before_any_later_commit",complete=complete,dirty_documents_observed=dirty,files_observed=hashes.Count,changed_file_count_since_previous_stage=changes});if(trace.Rows.Count>8)trace.Rows.RemoveAt(0);
        object summary=SaveObservation(model);AtomicJson(SaveAuditPath(model,Path.Combine("save-observations",saveOperation.Id,"operation.json")),summary);AtomicJson(SaveAuditPath(model,"last-save-observation.json"),summary);
    }
}
