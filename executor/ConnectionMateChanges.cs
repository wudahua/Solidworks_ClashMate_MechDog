using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    List<Dictionary<string,object>> ReadConnectionMateChanges(IModelDoc2 doc,Dictionary<string,object> data) {
        object raw;var changes=data.TryGetValue("mate_changes",out raw)?Json.Deserialize<List<Dictionary<string,object>>>(Json.Serialize(raw)):new List<Dictionary<string,object>>();
        if(changes==null||changes.Count>16)throw new CadFault("CONNECTION_REFERENCE_INVALID","既有配合状态修改最多16项。");
        var ids=new HashSet<int>();
        foreach(var c in changes) {
            if(c.Count!=6||c.Keys.Any(k=>!new[]{"native_feature_id","name","type","before","after","action"}.Contains(k))||
               !(c["native_feature_id"] is int)||!(c["type"] is int)||!(c["before"] is bool)||!(c["after"] is bool)||
               (bool)c["before"]==(bool)c["after"]||(string)c["action"]!="set_suppressed"||!ids.Add((int)c["native_feature_id"]))
                throw new CadFault("CONNECTION_REFERENCE_INVALID","既有配合修改字段、身份或前后状态无效。");
            var f=EGAllMates(doc).SingleOrDefault(v=>v.GetID()==(int)c["native_feature_id"]);
            if(f==null||f.Name!=(string)c["name"]||((IMate2)f.GetSpecificFeature2()).Type!=(int)c["type"]||
               !new[]{0,1,2,3,5,6}.Contains((int)c["type"])||f.GetTypeName2().IndexOf("limit",StringComparison.OrdinalIgnoreCase)>=0||EGSuppressed(f)!=(bool)c["before"])
                throw new CadFault("CONNECTION_PLAN_STALE","待修改配合的原生身份、类型或压缩状态变化，未写入。");
        }
        return changes;
    }
    string ConnectionExpectedMateParameters(string original,List<Dictionary<string,object>> changes) {
        var rows=Json.Deserialize<List<Dictionary<string,object>>>(original);
        foreach(var c in changes) {
            var row=rows.SingleOrDefault(v=>Convert.ToInt32(v["id"])==(int)c["native_feature_id"]);
            if(row==null)throw new CadFault("CONNECTION_REFERENCE_INVALID","修改配合不在完整参数快照内。");
            var mask=Json.Deserialize<bool[]>(Json.Serialize(row["suppression"]));
            if(mask==null||mask.Length!=1||mask[0]!=(bool)c["before"])throw new CadFault("CONNECTION_REFERENCE_INVALID","修改配合的配置压缩掩码未完整绑定。");
            row["suppression"]=new[]{(bool)c["after"]};
        }
        return Json.Serialize(rows);
    }
    void ApplyConnectionMateChanges(IModelDoc2 doc,List<Dictionary<string,object>> changes) {
        foreach(var c in changes) {
            var f=EGAllMates(doc).Single(v=>v.GetID()==(int)c["native_feature_id"]);
            if(f.Name!=(string)c["name"]||EGSuppressed(f)!=(bool)c["before"]||!f.SetSuppression2((bool)c["after"]?0:1,1,null)||EGSuppressed(f)!=(bool)c["after"])
                throw new CadFault("CONNECTION_CREATE_FAILED","已确认配合的压缩状态修改未通过原生读回。");
        }
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
