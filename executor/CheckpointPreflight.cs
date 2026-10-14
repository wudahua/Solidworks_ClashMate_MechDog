using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    // Rehearse an active animation checkpoint in a separate, uniquely named copy.
    // Never replace the live copy's pose with a new solver pose to make a checkpoint pass.
    object CheckAnimationCheckpoint(UserModel model,string checkpointId) {
        string directory=Path.Combine(model.Directory,"checkpoints",checkpointId);
        var descriptor=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(directory,"checkpoint.json")));
        var states=Json.Deserialize<StudyState[]>(Json.Serialize(descriptor["studies"]));
        if(!states.Any(s=>s.active&&s.type==1))return new{status="not_required",scope="active_animation_checkpoint_only"};
        if(model.Files.Count(p=>p.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase))!=1)throw new CadFault("CHECKPOINT_PROBE_UNSUPPORTED","激活动画的多层装配检查点尚未覆盖恢复预检；未添加配合。",new{checkpoint_id=checkpointId,model_id=model.Id,mate_created=false});
        var expected=Json.Deserialize<Dictionary<string,double[]>>(Json.Serialize(descriptor["poses"]));
        var hashes=(Dictionary<string,object>)descriptor["files"];
        string probe=Path.Combine(Experiments,"cp-probes",Guid.NewGuid().ToString("N").Substring(0,8));Directory.CreateDirectory(probe);
        string prefix="cp_probe_"+Guid.NewGuid().ToString("N").Substring(0,8)+"_";
        var mapping=model.Files.ToDictionary(p=>p,p=>Path.Combine(probe,prefix+Path.GetFileName(p)),StringComparer.OrdinalIgnoreCase);
        var renames=mapping.ToDictionary(p=>Path.GetFileNameWithoutExtension(p.Value),p=>Path.GetFileNameWithoutExtension(p.Key));
        IModelDoc2 original=Sw.GetOpenDocumentByName(model.Path) as IModelDoc2;
        if(original==null)throw new CadFault("CHECKPOINT_PROBE_CONTEXT_MISSING","恢复预检需要已打开的登记副本；未添加配合。",new{checkpoint_id=checkpointId});
        var before=Transforms(original);var settings=StudyStates(original);var beforeHashes=model.Files.ToDictionary(p=>p,p=>FileHash(p));string beforeMates=Json.Serialize(UserMates(original));
        LastOperationRestoration="pending";
        Exception failure=null;object evidence=null;
        try {
            foreach(var entry in mapping){string snapshot=Path.Combine(directory,Path.GetFileName(entry.Key));if(FileHash(snapshot)!=(string)hashes[entry.Key])throw new Exception("CHECKPOINT_INTEGRITY_FAILED");File.Copy(snapshot,entry.Value);File.SetAttributes(entry.Value,FileAttributes.Normal);}
            foreach(var entry in mapping)foreach(string reference in DiskDependencies(entry.Key,false))if(!mapping.ContainsKey(reference)||!Sw.ReplaceReferencedDocument(entry.Value,reference,mapping[reference]))throw new Exception("CHECKPOINT_PROBE_REDIRECT_FAILED");
            foreach(string path in mapping.Values)if(DiskDependencies(path,true).Any(p=>!mapping.Values.Contains(p,StringComparer.OrdinalIgnoreCase)))throw new Exception("CHECKPOINT_PROBE_NOT_ISOLATED");
            using(var scope=new Scope(this,mapping[model.Path],null)){
                if(scope.Doc.ConfigurationManager.ActiveConfiguration.Name!=model.Configuration&&!scope.Doc.ShowConfiguration2(model.Configuration))throw new Exception("CHECKPOINT_CONFIGURATION_MISMATCH");
                var target=new Dictionary<string,double[]>();
                foreach(string name in Transforms(scope.Doc).Keys){string old=name;foreach(var rename in renames)old=old.Replace(rename.Key,rename.Value);if(!expected.ContainsKey(old))throw new Exception("CHECKPOINT_PROBE_COMPONENT_SET_MISMATCH");target[name]=expected[old];}
                if(target.Count!=expected.Count)throw new Exception("CHECKPOINT_PROBE_COMPONENT_SET_MISMATCH");
                ApplyStudyStates(scope.Doc,states,target);VerifyStudyStates(scope.Doc,states);evidence=PoseChange(target,Transforms(scope.Doc));
            }
        }catch(Exception error){failure=error;}
        finally {
            try{
                foreach(var doc in (Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Where(d=>d.GetType()==2&&mapping.Values.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase))){var manager=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();foreach(string name in Names(manager)){var study=(IMotionStudy)manager.GetMotionStudy(name);if(study.IsActive){study.Stop();if(study.IsPlaying)throw new Exception("CHECKPOINT_PROBE_STOP_FAILED");}}}
                CloseUserDocuments(mapping.Values.ToArray());
                if((Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Any(d=>mapping.Values.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)))throw new Exception("CHECKPOINT_PROBE_DOCUMENT_STILL_OPEN");
            }catch(Exception cleanup){LastOperationRestoration="unknown";throw new CadFault("CHECKPOINT_PROBE_CLEANUP_FAILED","检查点预检副本未确认关闭；未添加配合，保留诊断并停止写入。",new{checkpoint_id=checkpointId,model_id=model.Id,mate_created=false,probe_path=probe,failure=failure==null?null:FailureEvidence(failure),cleanup_failure=FailureEvidence(cleanup)});}
        }
        var after=Transforms(original);bool filesUnchanged=beforeHashes.All(p=>FileHash(p.Key)==p.Value),matesUnchanged=Json.Serialize(UserMates(original))==beforeMates;
        bool unchanged=filesUnchanged&&matesUnchanged&&before.Count==after.Count&&before.All(p=>after.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,after[p.Key]));
        try{VerifyStudyStates(original,settings);}catch{unchanged=false;}
        if(!unchanged||LastContextRestoration=="unknown"){LastOperationRestoration="unknown";throw new CadFault("CHECKPOINT_PROBE_CONTEXT_CHANGED","恢复预检后原副本状态未确认；停止写入并保留现场。",new{model_id=model.Id,checkpoint_id=checkpointId,mate_created=false,probe_path=probe,pose_change=PoseChange(before,after),failure=failure==null?null:FailureEvidence(failure)});}
        bool restoreMismatch=failure is CadFault&&new[]{"CHECKPOINT_POSE_RESTORE_FAILED","CHECKPOINT_TIME_RESTORE_FAILED"}.Contains(((CadFault)failure).Code);
        var result=new{status=failure==null?"verified":restoreMismatch?"unrestorable":"probe_failed",model_id=model.Id,checkpoint_id=checkpointId,probe_path=probe,original_copy_unchanged=true,original_file_hashes_unchanged=filesUnchanged,original_mates_unchanged=matesUnchanged,mate_created=false,pose_change=evidence,failure=failure==null?null:FailureEvidence(failure)};
        AtomicJson(Path.Combine(directory,"restorability.json"),result);
        if(failure!=null){LastOperationRestoration="not_required";throw new CadFault(restoreMismatch?"MATE_CHECKPOINT_UNRESTORABLE":"CHECKPOINT_PROBE_FAILED",restoreMismatch?"动画检查点在独立副本中未通过恢复核验；未创建配合，当前副本状态保留。请显式选择可恢复的检查点或重新导入。":"检查点恢复预检未完成；未创建配合，当前副本状态保留。请查看准备阶段诊断。",result);}
        LastOperationRestoration="not_required";return result;
    }
}
