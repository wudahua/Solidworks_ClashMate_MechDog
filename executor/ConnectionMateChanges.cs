using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    List<Dictionary<string,object>> ReadConnectionMateChanges(IModelDoc2 doc,Dictionary<string,object> data,
        Dictionary<int,string[]> plannedLockReferences=null) {
        object raw;var changes=data.TryGetValue("mate_changes",out raw)?Json.Deserialize<List<Dictionary<string,object>>>(Json.Serialize(raw)):new List<Dictionary<string,object>>();
        if(changes==null||changes.Count>16)throw new CadFault("CONNECTION_REFERENCE_INVALID","既有配合状态修改最多16项。");
        var ids=new HashSet<int>();
        foreach(var c in changes) {
            if(c==null||c.Count!=6||!new[]{"native_feature_id","name","type","before","after","action"}.All(c.ContainsKey)||
               !(c["native_feature_id"] is int)||!(c["type"] is int)||!(c["before"] is bool)||!(c["after"] is bool)||
               !(c["name"] is string)||(bool)c["before"]==(bool)c["after"]||!ids.Add((int)c["native_feature_id"]))
                throw new CadFault("CONNECTION_REFERENCE_INVALID","既有配合修改字段、身份或前后状态无效。");
            bool lockChange=(c["action"] as string)=="set_lock_rotation";
            if((c["action"] as string)!="set_suppressed"&&(!lockChange||plannedLockReferences==null||(int)c["type"]!=1))
                throw new CadFault("CONNECTION_REFERENCE_INVALID","锁旋转只允许独立改造中已有的同心配合。");
            var f=EGAllMates(doc).SingleOrDefault(v=>v.GetID()==(int)c["native_feature_id"]);
            if(f==null||f.Name!=(string)c["name"]||((IMate2)f.GetSpecificFeature2()).Type!=(int)c["type"]||
               !new[]{0,1,2,3,5,6}.Contains((int)c["type"])||f.GetTypeName2().IndexOf("limit",StringComparison.OrdinalIgnoreCase)>=0)
                throw new CadFault("CONNECTION_PLAN_STALE","待修改配合的原生身份、类型或压缩状态变化，未写入。");
            if(lockChange) {
                var lockData=f.GetDefinition() as IConcentricMateFeatureData;
                if(EGSuppressed(f)||lockData==null||lockData.LockRotation!=(bool)c["before"])
                    throw new CadFault("CONNECTION_PLAN_STALE","同心配合的激活状态或原生锁态变化，未写入。");
                plannedLockReferences.Add((int)c["native_feature_id"],ConcentricRepairReferences(doc,(IMate2)f.GetSpecificFeature2()));
            } else if(EGSuppressed(f)!=(bool)c["before"])
                throw new CadFault("CONNECTION_PLAN_STALE","待修改配合的压缩状态变化，未写入。");
        }
        return changes;
    }
    string ConnectionExpectedMateParameters(string original,List<Dictionary<string,object>> changes,Dictionary<int,int> replacements=null) {
        var rows=Json.Deserialize<List<Dictionary<string,object>>>(original);
        foreach(var c in changes) {
            var row=rows.SingleOrDefault(v=>Convert.ToInt32(v["id"])==(int)c["native_feature_id"]);
            if(row==null)throw new CadFault("CONNECTION_REFERENCE_INVALID","修改配合不在完整参数快照内。");
            var mask=Json.Deserialize<bool[]>(Json.Serialize(row["suppression"]));
            bool lockChange=(string)c["action"]=="set_lock_rotation";
            if(mask==null||mask.Length!=1||mask[0]!=(lockChange?false:(bool)c["before"]))
                throw new CadFault("CONNECTION_REFERENCE_INVALID","修改配合的配置压缩掩码未完整绑定。");
            if(lockChange) {
                object state;
                if(!row.TryGetValue("lock_rotation",out state)||!(state is bool)||(bool)state!=(bool)c["before"])
                    throw new CadFault("CONNECTION_PLAN_STALE","检查点的同心锁态与预演不符。");
                row["lock_rotation"]=(bool)c["after"];
                int replacement;
                if(replacements!=null&&replacements.TryGetValue((int)c["native_feature_id"],out replacement))row["id"]=replacement;
            } else row["suppression"]=new[]{(bool)c["after"]};
        }
        return Json.Serialize(replacements==null||replacements.Count==0?rows:rows.OrderBy(r=>Convert.ToInt32(r["id"])).ToList());
    }
    static string[] ConcentricRepairReferences(IModelDoc2 doc,IMate2 mate) {
        if(mate==null||mate.Type!=1||mate.GetMateEntityCount()!=2)
            throw new CadFault("CONNECTION_REFERENCE_INVALID","同心配合必须有两个可核对的原生参考。");
        var references=new string[2];
        for(int i=0;i<2;i++) {
            var entity=mate.MateEntity(i);
            var reference=entity==null?null:entity.Reference;
            var bytes=reference==null?null:doc.Extension.GetPersistReference3(reference) as byte[];
            if(bytes==null||bytes.Length==0)throw new CadFault("CONNECTION_REFERENCE_INVALID","同心配合参考的持久标识不可读取。");
            references[i]=Convert.ToBase64String(bytes);
        }
        return references;
    }
    Dictionary<int,int> ApplyConnectionMateChanges(IModelDoc2 doc,List<Dictionary<string,object>> changes,
        Dictionary<int,string[]> plannedLockReferences=null,Dictionary<int,string[]> checkedLockReferences=null) {
        var replacements=new Dictionary<int,int>();
        foreach(var c in changes) {
            int id=(int)c["native_feature_id"];
            var features=EGAllMates(doc).ToDictionary(v=>v.GetID());
            IFeature f;
            if(!features.TryGetValue(id,out f)||f.Name!=(string)c["name"])
                throw new CadFault("CONNECTION_PLAN_STALE","既有配合原生身份已变化。");
            object action;
            if(c.TryGetValue("action",out action)&&(string)action=="set_lock_rotation") {
                string[] references;
                if(checkedLockReferences==null||plannedLockReferences==null||!plannedLockReferences.TryGetValue(id,out references))
                    throw new CadFault("CONNECTION_REFERENCE_INVALID","同心锁旋转只允许独立改造。");
                var data=f.GetDefinition() as IConcentricMateFeatureData;
                if(EGSuppressed(f)||data==null||data.LockRotation!=(bool)c["before"])
                    throw new CadFault("CONNECTION_PLAN_STALE","已确认同心配合的原生锁态不符。");
                if(!references.SequenceEqual(ConcentricRepairReferences(doc,(IMate2)f.GetSpecificFeature2())))
                    throw new CadFault("CONNECTION_PLAN_STALE","同心配合的原生参考自预演后变化，未执行该项。");
                data.LockRotation=(bool)c["after"];
                if(!f.ModifyDefinition(data,doc,null))throw new CadFault("CONNECTION_CREATE_FAILED","原生同心锁旋转修改失败。");
                var actual=EGAllMates(doc).ToDictionary(v=>v.GetID());
                var added=actual.Keys.Except(features.Keys).ToArray();
                var removed=features.Keys.Except(actual.Keys).ToArray();
                int observedId=id;
                if(added.Length==1&&removed.Length==1&&removed[0]==id)observedId=added[0];
                else if(added.Length!=0||removed.Length!=0)
                    throw new CadFault("CONNECTION_CREATE_FAILED","锁旋转后的原生配合增删超出确认范围。");
                var observed=actual[observedId];
                var read=observed.GetDefinition() as IConcentricMateFeatureData;
                if(observed.Name!=(string)c["name"]||EGSuppressed(observed)||read==null||read.LockRotation!=(bool)c["after"]||
                   !references.SequenceEqual(ConcentricRepairReferences(doc,(IMate2)observed.GetSpecificFeature2())))
                    throw new CadFault("CONNECTION_CREATE_FAILED","修改后的同心配合参考或锁态未通过原生读回。");
                if(observedId!=id)replacements.Add(id,observedId);
                checkedLockReferences.Add(observedId,references);
                continue;
            }
            if(f.Name!=(string)c["name"]||EGSuppressed(f)!=(bool)c["before"]||!f.SetSuppression2((bool)c["after"]?0:1,1,null)||EGSuppressed(f)!=(bool)c["after"])
                throw new CadFault("CONNECTION_CREATE_FAILED","已确认配合的压缩状态修改未通过原生读回。");
        }
        return replacements;
    }
    void RequireCheckpointMateState(IModelDoc2 doc,string expected,Dictionary<string,string> names=null) {
        string actual=ImportMateParameters(doc);
        if(actual==expected)return;
        // Study activation may restore a study-local mask. Restore only the
        // checkpoint's exact suppression mask after every other parameter,
        // feature identity and name has matched. Never adopt a stale import mask.
        var wanted=Json.Deserialize<List<Dictionary<string,object>>>(expected);
        var observed=Json.Deserialize<List<Dictionary<string,object>>>(actual);
        var features=EGAllMates(doc).ToDictionary(f=>f.GetID());
        if(names!=null&&wanted.Count==observed.Count&&names.Count==features.Count&&names.All(v=>features.ContainsKey(int.Parse(v.Key))&&features[int.Parse(v.Key)].Name==v.Value)) {
            var corrections=new List<Dictionary<string,object>>();
            foreach(var row in wanted) {
                int id=Convert.ToInt32(row["id"]);var current=observed.SingleOrDefault(v=>Convert.ToInt32(v["id"])==id);
                if(current==null)throw new CadFault("CHECKPOINT_RESTORE_UNVERIFIED","检查点配合身份未恢复。");
                var before=Json.Deserialize<bool[]>(Json.Serialize(current["suppression"]));var after=Json.Deserialize<bool[]>(Json.Serialize(row["suppression"]));
                if(before==null||after==null||before.Length!=1||after.Length!=1)throw new CadFault("CHECKPOINT_RESTORE_UNVERIFIED","检查点配合配置掩码不完整。");
                current["suppression"]=row["suppression"];
                if(before[0]!=after[0])corrections.Add(new Dictionary<string,object>{{"native_feature_id",id},{"name",names[id.ToString(System.Globalization.CultureInfo.InvariantCulture)]},{"before",before[0]},{"after",after[0]}});
            }
            if(Json.Serialize(observed)==expected) {
                ApplyConnectionMateChanges(doc,corrections);
                if(corrections.Count>0&&!doc.EditRebuild3())throw new CadFault("CHECKPOINT_RESTORE_UNVERIFIED","检查点配合掩码恢复后重建失败。");
                if(ImportMateParameters(doc)==expected)return;
            }
        }
        throw new CadFault("CHECKPOINT_RESTORE_UNVERIFIED","检查点配合参数或压缩状态未恢复，不能报告恢复通过。",new{mate_parameters_verified=false,automatic_mask_rewrite=false});
    }
}
