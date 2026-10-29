using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

// Registered isolated assemblies only. No gear roles or Motion Calculate.
public partial class Cad {
    class ConnectionPlan {
        public string Id,ModelId,Signature,OriginalParameters;public int Revision;
        public bool Consumed;public List<Dictionary<string,object>> Actions,Goals;
        public Dictionary<string,double[]> Poses;public Dictionary<string,bool> Fixed;
    }
    readonly Dictionary<string,ConnectionPlan> connectionPlans=new Dictionary<string,ConnectionPlan>();
    readonly HashSet<string> connectionModelScopes=new HashSet<string>();
    readonly Dictionary<string,List<Dictionary<string,object>>> connectionTrialGoals=new Dictionary<string,List<Dictionary<string,object>>>();
    string ConnectionModelTab() {
        string language=Sw.GetCurrentLanguage();
        string tab=language=="english"?"Model":language=="chinese-simplified"||language=="chinese"?"模型":null;
        if(tab==null)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","当前语言的模型标签尚未核验。");
        return tab;
    }
    void RequireConnectionModelScope(UserModel m,IModelDoc2 doc) {
        var manager=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();string tab=ConnectionModelTab();
        if(!connectionModelScopes.Contains(m.Id)||Names(manager).Contains(tab)||StudyStates(doc).Any(v=>v.active))
            throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","有界试验要求本次已验证的装配模型作用域，不在历史算例中移动。");
    }
    object PrepareConnectionModelScope(UserModel m,IModelDoc2 doc) {
        var before=Transforms(doc);string mates=ImportMateParameters(doc);
        var states=StudyStates(doc);string clocks=Json.Serialize(states.Select(v=>new{v.name,v.time_s}).OrderBy(v=>v.name).ToArray());
        var manager=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();string tab=ConnectionModelTab();
        if(Names(manager).Contains(tab)||!manager.ActivateMotionStudy(tab)||StudyStates(doc).Any(v=>v.active))
            throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","未核验进入装配模型作用域。");
        var after=Transforms(doc);
        if(before.Count!=after.Count||!before.All(v=>after.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,after[v.Key]))||mates!=ImportMateParameters(doc)||
            clocks!=Json.Serialize(StudyStates(doc).Select(v=>new{v.name,v.time_s}).OrderBy(v=>v.name).ToArray()))
            throw new CadFault("CONNECTION_CREATE_FAILED","切换模型作用域未保持导入保存姿态、配合或历史算例时钟。");
        connectionModelScopes.Add(m.Id);
        return new{strategy="verified_model_context_saved_pose_only",historical_studies_deleted=false,historical_clocks_unchanged=true,
            saved_poses_and_mate_parameters_unchanged=true,model_context_verified=true,old_study_frame_zero_verified=false};
    }
    object ConnectionNonlinearObservation(IFeature feature,IMate2 mate) {
        try {
            if(mate.Type==17) {
                var data=feature.GetDefinition() as IScrewMateFeatureData;
                if(data==null)return new{native_feature_id=feature.GetID(),kind="screw",status="definition_unavailable"};
                return new{native_feature_id=feature.GetID(),kind="screw",status="observed",native_revolution_type=data.RevolutionType,
                    native_revolution_value=data.RevolutionVal,reverse=data.Reverse,mate_alignment=data.MateAlignment,
                    modelled_as_linear_equality=false,observation_not_native_motion_verification=true};
            }
            if(mate.Type==5&&feature.GetTypeName2().ToLowerInvariant().Contains("limit")) {
                var data=feature.GetDefinition() as IDistanceMateFeatureData;
                if(data==null)return new{native_feature_id=feature.GetID(),kind="limit_distance",status="definition_unavailable"};
                return new{native_feature_id=feature.GetID(),kind="limit_distance",status="observed",distance_m=data.Distance,
                    minimum_distance_m=data.MinimumDistance,maximum_distance_m=data.MaximumDistance,
                    flip_dimension=data.FlipDimension,mate_alignment=data.MateAlignment,
                    modelled_as_linear_equality=false,observation_not_native_motion_verification=true};
            }
            return null;
        }catch(Exception error){return new{native_feature_id=feature.GetID(),status="unavailable",error=error.GetType().Name};}
    }
    public object SurveyAssemblyConnections(string id) {
        var model=GetUserModel(id);
        using(var scope=new Scope(this,model.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
            var doc=scope.Doc;Fingerprint(doc,model.Path);string signature=MateSignature(model,doc);var cs=UserComponents(doc);
            if(cs.Length>128)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","基础连接调查限128个已解析顶层零件。");
            var rows=new List<object>();var skipped=new List<object>();var templates=new Dictionary<string,List<CompletionPlaneTemplate>>();
            int completed=0;foreach(var c in cs) {
                Progress(activeJobId,"connection_geometry_survey",completed++,cs.Length,null);
                var part=c.GetModelDoc2() as IModelDoc2;
                if(c.IsSuppressed()||c.IsSpeedPak||part==null||part.GetType()!=1||!model.Files.Contains(c.GetPathName(),StringComparer.OrdinalIgnoreCase)) {
                    skipped.Add(new{instance=c.Name2,reason="not_resolved_owned_top_level_part"});continue;
                }
                string status;var faces=ComponentFaces(c,out status);var cylinders=faces.Where(f=>((ISurface)f.GetSurface()).IsCylinder()).OrderByDescending(f=>f.GetArea()).ToArray();
                var planes=faces.Where(f=>((ISurface)f.GetSurface()).IsPlane()).OrderByDescending(f=>f.GetArea()).ToArray();
                Func<IFace2,string,object> shape=(f,kind)=>{var row=MateGeometry(doc,f,c);row["native_reference"]=GTReference(doc,f);row["reference_kind"]=kind;row["area_m2"]=f.GetArea();return row;};
                rows.Add(new{component_id=GTComponentId(doc,c),instance=c.Name2,fixed_component=c.IsFixed(),constraint_state=ComponentConstraintObservation(c),
                    transform=(double[])c.GetTotalTransform(false).ArrayData,box=c.GetBox(false,false),
                    cylinders=cylinders.Take(24).Select(f=>shape(f,"cylindrical_face")).ToArray(),
                    planes=planes.Take(16).Select(f=>shape(f,"planar_face")).ToArray(),
                    completion_planes=CompletionPlaneReferences(doc,c,templates),
                    geometry_complete=cylinders.Length<=24&&planes.Length<=16,geometry_status=status});
            }
            var mates=UserMates(doc,model);var structure=AssemblyStructureObservation(doc);var studies=StudyStates(doc);
            var nonlinear=BasicMateFeatures(doc).Select(f=>{var mate=f.GetSpecificFeature2() as IMate2;return mate==null?null:ConnectionNonlinearObservation(f,mate);}).Where(v=>v!=null).ToArray();
            if(signature!=MateSignature(model,doc))throw new CadFault("CONNECTION_PLAN_STALE","调查期间状态发生变化。");
            SaveUserModel(model);
            return new{model_id=id,reference_state_signature=signature,components=rows,mates=mates,structural_relations=structure,
                studies=studies,nonlinear_constraints=nonlinear,skipped=skipped,inventory_complete=skipped.Count==0,write_dispatched=false,
                native_motion_study_solved=false,geometry_budget=new{cylinders_per_component=24,planes_per_component=16},
                recommendation_scope="basic_joint_goal_planning_not_global_DOF_or_design_intent",source_files_unchanged=UserSourcesUnchanged(model)};
        }
    }
    object ConnectionReference(IModelDoc2 doc,IComponent2 component,string reference,string kind) {
        if(kind=="datum_plane")return CompletionReference(doc,component,reference);
        int error;var entity=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out error) as IFace2;
        var owner=entity==null?null:((IEntity)entity).GetComponent() as IComponent2;
        if(error!=0||entity==null||owner==null||owner.Name2!=component.Name2)throw new CadFault("CONNECTION_REFERENCE_INVALID","参考未解析到确认组件。");
        var surface=entity.GetSurface() as ISurface;
        if(surface==null||kind=="cylindrical_face"&&!surface.IsCylinder()||kind=="planar_face"&&!surface.IsPlane()||kind!="cylindrical_face"&&kind!="planar_face")throw new CadFault("CONNECTION_REFERENCE_INVALID","参考几何类型不符。");
        return entity;
    }
    void ValidateConnectionAction(UserModel m,IModelDoc2 doc,Dictionary<string,object> a) {
        string kind=(string)a["kind"];
        if(!new[]{"concentric","parallel","distance","perpendicular","angle"}.Contains(kind))throw new CadFault("CONNECTION_REFERENCE_INVALID","新增约束类型未支持。");
        var ca=ResolveUserComponent(m,doc,(string)a["component_a"]);var cb=ResolveUserComponent(m,doc,(string)a["component_b"]);
        if(ca.Name2==cb.Name2||ca.IsPatternInstance()||cb.IsPatternInstance())throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","阵列实例不单独添加基础连接约束。");
        ConnectionReference(doc,ca,(string)a["reference_a"],(string)a["reference_kind_a"]);
        ConnectionReference(doc,cb,(string)a["reference_b"],(string)a["reference_kind_b"]);
    }
    public object PreviewAssemblyConnections(string id,string proposalJson) {
        var m=GetUserModel(id);var data=Json.Deserialize<Dictionary<string,object>>(proposalJson);
        using(var scope=new Scope(this,m.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
            var doc=scope.Doc;Fingerprint(doc,m.Path);RequireMatesHealthy(doc);
            if((string)data["reference_state_signature"]!=MateSignature(m,doc))throw new CadFault("CONNECTION_PLAN_STALE","只读方案已过期。");
            var actions=Json.Deserialize<List<Dictionary<string,object>>>(Json.Serialize(data["actions"]));
            var goals=Json.Deserialize<List<Dictionary<string,object>>>(Json.Serialize(data["goals"]));
            if(actions.Count>64||goals.Count<1||goals.Count>8)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","首批每项最多8个连接目标、64项新增约束。");
            foreach(var action in actions)ValidateConnectionAction(m,doc,action);
            foreach(var goal in goals) {
                if(!new[]{"rigid","revolute","prismatic"}.Contains((string)goal["kind"]))throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","目标连接类型未支持。");
                var a=ResolveUserComponent(m,doc,(string)goal["component_a"]);var b=ResolveUserComponent(m,doc,(string)goal["component_b"]);
                if(a.Name2==b.Name2||a.IsFixed())throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","试验目标须为不同的浮动组件，未自动解除固定。");
                object trialDriver;
                if(goal.TryGetValue("linear_trial_driver",out trialDriver)&&trialDriver!=null)ValidateConnectionAction(m,doc,Json.Deserialize<Dictionary<string,object>>(Json.Serialize(trialDriver)));
                if(goal.TryGetValue("rotary_trial_driver",out trialDriver)&&trialDriver!=null)ValidateConnectionAction(m,doc,Json.Deserialize<Dictionary<string,object>>(Json.Serialize(trialDriver)));
            }
            var cs=UserComponents(doc);var plan=new ConnectionPlan{Id=Guid.NewGuid().ToString("N"),ModelId=id,Revision=m.Revision,
                Signature=MateSignature(m,doc),OriginalParameters=CompletionOriginalParameters(doc,EGAllMates(doc).Select(f=>f.GetID()).ToArray()),Actions=actions,Goals=goals,
                Poses=Transforms(doc),Fixed=cs.ToDictionary(c=>c.Name2,c=>c.IsFixed())};connectionPlans[plan.Id]=plan;
            if(cs.Any(c=>!ConnectionRigidTransform((double[])c.GetTotalTransform(false).ArrayData))) {
                connectionPlans.Remove(plan.Id);throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","有界验证首批要求单位尺度的刚体变换。");
            }
            var nonzero=StudyStates(doc).Where(v=>Math.Abs(v.time_s)>1e-8).Select(v=>new{name=v.name,time_s=v.time_s}).ToArray();
            return new{plan_id=plan.Id,model_id=id,expected_added_mates=actions.Count,goals=goals,
                checkpoint_probe_required=true,original_mates_deleted=false,original_mates_suppressed=false,fixed_state_changes=new string[0],
                initial_state_preparation=new{strategy="verified_model_context_saved_pose_only",nonzero_historical_clocks_retained_inactive=nonzero,historical_studies_deleted=false,old_frame_zero_claimed=false,requires_confirmation=true},
                verification=new{method="native_assembly_solver_bounded_pose_trials_not_Motion_Analysis",translation_step_m=.0001,rotation_step_rad=Math.PI/3600,
                    maximum_any_component_translation_m=.005,maximum_any_component_rotation_rad=Math.PI/180,
                    full_component_pose_health_and_restore_checks=true,whole_range_or_global_DOF_certified=false},
                linear_allowed_trial_strategy="temporary_native_distance_constraint_then_verified_result_checkpoint_restore_if_reference_available",
                rotary_allowed_trial_strategy="temporary_native_angle_constraint_then_verified_result_checkpoint_restore_if_reference_available",
                native_compatibility_verified=false,write_dispatched=false};
        }
    }
    IFeature CreateConnectionMate(UserModel m,IModelDoc2 doc,Dictionary<string,object> action) {
        ValidateConnectionAction(m,doc,action);var ca=ResolveUserComponent(m,doc,(string)action["component_a"]);var cb=ResolveUserComponent(m,doc,(string)action["component_b"]);
        var ra=ConnectionReference(doc,ca,(string)action["reference_a"],(string)action["reference_kind_a"]);
        var rb=ConnectionReference(doc,cb,(string)action["reference_b"],(string)action["reference_kind_b"]);
        string kind=(string)action["kind"];int type=kind=="concentric"?1:kind=="parallel"?3:kind=="perpendicular"?2:kind=="angle"?6:5;
        doc.ClearSelection2(true);
        try {
            var select=((ISelectionMgr)doc.SelectionManager).CreateSelectData();select.Mark=1;
            Func<object,bool,bool> choose=(reference,append)=>reference is IFeature?((IFeature)reference).Select2(append,1):((IEntity)reference).Select4(append,select);
            if(!choose(ra,false)||!choose(rb,true))throw new CadFault("CONNECTION_REFERENCE_INVALID","原生选择失败。");
            var sm=(ISelectionMgr)doc.SelectionManager;
            if(sm.GetSelectedObjectCount2(1)!=2||GTComponentId(doc,(IComponent2)sm.GetSelectedObjectsComponent4(1,1))!=(string)action["component_a"]||
                GTComponentId(doc,(IComponent2)sm.GetSelectedObjectsComponent4(2,1))!=(string)action["component_b"])throw new CadFault("CONNECTION_REFERENCE_INVALID","选择组件上下文不一致。");
            double distance=type==5?Convert.ToDouble(action["value"]):0,angle=type==6?Convert.ToDouble(action["value"]):0;int error;
            var before=new HashSet<int>(EGAllMates(doc).Select(f=>f.GetID()));
            bool flip=type==5&&action.ContainsKey("flip_dimension")&&Convert.ToBoolean(action["flip_dimension"]);
            var added=((IAssemblyDoc)doc).AddMate5(type,2,flip,distance,distance,distance,1,1,angle,angle,angle,false,false,0,out error);
            if(added==null||error!=1)throw new CadFault("CONNECTION_CREATE_FAILED","原生新增约束未成功。",new{kind=kind,native_error=error,native_error_name=Enum.GetName(typeof(SolidWorks.Interop.swconst.swAddMateError_e),error)});
            var created=EGAllMates(doc).Where(f=>!before.Contains(f.GetID())).ToArray();
            var feature=created.Length==1?created[0]:null;
            if(feature==null||((IMate2)feature.GetSpecificFeature2()).Type!=type)throw new CadFault("CONNECTION_CREATE_FAILED","新增原生特征未核验。");
            return feature;
        }finally{doc.ClearSelection2(true);}
    }
    public object ApplyAssemblyConnections(string planId,bool confirmed,bool testFault=false) {
        ConnectionPlan p;if(!connectionPlans.TryGetValue(planId,out p))throw new CadFault("CONNECTION_PLAN_STALE","方案不存在。");
        if(!confirmed)throw new CadFault("CONFIRMATION_REQUIRED","须确认基础连接方案和有界运动试验。");
        if(p.Consumed)throw new CadFault("TASK_ALREADY_EXECUTED","方案已消费。");
        if(testFault&&p.Actions.Count==0)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","回滚夹具必须有待新增约束，不能将无写入当回滚验证。");
        if(testFault&&System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TEST_DISABLED");
        var m=GetUserModel(p.ModelId);
        using(var scope=new Scope(this,m.Path,null))if(MateSignature(m,scope.Doc)!=p.Signature||m.Revision!=p.Revision)throw new CadFault("CONNECTION_PLAN_STALE","当前模型与方案不一致。");
        p.Consumed=true;string cp=null;bool mutating=false;
        try {
            Progress(activeJobId,"connection_create_checkpoint",0,0,null);
            var checkpoint=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(m.Id)));cp=(string)checkpoint["checkpoint_id"];
            Progress(activeJobId,"connection_checkpoint_reopen",0,0,null);
            var probe=ProbeCompletionSavedCheckpoint(m.Id,cp,p.Poses,p.Fixed);m=GetUserModel(m.Id);
            using(var scope=new Scope(this,m.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
                Progress(activeJobId,"connection_model_context",0,0,null);
                var doc=scope.Doc;mutating=true;LastOperationRestoration="pending";var prepared=PrepareConnectionModelScope(m,doc);var originalIds=EGAllMates(doc).Select(f=>f.GetID()).ToArray();
                var evidence=new List<object>();int index=0;
                foreach(var action in p.Actions) {
                    Progress(activeJobId,"basic_connection_completion",index++,p.Actions.Count,null);
                    action["model_id"]=m.Id;var added=CreateConnectionMate(m,doc,action);CheckMate(added,"basic_connection_supplement");
                    if(!doc.EditRebuild3())throw new CadFault("CONNECTION_CREATE_FAILED","新增约束后重建失败。");RequireMatesHealthy(doc);
                    evidence.Add(VerifyCompletionPose(doc,p.Poses,added,action));
                    if(testFault)throw new CadFault("CONNECTION_CREATE_FAILED","受控验收故障：验证完整回退。");
                }
                if(CompletionOriginalParameters(doc,originalIds)!=p.OriginalParameters||EGAllMates(doc).Length!=originalIds.Length+p.Actions.Count)
                    throw new CadFault("CONNECTION_CREATE_FAILED","原配合或新增数量发生非预期变化。");
                var actual=Transforms(doc);if(!p.Poses.All(v=>actual.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,actual[v.Key])))throw new CadFault("CONNECTION_CREATE_FAILED","基础连接补齐改变初态。");
                if(UserComponents(doc).Any(c=>c.IsFixed()!=p.Fixed[c.Name2]))throw new CadFault("CONNECTION_CREATE_FAILED","补齐改变固定状态。");
                Progress(activeJobId,"connection_save_verified_result",0,0,null);
                SaveOwnedDocuments(m);m.Revision++;SaveUserModel(m);VerifyUserSources(m);LastOperationRestoration="restored";
                connectionTrialGoals[m.Id]=p.Goals;
                return new{model_id=m.Id,plan_id=planId,checkpoint_id=cp,checkpoint_probe=probe,initial_state_preparation=prepared,
                    added_mates=p.Actions.Count,goals=p.Goals,evidence=evidence,native_health_verified=true,motion_verified=false,
                    source_files_unchanged=true,restoration_status="restored"};
            }
        }catch(Exception error) {
            if(error is COMException||error is NativeCommandStateException||LastContextRestoration=="unknown") {LastOperationRestoration="unknown";throw new CadFault("CONNECTION_NATIVE_UNKNOWN","原生状态未知，未重试写入或恢复。",new{checkpoint_id=cp,original_failure=FailureEvidence(error)});}
            if(!mutating)throw;
            try{RestoreUserCheckpoint(m.Id,cp);LastOperationRestoration="restored";}catch(Exception rollback){LastOperationRestoration="unknown";throw new CadFault("CONNECTION_NATIVE_UNKNOWN","已知失败后恢复未验证。",new{checkpoint_id=cp,original_failure=FailureEvidence(error),rollback_failure=FailureEvidence(rollback)});}
            throw new CadFault("CONNECTION_APPLY_ROLLED_BACK","基础连接未通过，已恢复检查点。",new{checkpoint_id=cp,original_failure=FailureEvidence(error),rollback_verified=true});
        }
    }
    Dictionary<string,double[]> ConnectionPoses(IModelDoc2 doc) {
        return UserComponents(doc).Where(c=>!c.IsSuppressed()).ToDictionary(c=>GTComponentId(doc,c),c=>(double[])c.GetTotalTransform(false).ArrayData);
    }
    static bool ConnectionRigidTransform(double[] p) {
        if(p==null||p.Length!=16||p.Any(x=>double.IsNaN(x)||double.IsInfinity(x))||Math.Abs(p[12]-1)>1e-9||p.Skip(13).Any(x=>Math.Abs(x)>1e-9))return false;
        for(int i=0;i<3;i++)for(int j=0;j<3;j++)if(Math.Abs(Enumerable.Range(0,3).Sum(k=>p[3*i+k]*p[3*j+k])-(i==j?1:0))>1e-7)return false;
        double det=p[0]*(p[4]*p[8]-p[5]*p[7])-p[1]*(p[3]*p[8]-p[5]*p[6])+p[2]*(p[3]*p[7]-p[4]*p[6]);
        return Math.Abs(det-1)<1e-7;
    }
    bool ConnectionMove(IModelDoc2 doc,IComponent2 moving,double[] target,out object observation) {
        var transform=(MathTransform)((IMathUtility)Sw.GetMathUtility()).CreateTransform(target);
        bool accepted=moving.SetTransformAndSolve3(transform,true);
        observation=new{backend="SetTransformAndSolve3",this_configuration=true};
        if(!doc.EditRebuild3())throw new CadFault("CONNECTION_CREATE_FAILED","有界位姿请求后装配重建未通过。");
        // Capture all poses in the caller before checking known mate errors.
        return accepted;
    }
    public object ProbeAssemblyConnectionPose(string id,string componentId,string targetJson,string checkpointId,string probeId,int goalIndex=-1,bool allowedTrial=false) {
        if(!System.Text.RegularExpressions.Regex.IsMatch(probeId,"^[a-f0-9]{32}$"))throw new CadFault("CONNECTION_REFERENCE_INVALID","试验ID无效。");
        var timing=new OperationTiming("connection_probe_native_body_before_artifact_write_and_transport");timing.Start("parse_model_and_target");
        var m=GetUserModel(id);string requestHash=ConnectionRequestFingerprint.Hash(targetJson);var target=Json.Deserialize<double[]>(targetJson);string path=Path.Combine(Root,"runs","connection-probes",probeId+".json");Directory.CreateDirectory(Path.GetDirectoryName(path));
        Dictionary<string,double[]> before=null,after=null,restored=null;bool accepted=false,undoAccepted=false;string parameters=null;Dictionary<string,bool> fixedStates=null;
        bool touched=false,needsCheckpoint=false,undoAttempted=false,checkpointPerTrial=false,angularDriver=false;object postRestoreBatch=null;object moveObservation=null,undoObservation=null;Dictionary<string,object> driver=null;int[] originalIds=null;int? temporaryFeature=null;
        List<Dictionary<string,object>> goals;
        if(connectionTrialGoals.TryGetValue(id,out goals)&&goalIndex>=0&&goalIndex<goals.Count) {
            var goal=goals[goalIndex];object raw;
            if((string)goal["component_a"]!=componentId)throw new CadFault("CONNECTION_REFERENCE_INVALID","试验目标组件与确认方案不符。");
            checkpointPerTrial=(string)goal["kind"]=="revolute";
            if(allowedTrial&&(string)goal["kind"]=="prismatic"&&goal.TryGetValue("linear_trial_driver",out raw)&&raw!=null)driver=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(raw));
            if(allowedTrial&&checkpointPerTrial&&goal.TryGetValue("rotary_trial_driver",out raw)&&raw!=null){driver=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(raw));angularDriver=true;}
        }
        try {
            timing.Start("scope_and_initial_batch");
            using(var scope=new Scope(this,m.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
                timing.Start("model_scope_health_fingerprint_and_identity");
                var doc=scope.Doc;RequireConnectionModelScope(m,doc);RequireMatesHealthy(doc);Fingerprint(doc,m.Path);var moving=ResolveUserComponent(m,doc,componentId);
                if(moving.IsFixed()||moving.IsPatternInstance()||!ConnectionRigidTransform(target))throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","试验组件或目标变换无效。");
                timing.Start("initial_component_poses");before=ConnectionPoses(doc);var initial=before[componentId];
                if(PoseValidation.TranslationDistance(initial,target)>.005||PoseValidation.RotationDistance(initial,target)>Math.PI/180)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","试验超出5mm/1度封顶，未派发移动。");
                timing.Start("initial_mates_parameters_and_fixed_states");originalIds=EGAllMates(doc).Select(f=>f.GetID()).ToArray();parameters=CompletionOriginalParameters(doc,originalIds);fixedStates=UserComponents(doc).ToDictionary(c=>GTComponentId(doc,c),c=>c.IsFixed());
                Progress(activeJobId,"connection_native_pose_trial",0,0,null);
                timing.Start("native_trial_move_and_rebuild");
                if(driver!=null) {
                    if(angularDriver) {
                        if(Math.Abs(PoseValidation.RotationDistance(initial,target)-Math.PI/3600)>1e-8)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","临时角度试验仅用于已确认的正反0.05度请求。");
                        var na=RelativeMotion.Unit(Json.Deserialize<double[]>(Json.Serialize(driver["normal_a_global"])));
                        var nb=RelativeMotion.Unit(Json.Deserialize<double[]>(Json.Serialize(driver["normal_b_global"])));
                        var desired=RelativeMotion.Vector(target,RelativeMotion.InverseVector(initial,na));
                        double angle=Math.Acos(Math.Max(-1,Math.Min(1,GTDot(desired,nb))));
                        if(angle<=.01||angle>=Math.PI-.01)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","临时角度试验接近分支奇异位置，未创建约束。");
                        driver["value"]=angle;
                        moveObservation=new{backend="temporary_native_angle_constraint",target_angle_rad=angle,configuration_scope="owned_active_assembly",contact_or_force_tested=false};
                    }else {
                    var n=Json.Deserialize<double[]>(Json.Serialize(driver["normal_global"]));var delta=target.Skip(9).Take(3).Zip(initial.Skip(9).Take(3),(a,b)=>a-b).ToArray();
                    double step=GTDot(n,delta);
                    if(PoseValidation.RotationDistance(initial,target)>1e-9||Math.Abs(Math.Abs(step)-.0001)>1e-9||Math.Sqrt(delta.Select((v,i)=>Math.Pow(v-step*n[i],2)).Sum())>1e-9)
                        throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","临时直线驱动仅用于确认轴线的正反0.1mm试验。");
                    double signed=Convert.ToDouble(driver["signed_distance_m"])+step;
                    driver["value"]=Math.Abs(signed);driver["flip_dimension"]=signed>0;
                    }
                    touched=true;LastOperationRestoration="pending";var added=CreateConnectionMate(m,doc,driver);temporaryFeature=added.GetID();CheckMate(added,angularDriver?"temporary_angular_trial":"temporary_linear_trial");
                    if(!doc.EditRebuild3())throw new CadFault("CONNECTION_CREATE_FAILED","临时驱动约束试验求解重建失败。");accepted=true;
                }else {touched=true;LastOperationRestoration="pending";accepted=ConnectionMove(doc,moving,target,out moveObservation);}
                timing.Start("trial_component_poses_and_health");after=ConnectionPoses(doc);RequireMatesHealthy(doc);
                timing.Start("trial_parameters_count_and_fixed_states");
                if(parameters!=CompletionOriginalParameters(doc,originalIds)||EGAllMates(doc).Length!=originalIds.Length+(driver==null?0:1)||UserComponents(doc).Any(c=>c.IsFixed()!=fixedStates[GTComponentId(doc,c)]))throw new CadFault("CONNECTION_CREATE_FAILED","试验改变原配合参数、数量或固定状态。");
                if(before.Count!=after.Count||before.Any(v=>!after.ContainsKey(v.Key)||PoseValidation.TranslationDistance(v.Value,after[v.Key])>.005||PoseValidation.RotationDistance(v.Value,after[v.Key])>Math.PI/180))
                    throw new CadFault("CONNECTION_CREATE_FAILED","试验中任一组件位姿超出5mm/1度封顶。");
                timing.Start("pre_restore_observations_and_scope_exit");bool unchanged=before.Count==after.Count&&before.All(v=>after.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,after[v.Key]));
                Progress(activeJobId,"connection_verify_trial_restore",0,0,null);
                if(driver==null&&!checkpointPerTrial&&!unchanged){undoAttempted=true;undoAccepted=ConnectionMove(doc,moving,initial,out undoObservation);}
                restored=ConnectionPoses(doc);needsCheckpoint=checkpointPerTrial||driver!=null||before.Count!=restored.Count||!before.All(v=>restored.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,restored[v.Key]));
                RequireMatesHealthy(doc);
                if(parameters!=CompletionOriginalParameters(doc,originalIds)||UserComponents(doc).Any(c=>c.IsFixed()!=fixedStates[GTComponentId(doc,c)]))throw new CadFault("CONNECTION_CREATE_FAILED","试验反向恢复改变了配合参数或固定状态。");
            }
            if(needsCheckpoint) {
                timing.Start("checkpoint_restore_close_reopen_and_verify");
                RestoreUserCheckpoint(id,checkpointId);m=GetUserModel(id);
                timing.Start("post_restore_readonly_batch");
                using(var scope=new Scope(this,m.Path,null)) {
                    // Entire checkpoint restore finishes before this read-only
                    // batch starts. No retained objects cross the reopen.
                    var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,value=>Sw.CommandInProgress=value);
                    try {
                        restored=ConnectionPoses(scope.Doc);RequireMatesHealthy(scope.Doc);
                        if(parameters!=CompletionOriginalParameters(scope.Doc,originalIds)||EGAllMates(scope.Doc).Length!=originalIds.Length||UserComponents(scope.Doc).Any(c=>c.IsFixed()!=fixedStates[GTComponentId(scope.Doc,c)]))
                            throw new CadFault("CONNECTION_CREATE_FAILED","试验检查点恢复后配合参数、数量或固定状态不符。");
                    }finally {batch.Dispose();postRestoreBatch=batch.Export();}
                }
            }
            timing.Start("final_pose_and_source_validation");
            if(before.Count!=restored.Count||!before.All(v=>restored.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,restored[v.Key])))throw new CadFault("CONNECTION_CREATE_FAILED","有界试验未恢复全部姿态。");
            VerifyUserSources(m);LastOperationRestoration="restored";
            timing.Finish();var evidence=new{native_timings=timing.Export(),post_restore_native_batch=postRestoreBatch,model_id=id,component_id=componentId,probe_id=probeId,request_target_sha256=requestHash,target=target,before=before,after=after,restored=restored,
                fixed_states=fixedStates,native_trial_return=accepted,native_set_transform_return=driver==null?(bool?)accepted:null,
                native_undo_attempted=undoAttempted,native_undo_return=undoAttempted?(bool?)undoAccepted:null,checkpoint_fallback_used=driver==null&&!checkpointPerTrial&&needsCheckpoint,
                per_trial_checkpoint_required=checkpointPerTrial,solver_state_restoration=checkpointPerTrial?"saved_result_closed_reopened_and_verified":"pose_undo_or_verified_checkpoint",
                checkpoint_restore_used=needsCheckpoint,temporary_trial_feature_id=temporaryFeature,temporary_trial_feature_removed=driver==null?(bool?)null:true,
                temporary_trial_feature_status=driver==null?"not_used":"removed_and_checkpoint_verified",
                native_backend=driver!=null?(angularDriver?"temporary_native_angle_constraint_solve_and_result_checkpoint_restore":"temporary_native_distance_constraint_solve_and_result_checkpoint_restore"):"SetTransformAndSolve3_then_rebuild",
                native_move=moveObservation,native_undo=undoObservation,
                original_mates_parameters_unchanged=true,restoration_status="restored",native_motion_study_solved=false};AtomicJson(path,evidence);
            return new{probe_id=probeId,artifact_path=path,sha256=FileHash(path).Replace("-","").ToLowerInvariant(),restoration_status="restored",native_motion_study_solved=false};
        }catch(Exception error) {
            timing.Finish();
            if(touched){
                LastOperationRestoration="unknown";
                if(!(error is COMException)&&!(error is NativeCommandStateException)&&LastContextRestoration!="unknown") {
                    try {
                        RestoreUserCheckpoint(id,checkpointId);m=GetUserModel(id);
                        using(var scope=new Scope(this,m.Path,null)) {
                            restored=ConnectionPoses(scope.Doc);RequireMatesHealthy(scope.Doc);
                            if(parameters!=CompletionOriginalParameters(scope.Doc,originalIds)||EGAllMates(scope.Doc).Length!=originalIds.Length||UserComponents(scope.Doc).Any(c=>c.IsFixed()!=fixedStates[GTComponentId(scope.Doc,c)]))throw new Exception("TRIAL_RESTORE_PARAMETERS_CHANGED");
                        }
                        if(before.Count==restored.Count&&before.All(v=>restored.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,restored[v.Key])))LastOperationRestoration="restored";
                    }catch(Exception){LastOperationRestoration="unknown";}
                }
                AtomicJson(path,new{native_timings=timing.Export(),post_restore_native_batch=postRestoreBatch,probe_id=probeId,model_id=id,component_id=componentId,request_target_sha256=requestHash,target=target,before=before,after=after,restored=restored,
                    native_move=moveObservation,native_undo=undoObservation,failure=FailureEvidence(error),restoration_status=LastOperationRestoration,automatic_retry=false});
            }
            throw;
        }
    }
    // Development fixture only. Native deletion API documented by SOLIDWORKS:
    // https://help.solidworks.com/2021/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICoincidentMateFeatureData.html
    public object TestConnectionDeletion(string id,int featureId) {
        if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new CadFault("FAULT_TESTS_DISABLED","仅用于自建删除配合夹具。");
        var m=GetUserModel(id);
        using(var scope=new Scope(this,m.Path,null)) {
            var doc=scope.Doc;Fingerprint(doc,m.Path);var saved=PrepareConnectionModelScope(m,doc);
            var features=EGAllMates(doc).ToArray();var feature=features.SingleOrDefault(f=>f.GetID()==featureId);
            if(feature==null||EGSuppressed(feature))throw new CadFault("CONNECTION_REFERENCE_INVALID","夹具配合ID不存在或已压缩。");
            var ids=features.Select(f=>f.GetID()).OrderBy(v=>v).ToArray();var before=Transforms(doc);LastOperationRestoration="pending";
            doc.ClearSelection2(true);
            try {if(!feature.Select2(false,0)||!doc.Extension.DeleteSelection2(0))throw new CadFault("CONNECTION_CREATE_FAILED","受控删除配合未成功。");}
            finally {doc.ClearSelection2(true);}
            var remaining=EGAllMates(doc).Select(f=>f.GetID()).OrderBy(v=>v).ToArray();
            if(!remaining.SequenceEqual(ids.Where(v=>v!=featureId))||!doc.EditRebuild3())throw new CadFault("CONNECTION_CREATE_FAILED","删除影响了目标外配合或重建失败。");
            RequireMatesHealthy(doc);var after=Transforms(doc);
            if(before.Count!=after.Count||!before.All(v=>after.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,after[v.Key])))throw new CadFault("CONNECTION_CREATE_FAILED","受控删除改变初态，停止后续夹具操作。");
            SaveOwnedDocuments(m);m.Revision++;SaveUserModel(m);LastOperationRestoration="restored";
            return new{model_id=id,deleted_native_feature_id=featureId,original_mate_count=ids.Length,remaining_mate_count=remaining.Length,
                test_only=true,source_files_unchanged=UserSourcesUnchanged(m),preparation=saved};
        }
    }
    public object TestConnectionSuppression(string id,int featureId) {
        if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new CadFault("FAULT_TESTS_DISABLED","仅用于本机受控缺配合副本。");
        var m=GetUserModel(id);
        using(var scope=new Scope(this,m.Path,null)) {
            var doc=scope.Doc;Fingerprint(doc,m.Path);var saved=PrepareConnectionModelScope(m,doc);
            var feature=EGAllMates(doc).SingleOrDefault(f=>f.GetID()==featureId);
            if(feature==null||EGSuppressed(feature))throw new CadFault("CONNECTION_REFERENCE_INVALID","夹具配合ID不存在或已压缩。");
            var before=Transforms(doc);LastOperationRestoration="pending";
            if(!feature.SetSuppression2(0,1,null)||!EGSuppressed(feature)||!doc.EditRebuild3())throw new CadFault("CONNECTION_CREATE_FAILED","受控缺配合夹具未成功。");
            RequireMatesHealthy(doc);var after=Transforms(doc);
            if(before.Count!=after.Count||!before.All(v=>after.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,after[v.Key])))throw new CadFault("CONNECTION_CREATE_FAILED","受控压缩意外改变初态。");
            SaveOwnedDocuments(m);m.Revision++;SaveUserModel(m);LastOperationRestoration="restored";
            return new{model_id=id,suppressed_native_feature_id=featureId,test_only=true,source_files_unchanged=UserSourcesUnchanged(m),preparation=saved};
        }
    }
}
