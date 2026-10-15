using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    // Internal, explicitly enabled test hooks are not exposed as MCP parameters.
    internal Action<string,IModelDoc2> CheckpointProbeTestHook=null;
    void CheckpointProbeHook(string stage,IModelDoc2 original){if(CheckpointProbeTestHook!=null){if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new CadFault("FAULT_TESTS_DISABLED","检查点故障注入只允许显式测试环境。");CheckpointProbeTestHook(stage,original);}}
    sealed class ProbeWorkingState {
        readonly Cad cad;readonly UserModel model;readonly OwnedMotionSnapshot snapshot;public string RestorationMethod;public object InPlaceFailure;
        readonly string configuration,components,mates,health;
        readonly int stamp;readonly Dictionary<string,string> hashes;
        readonly Dictionary<string,double[]> poses;readonly StudyState[] studies;
        public ProbeWorkingState(Cad owner,UserModel m,IModelDoc2 doc){cad=owner;model=m;snapshot=new OwnedMotionSnapshot(owner,m,doc);configuration=doc.ConfigurationManager.ActiveConfiguration.Name;poses=Transforms(doc);studies=StudyStates(doc);stamp=doc.GetUpdateStamp();hashes=m.Files.ToDictionary(p=>p,p=>FileHash(p));components=ComponentIdentity(doc);mates=MateIdentity(doc);health=MateHealthIdentity(doc);}
        static string ComponentIdentity(IModelDoc2 doc){return Json.Serialize(UserComponents(doc).OrderBy(c=>c.GetID()).Select(c=>new{id=c.GetID(),reference=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(c)),path=c.GetPathName(),configuration=c.ReferencedConfiguration,fixed_component=c.IsFixed(),suppressed=c.IsSuppressed()}).ToArray());}
        static string MateHealthIdentity(IModelDoc2 doc){return Json.Serialize(BasicMateFeatures(doc).OrderBy(f=>f.GetID()).Select(f=>{bool warning;return new{id=f.GetID(),error=f.GetErrorCode2(out warning),warning=warning};}).ToArray());}
        static string MateIdentity(IModelDoc2 doc){return Json.Serialize(BasicMateFeatures(doc).GroupBy(f=>f.GetID()).Select(g=>g.First()).OrderBy(f=>f.GetID()).Select(f=>{var m=(IMate2)f.GetSpecificFeature2();var lockData=f.GetDefinition() as SolidWorks.Interop.sldworks.IConcentricMateFeatureData;double? distance=null;if(m.Type==5){var d=m.DisplayDimension2[0] as IDisplayDimension;if(d==null)throw new Exception("MATE_PARAMETER_UNREADABLE");distance=((IDimension)d.GetDimension2(0)).SystemValue;}return new{id=f.GetID(),type=m.Type,alignment=m.Alignment,lock_rotation=lockData==null?(bool?)null:lockData.LockRotation,distance_m=distance,references=Enumerable.Range(0,m.GetMateEntityCount()).Select(i=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(m.MateEntity(i).Reference))).ToArray()};}).ToArray());}
        public Dictionary<string,object> Observe(IModelDoc2 doc){
            bool files=hashes.All(p=>FileHash(p.Key)==p.Value),identity=ComponentIdentity(doc)==components,nativeMates=MateIdentity(doc)==mates,config=doc.ConfigurationManager.ActiveConfiguration.Name==configuration;var actual=Transforms(doc);bool pose=actual.Count==poses.Count&&poses.All(p=>actual.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,actual[p.Key]));
            var current=StudyStates(doc);var differences=studies.Where(s=>!current.Any(a=>a.name==s.name&&a.type==s.type&&a.fps==s.fps&&Math.Abs(a.duration_s-s.duration_s)<=1e-8&&Math.Abs(a.time_s-s.time_s)<=1e-8&&a.active==s.active)).Select(s=>s.name).Concat(current.Where(s=>!studies.Any(a=>a.name==s.name)).Select(s=>s.name)).Distinct().ToArray();
            var active=cad.Sw.ActiveDoc as IModelDoc2;bool window=active!=null&&string.Equals(active.GetPathName(),model.Path,StringComparison.OrdinalIgnoreCase);bool sameStamp=doc.GetUpdateStamp()==stamp;bool sameHealth=MateHealthIdentity(doc)==health;
            return new Dictionary<string,object>{{"verified",files&&identity&&nativeMates&&sameHealth&&config&&pose&&differences.Length==0&&current.Length==studies.Length&&window},{"files_unchanged",files},{"component_identity_unchanged",identity},{"mates_unchanged",nativeMates},{"mate_health_unchanged",sameHealth},{"configuration_unchanged",config},{"pose_matches",pose},{"study_states_match",differences.Length==0&&current.Length==studies.Length},{"study_state_differences",differences.Take(8).ToArray()},{"study_state_difference_count",differences.Length},{"working_document_active",window},{"native_update_stamp_unchanged",sameStamp},{"context_restore_allowed",files&&identity&&nativeMates&&config&&sameStamp},{"pose_change",actual.Keys.OrderBy(x=>x).SequenceEqual(poses.Keys.OrderBy(x=>x))?PoseChange(poses,actual):null}};
        }
        public IModelDoc2 Restore(IModelDoc2 doc){
            var evidence=Observe(doc);if(!(bool)evidence["context_restore_allowed"])throw new CadFault("CHECKPOINT_PROBE_EXTERNAL_CHANGE_UNPROVEN","原副本机械输入或更新标记改变，不能自动覆盖可能的并发编辑。",evidence);
            try{int error=0;var active=cad.Sw.ActiveDoc as IModelDoc2;if(active==null||!string.Equals(active.GetPathName(),model.Path,StringComparison.OrdinalIgnoreCase)){var selected=cad.Sw.ActivateDoc3(doc.GetTitle(),false,0,ref error);if(selected==null||error!=0)throw new Exception("CHECKPOINT_PROBE_REACTIVATION_FAILED");}ApplyStudyStates(doc,studies,poses);VerifyStudyStates(doc,studies);var after=Observe(doc);if(!(bool)after["verified"])throw new CadFault("CHECKPOINT_PROBE_CONTEXT_RESTORE_FAILED","恢复时钟后全部组件姿态和状态仍未通过核验。",after);RestorationMethod="native_study_state";return doc;}
            catch(Exception error){
                InPlaceFailure=FailureEvidence(error);var after=Observe(doc);if(!(bool)after["files_unchanged"]||!(bool)after["component_identity_unchanged"]||!(bool)after["mates_unchanged"]||!(bool)after["configuration_unchanged"])throw new CadFault("CHECKPOINT_PROBE_SNAPSHOT_FALLBACK_REFUSED","原生恢复后机械输入身份改变，未覆盖文件。",after);
                // Exactly one reopen of bytes captured before the probe. No transform forcing.
                var reopened=snapshot.Restore();var verified=Observe(reopened);if(!(bool)verified["verified"])throw new CadFault("CHECKPOINT_PROBE_CONTEXT_RESTORE_FAILED","精确快照重开后状态仍未通过核验。",verified);RestorationMethod="exact_file_snapshot_reopen";return reopened;
            }
        }
    }
    object CheckAnimationCheckpoint(UserModel model,string checkpointId) {
        string directory=Path.Combine(model.Directory,"checkpoints",checkpointId),record=Path.Combine(directory,"restorability.json");
        var descriptor=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(directory,"checkpoint.json")));var states=Json.Deserialize<StudyState[]>(Json.Serialize(descriptor["studies"]));
        if(!states.Any(s=>s.active&&s.type==1)){var skipped=new{status="not_required",scope="active_animation_checkpoint_only",model_id=model.Id,checkpoint_id=checkpointId,mate_created=false};AtomicJson(record,skipped);return skipped;}
        var original=Sw.GetOpenDocumentByName(model.Path) as IModelDoc2;if(original==null)throw new CadFault("CHECKPOINT_PROBE_CONTEXT_MISSING","恢复预检需要已打开的登记副本；未添加配合。",new{model_id=model.Id,checkpoint_id=checkpointId});
        var working=new ProbeWorkingState(this,model,original);var timeline=new List<object>();string stage="prepare",probe=null;Exception failure=null,cleanup=null,restoration=null;object probePose=null;bool restored=false;
        var result=new Dictionary<string,object>{{"model_id",model.Id},{"checkpoint_id",checkpointId},{"mate_created",false},{"write_committed",false},{"evidence_path",record}};
        Action<string> observe=s=>{stage=s;timeline.Add(new{stage=s,original=working.Observe(original)});};
        LastOperationRestoration="pending";
        try {
            observe("before_probe");CheckpointProbeHook("before_copy",original);
            if(model.Files.Count(p=>p.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase))!=1)throw new CadFault("CHECKPOINT_PROBE_UNSUPPORTED","激活动画的多层装配未纳入恢复预检；未添加配合。");
            var expected=Json.Deserialize<Dictionary<string,double[]>>(Json.Serialize(descriptor["poses"]));var hashes=(Dictionary<string,object>)descriptor["files"];
            stage="copy_checkpoint";probe=Path.Combine(Root,"runs","probes",Guid.NewGuid().ToString("N").Substring(0,8));Directory.CreateDirectory(probe);
            var snapshots=model.Files.ToDictionary(p=>p,p=>Path.Combine(directory,Path.GetFileName(p)),StringComparer.OrdinalIgnoreCase);
            foreach(var entry in snapshots)if(FileHash(entry.Value)!=(string)hashes[entry.Key])throw new Exception("CHECKPOINT_INTEGRITY_FAILED");
            Dictionary<string,string> renames;var isolated=CopyProbeInputs(model,snapshots,probe,out renames);
            stage="isolated_worker";WriteStage("checkpoint_isolated_probe",model.Id,null,checkpointId);
            observe("before_isolated_worker");var worker=RunIsolatedProbe(probe,new Dictionary<string,object>{{"kind","checkpoint"},{"model",isolated},{"studies",states},{"poses",expected},{"renames",renames}});
            result["isolated_worker"]=worker;CheckpointProbeHook("after_probe_open",original);
            probePose=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(worker["result"]))["pose_change"];
            observe("after_probe_restore");
        }catch(Exception error){failure=error;if(error is CadFault&&((CadFault)error).Code=="ISOLATED_PROBE_RECOVERY_REQUIRED")cleanup=error;result["failure_stage"]=stage;}
        finally {
            try{CheckpointProbeHook("before_probe_close",original);CheckpointProbeHook("after_probe_close",original);observe("after_probe_close");}catch(Exception error){cleanup=error;}
        }
        Dictionary<string,object> after=null;
        try{after=working.Observe(original);if(!(bool)after["verified"]&&cleanup==null){stage="restore_original_context";CheckpointProbeHook("before_context_restore",original);original=working.Restore(original);restored=true;observe("after_original_context_restore");after=working.Observe(original);}}catch(Exception error){restoration=error;try{after=working.Observe(original);}catch{}}
        bool originalVerified=after!=null&&(bool)after["verified"],safe=originalVerified&&cleanup==null&&restoration==null;
        bool mismatch=failure is CadFault&&new[]{"CHECKPOINT_POSE_RESTORE_FAILED","CHECKPOINT_TIME_RESTORE_FAILED"}.Contains(((CadFault)failure).Code);
        result["status"]=!safe?"recovery_required":failure==null?"verified":mismatch?"unrestorable":"probe_failed";result["probe_restore_status"]=failure==null?"verified":"not_verified";result["original_copy_restore_status"]=originalVerified?(restored?"restored":"unchanged"):"unconfirmed";result["original_copy_unchanged"]=originalVerified&&!restored;result["original_copy_verified"]=originalVerified;result["context_restore_performed"]=restored;result["context_restore_method"]=working.RestorationMethod;result["in_place_restoration_failure"]=working.InPlaceFailure;result["original_state"]=after;result["probe_path"]=probe;result["pose_change"]=probePose;result["failure"]=failure==null?null:FailureEvidence(failure);result["cleanup_failure"]=cleanup==null?null:FailureEvidence(cleanup);result["context_restoration_failure"]=restoration==null?null:FailureEvidence(restoration);result["stage_timeline"]=timeline.ToArray();result["restoration_status"]=safe?"restored":"unknown";
        LastOperationRestoration=safe?"restored":"unknown";LastContextRestoration=safe?"restored":"unknown";AtomicJson(record,result);
        var summary=new{model_id=model.Id,checkpoint_id=checkpointId,status=result["status"],probe_restore_status=result["probe_restore_status"],original_copy_restore_status=result["original_copy_restore_status"],original_copy_unchanged=originalVerified&&!restored,original_copy_verified=originalVerified,context_restore_performed=restored,context_restore_method=working.RestorationMethod,mate_created=false,write_committed=false,restoration_status=LastOperationRestoration,original_state=after,evidence_path=record,evidence_sha256=FileHash(record).Replace("-","").ToLowerInvariant(),stage_count=timeline.Count,stages=timeline.Select(t=>(string)Json.Deserialize<Dictionary<string,object>>(Json.Serialize(t))["stage"]).Take(8).ToArray(),stages_truncated=timeline.Count>8,probe_failure_code=failure==null?null:HistoryErrorCode(failure),cleanup_failure_code=cleanup==null?null:HistoryErrorCode(cleanup),context_restoration_failure_code=restoration==null?null:HistoryErrorCode(restoration),probe_execution="separate_owned_solidworks_process",isolated_worker=result.ContainsKey("isolated_worker")?result["isolated_worker"]:null,full_failures_and_stage_observations="saved_in_hash_bound_evidence_file"};
        if(!safe)throw new CadFault(cleanup!=null?"CHECKPOINT_PROBE_CLEANUP_FAILED":"CHECKPOINT_PROBE_CONTEXT_CHANGED","探测后的原副本或清理未通过完整核验；未添加配合，保留诊断并进入恢复。",summary);
        if(failure!=null)throw new CadFault(mismatch?"MATE_CHECKPOINT_UNRESTORABLE":"CHECKPOINT_PROBE_FAILED","检查点探测未通过；未添加配合，原工作副本已核验，不自动重复写入。",summary);
        return summary;
    }
}
