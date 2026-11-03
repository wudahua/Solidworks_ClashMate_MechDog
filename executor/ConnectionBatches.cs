using System;
using System.Linq;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    class ConnectionBatchScope {
        public string Id,Manifest;public int Index,Count,GoalCount;
    }
    class ConnectionBatchProgress {
        public ConnectionBatchScope Scope;public int Next;public bool Failed;
        public List<Dictionary<string,object>> Goals=new List<Dictionary<string,object>>();
        public ConnectionInternalWitness InternalWitness;public string Parameters;public int[] MateIds;public Dictionary<string,double[]> Poses;public Dictionary<string,bool> Fixed;
    }
    readonly Dictionary<string,ConnectionBatchProgress> connectionBatchProgress=new Dictionary<string,ConnectionBatchProgress>();
    public object ConnectionReferenceState(string id,bool verificationDetails=false) {
        var model=GetUserModel(id);
        using(var scope=new Scope(this,model.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
            Fingerprint(scope.Doc,model.Path);RequireMatesHealthy(scope.Doc);RequireConnectionBatchBaseline(id,scope.Doc);
            return new{model_id=id,reference_state_signature=MateSignature(model,scope.Doc),
                mate_parameters_signature=verificationDetails?StableId("parameters_",ImportMateParameters(scope.Doc)):null,
                native_mate_count=verificationDetails?(int?)EGAllMates(scope.Doc).Length:null,study_states=verificationDetails?StudyStates(scope.Doc):null,
                fixed_states=verificationDetails?UserComponents(scope.Doc).ToDictionary(c=>GTComponentId(scope.Doc,c),c=>c.IsFixed()):null,
                signature_domain="full_mate_plan_saved_and_live_state_not_circular_query",write_dispatched=false};
        }
    }
    ConnectionBatchScope ReadConnectionBatch(string modelId,Dictionary<string,object> outer,out Dictionary<string,object> data) {
        data=outer;
        if(!outer.ContainsKey("batch_payload_json")) {
            if(connectionBatchProgress.ContainsKey(modelId))throw new CadFault("CONNECTION_PLAN_STALE","该模型已有整装配事务，不能混入其他写入方案。");
            return null;
        }
        if(outer.Count!=3||!outer.ContainsKey("batch_transaction")||!outer.ContainsKey("reference_state_signature")||!(outer["batch_payload_json"] is string))throw new CadFault("CONNECTION_REFERENCE_INVALID","整装配批次信封无效。");
        var header=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(outer["batch_transaction"]));
        var names=new[]{"transaction_id","batch_index","batch_count","global_goal_count","payload_hashes"};
        if(header.Count!=names.Length||header.Keys.Any(k=>!names.Contains(k))||!(header["transaction_id"] is string)||
            !Regex.IsMatch((string)header["transaction_id"],"^[a-f0-9]{32}$")||!(header["batch_index"] is int)||!(header["batch_count"] is int)||!(header["global_goal_count"] is int))throw new CadFault("CONNECTION_REFERENCE_INVALID","整装配批次身份或计数无效。");
        var scope=new ConnectionBatchScope{Id=(string)header["transaction_id"],Index=(int)header["batch_index"],Count=(int)header["batch_count"],GoalCount=(int)header["global_goal_count"]};
        var hashes=Json.Deserialize<List<object>>(Json.Serialize(header["payload_hashes"]));
        if(scope.GoalCount<1||scope.GoalCount>128||scope.Count!=(scope.GoalCount+7)/8||scope.Index<0||scope.Index>=scope.Count||
            hashes==null||hashes.Count!=scope.Count||hashes.Any(h=>!(h is string)||!Regex.IsMatch((string)h,"^[a-f0-9]{64}$"))||
            ConnectionRequestFingerprint.Hash((string)outer["batch_payload_json"])!=(string)hashes[scope.Index])throw new CadFault("CONNECTION_REFERENCE_INVALID","批次清单、顺序或精确载荷哈希不符。");
        scope.Manifest=string.Join(":",hashes.Cast<string>());
        ValidateConnectionBatch(modelId,scope);
        data=Json.Deserialize<Dictionary<string,object>>((string)outer["batch_payload_json"]);
        if(data.Count!=4||data.Keys.Any(k=>!new[]{"actions","goals","fixed_state_changes","group_bindings"}.Contains(k)))throw new CadFault("CONNECTION_REFERENCE_INVALID","批次载荷字段不符。");
        data["reference_state_signature"]=outer["reference_state_signature"];
        return scope;
    }
    void ValidateConnectionBatch(string modelId,ConnectionBatchScope scope) {
        ConnectionBatchProgress progress;
        if(!connectionBatchProgress.TryGetValue(modelId,out progress)) {
            if(scope.Index!=0)throw new CadFault("CONNECTION_PLAN_STALE","整装配事务须从已确认的首批开始，不跳过目标。");
        } else if(progress.Failed||progress.Next!=scope.Index||progress.Scope.Id!=scope.Id||progress.Scope.Manifest!=scope.Manifest||progress.Scope.Count!=scope.Count||progress.Scope.GoalCount!=scope.GoalCount)
            throw new CadFault("CONNECTION_PLAN_STALE","批次事务身份、清单或前序完成状态不符，未继续写入。");
    }
    void BeginConnectionBatch(ConnectionPlan plan) {
        if(plan.Batch==null)return;ValidateConnectionBatch(plan.ModelId,plan.Batch);
        if(!connectionBatchProgress.ContainsKey(plan.ModelId))connectionBatchProgress[plan.ModelId]=new ConnectionBatchProgress{Scope=plan.Batch,Poses=plan.Poses,Fixed=plan.Fixed,Parameters=plan.OriginalParameters,MateIds=plan.OriginalMateIds,InternalWitness=plan.HierarchyWitness};
        connectionTrialGoals.Remove(plan.ModelId);
    }
    void RequireConnectionBatchBaseline(string modelId,IModelDoc2 doc) {
        ConnectionBatchProgress p;if(!connectionBatchProgress.TryGetValue(modelId,out p))return;
        var current=Transforms(doc);var flags=UserComponents(doc).ToDictionary(c=>c.Name2,c=>c.IsFixed());
        if(p.Failed||p.Poses.Count!=current.Count||p.Poses.Any(v=>!current.ContainsKey(v.Key)||!PoseValidation.Matches(v.Value,current[v.Key]))||
            flags.Count!=p.Fixed.Count||flags.Any(v=>!p.Fixed.ContainsKey(v.Key)||p.Fixed[v.Key]!=v.Value)||EGAllMates(doc).Length!=p.MateIds.Length||
            CompletionOriginalParameters(doc,p.MateIds)!=p.Parameters||!ConnectionInternalWitnessMatches(p.InternalWitness,ConnectionInternalAssemblyWitness(GetUserModel(modelId),doc)))throw new CadFault("CONNECTION_PLAN_STALE","前批已验证的姿态、配合或固定状态发生改变，未采用漂移状态继续。");
    }
    void CompleteConnectionBatch(ConnectionPlan plan,IModelDoc2 doc) {
        if(plan.Batch==null){connectionTrialGoals[plan.ModelId]=plan.Goals;return;}
        var p=connectionBatchProgress[plan.ModelId];p.Goals.AddRange(plan.Goals);p.Next++;
        p.MateIds=EGAllMates(doc).Select(f=>f.GetID()).ToArray();p.Parameters=CompletionOriginalParameters(doc,p.MateIds);p.Fixed=plan.ExpectedFixed;p.InternalWitness=ConnectionInternalAssemblyWitness(GetUserModel(plan.ModelId),doc);
        if(p.Next==plan.Batch.Count) {
            if(p.Goals.Count!=plan.Batch.GoalCount)throw new CadFault("CONNECTION_CREATE_FAILED","整装配目标数量未闭合，未准入验证。");
            connectionTrialGoals[plan.ModelId]=p.Goals;
        }
    }
    void FailConnectionBatch(ConnectionPlan plan) {
        ConnectionBatchProgress p;if(plan.Batch!=null&&connectionBatchProgress.TryGetValue(plan.ModelId,out p)){p.Failed=true;connectionTrialGoals.Remove(plan.ModelId);}
    }
    void RequireCompletedConnectionBatches(string modelId) {
        ConnectionBatchProgress p;if(connectionBatchProgress.TryGetValue(modelId,out p)&&(p.Failed||p.Next!=p.Scope.Count))
            throw new CadFault("CONNECTION_PLAN_STALE","整装配批次未全部完成，不能把部分成果作为完整验证。");
    }
}
