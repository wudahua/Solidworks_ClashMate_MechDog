using System;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    object VerifyNewStudyMateState(IModelDoc2 doc,Dictionary<int,bool> expected,Dictionary<string,double[]> poses) {
        var features=EGAllMates(doc);var ids=features.Select(f=>f.GetID()).ToArray();
        if(ids.Length!=expected.Count||ids.Any(id=>!expected.ContainsKey(id)))throw new CadFault("STUDY_CONSTRAINT_STATE_UNVERIFIED","新建算例改变了原配合清单，未继续。");
        var changes=features.Where(f=>EGSuppressed(f)!=expected[f.GetID()]).Select(f=>new{native_feature_id=f.GetID(),expected_suppressed=expected[f.GetID()],observed_suppressed=EGSuppressed(f)}).ToArray();
        // Study-local mates cannot be transferred by changing their model
        // suppression flag. Refuse this scope change instead of a blind write.
        if(changes.Length>0)throw new CadFault("STUDY_CONSTRAINT_STATE_UNVERIFIED","新算例未保持创建前配合启用状态，未改写配合或开始求解。",new{changed_count=changes.Length,examples=changes.Take(10).ToArray(),automatic_transfer_attempted=false});
        RequireMatesHealthy(doc);var actual=Transforms(doc);
        if(poses.Count!=actual.Count||!poses.All(v=>actual.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,actual[v.Key])))
            throw new CadFault("STUDY_CONSTRAINT_STATE_UNVERIFIED","新算例激活改变初始姿态。",PoseDifference(poses,actual));
        return new{verified=true,mate_count=expected.Count,mask_source="observed_current_assembly_before_new_study",poses_unchanged=true,
            changed_mate_states=0,original_mates_deleted=false,original_mates_recreated=false,existing_study_intent_inferred=false};
    }
    object VerifyCompletionPose(IModelDoc2 doc,Dictionary<string,double[]> expected,IFeature added,Dictionary<string,object> action) {
        var actual=Transforms(doc);
        bool matches=expected.Count==actual.Count&&expected.All(v=>actual.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,actual[v.Key]));
        if(matches)return new{native_feature_id=added.GetID(),branch_adjusted=false,pose_unchanged=true};
        var first=PoseDifference(expected,actual);
        if((string)action["kind"]!="distance")throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","补约束改变确认姿态，未保留。",new{action=action,pose_difference=first});
        // Exactly one deterministic alternative of this newly created distance
        // mate, only after a returned healthy solve. Never recreate a failed
        // mate, touch old dimensions, or retry after an unknown native call.
        var mate=added.GetSpecificFeature2() as IMate2;
        if(mate==null||mate.Type!=5)throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","距离分支对象未核验。");
        bool original=mate.Flipped;mate.Flipped=!original;
        if(!doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","新距离配合分支校正后重建失败。");RequireMatesHealthy(doc);
        actual=Transforms(doc);matches=expected.Count==actual.Count&&expected.All(v=>actual.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,actual[v.Key]));
        if(!matches)throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","新距离配合的两个分支均未保持确认姿态。",new{action=action,first_pose_difference=first,second_pose_difference=PoseDifference(expected,actual),branch_adjustments=1});
        return new{native_feature_id=added.GetID(),branch_adjusted=true,original_flip=original,accepted_flip=mate.Flipped,
            initial_branch_pose_difference=first,pose_unchanged=true,branch_adjustments=1};
    }
    string CompletionOriginalParameters(IModelDoc2 doc,int[] ids) {
        var rows=Json.Deserialize<List<Dictionary<string,object>>>(ImportMateParameters(doc));
        return Json.Serialize(rows.Where(v=>ids.Contains(Convert.ToInt32(v["id"]))).OrderBy(v=>Convert.ToInt32(v["id"])).ToArray());
    }
    object ProbeCompletionSavedCheckpoint(string id,string checkpoint,Dictionary<string,double[]> expected,Dictionary<string,bool> fixedStates) {
        var model=GetUserModel(id);string mates,studies;
        using(var scope=new Scope(this,model.Path,null)) {
            mates=ImportMateParameters(scope.Doc);studies=Json.Serialize(StudyStates(scope.Doc));
            var observed=Transforms(scope.Doc);
            if(expected.Count!=observed.Count||!expected.All(v=>observed.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,observed[v.Key])))throw new CadFault("GEAR_PLAN_STALE","保存姿态已变化，未做补齐。");
        }
        // This explicit new-simulation mode restores the frozen *saved state*,
        // including old clocks. It never claims old frame-zero caches
        // were rebuilt. A full native reopen is verified before any additions.
        var restored=RestoreUserCheckpoint(id,checkpoint);model=GetUserModel(id);
        using(var scope=new Scope(this,model.Path,null)) {
            var actual=Transforms(scope.Doc);var flags=UserComponents(scope.Doc).ToDictionary(c=>c.Name2,c=>c.IsFixed());
            if(actual.Count!=expected.Count||!expected.All(v=>actual.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,actual[v.Key]))||
                fixedStates.Count!=flags.Count||!fixedStates.All(v=>flags.ContainsKey(v.Key)&&flags[v.Key]==v.Value)||
                mates!=ImportMateParameters(scope.Doc)||studies!=Json.Serialize(StudyStates(scope.Doc)))throw new CadFault("GEAR_PLAN_STALE","原保存态检查点回读不一致，未做补齐。");
            VerifyUserSources(model);
        }
        return new{strategy="whole_file_saved_state_native_restore_and_reopen",verified=true,checkpoint_id=checkpoint,restoration=restored,
            component_poses_fixed_flags_mate_parameters_and_study_states_verified=true,old_study_frame_zero_or_solver_cache_verified=false};
    }
    object PrepareCompletionSavedInitial(UserModel model,IModelDoc2 doc) {
        var before=Transforms(doc);var states=StudyStates(doc);var removed=new List<string>();string originalMates=ImportMateParameters(doc);
        var manager=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();
        foreach(var study in states.Where(v=>Math.Abs(v.time_s)>1e-8)) {
            if(!manager.DeleteMotionStudy(study.name))throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","试验副本非零历史算例未成功移除，不能清时钟冒充归零。");
            removed.Add(study.name);
        }
        string language=Sw.GetCurrentLanguage(),tab=language=="english"?"Model":language=="chinese-simplified"||language=="chinese"?"模型":null;
        if(tab==null||Names(manager).Contains(tab)||!manager.ActivateMotionStudy(tab)||StudyStates(doc).Any(v=>v.active))
            throw new CadFault("EXTERNAL_GEAR_SCOPE_UNSUPPORTED","未核验装配模型作用域，不能在旧算例中创建局部配合。",new{language=language,requested_model_tab=tab,model_scope_verified=false});
        if(originalMates!=ImportMateParameters(doc))throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","进入模型作用域改变了原配合参数，未继续补齐。");
        var after=Transforms(doc);
        if(before.Count!=after.Count||!before.All(v=>after.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,after[v.Key])))throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","建立新保存初态改变了组件姿态。");
        RequireMateInitialTime(doc,model);
        return new{strategy="new_simulation_from_saved_assembly_pose",removed_nonzero_studies=removed,poses_unchanged=true,existing_model_mates_preserved=true,
            model_context_verified=true,no_active_motion_study=true,model_tab_label=tab,language=language,scope="model_level_mate_creation_not_old_motion_study_local_mates",
            old_study_frame_zero_verified=false,original_files_and_preparation_checkpoint_preserved=true};
    }
    class CompletionPlaneTemplate {public IFeature Feature;public double[] Normal,Point;}
    object[] CompletionPlaneReferences(IModelDoc2 doc,IComponent2 component,Dictionary<string,List<CompletionPlaneTemplate>> templates=null) {
        var result=new List<object>();var part=component.GetModelDoc2() as IModelDoc2;
        if(part==null)return result.ToArray();
        templates=templates??new Dictionary<string,List<CompletionPlaneTemplate>>();string key=component.GetPathName()+"|"+component.ReferencedConfiguration;
        List<CompletionPlaneTemplate> local;
        if(!templates.TryGetValue(key,out local)) {
            local=new List<CompletionPlaneTemplate>();var feature=part.FirstFeature() as IFeature;int visited=0;
            while(feature!=null&&visited++<64&&local.Count<3) {
                if(feature.GetTypeName2()=="RefPlane") {
                    var plane=feature.GetSpecificFeature2() as IRefPlane;
                    if(plane!=null) {
                        var data=(double[])plane.Transform.ArrayData;
                        local.Add(new CompletionPlaneTemplate{Feature=feature,Normal=ApplyPose(data,new[]{0.0,0.0,1.0},false),Point=ApplyPose(data,new[]{0.0,0.0,0.0},true)});
                    }
                }
                feature=feature.GetNextFeature() as IFeature;
            }
            templates[key]=local;
        }
        var pose=(double[])component.GetTotalTransform(false).ArrayData;
        foreach(var template in local) {
                var corresponding=component.GetCorresponding(template.Feature) as IFeature;
                if(corresponding!=null) {
                    var normal=ApplyPose(pose,template.Normal,false);
                    var point=ApplyPose(pose,template.Point,true);
                    var reference=doc.Extension.GetPersistReference3(corresponding) as byte[];
                    if(reference!=null&&reference.Length>0)result.Add(new{component_id=GTComponentId(doc,component),
                        native_reference=Convert.ToBase64String(reference),reference_kind="datum_plane",feature=template.Feature.Name,
                        axis_global=normal,reference_point_global_m=point,source="part_RefPlane_transform_then_component_transform",
                        registration_scope="internal_completion_only_not_public_face_registration"});
                }
        }
        return result.ToArray();
    }
    object CompletionReference(IModelDoc2 doc,IComponent2 component,string reference) {
        int error;var feature=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out error) as IFeature;
        if(error!=0||feature==null||feature.GetTypeName2()!="RefPlane")throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","无法恢复补约束基准面。");
        // The complete plan is bound to the saved/live signature. Selection's
        // native component ownership is checked immediately before AddMate5;
        // rescanning every part plane here would not add ownership evidence.
        return feature;
    }
    IFeature CreateCompletionMate(IModelDoc2 doc,Dictionary<string,object> action) {
        string a=(string)action["component_a"],b=(string)action["component_b"];
        var m=GetUserModel((string)action["model_id"]);
        var ca=ResolveUserComponent(m,doc,a);var cb=ResolveUserComponent(m,doc,b);
        if((string)action["kind"]=="rigid_lock") {
            var links=BasicMateFeatures(doc).Where(f=>!EGSuppressed(f)).Where(f=>{
                var mate=(IMate2)f.GetSpecificFeature2();return Enumerable.Range(0,mate.GetMateEntityCount()).Any(i=>{
                    var c=mate.MateEntity(i).ReferenceComponent as IComponent2;return c!=null&&c.Name2==ca.Name2;});
            }).ToArray();
            if(links.Length>0||ca.IsPatternInstance())throw new CadFault("EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW","仅完全无配合的非阵列实例允许单项刚性补齐，未压缩旧配合。");
            var data=(ILockMateFeatureData)((IAssemblyDoc)doc).CreateMateData(16);
            data.EntitiesToMate=new DispatchWrapper[]{new DispatchWrapper(ca),new DispatchWrapper(cb)};
            return ((IAssemblyDoc)doc).CreateMate(data) as IFeature;
        }
        object ra=CompletionReference(doc,ca,(string)action["reference_a"]),rb=CompletionReference(doc,cb,(string)action["reference_b"]);
        if(ra==null||rb==null)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","原生基准面对象为空。");
        string kind=(string)action["kind"];int type=kind=="parallel"?3:kind=="perpendicular"?2:kind=="angle"?6:kind=="distance"?5:-1;
        if(type<0)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","补约束类型不支持。");
        var before=new HashSet<int>(EGAllMates(doc).Select(f=>f.GetID()));doc.ClearSelection2(true);
        try {
            if(!((IFeature)ra).Select2(false,1)||!((IFeature)rb).Select2(true,1))throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","原生组件基准面选择失败，未添加配合。");
            var selection=(ISelectionMgr)doc.SelectionManager;
            if(selection.GetSelectedObjectCount2(1)!=2)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","基准面选择数量不符。");
            var selectedA=selection.GetSelectedObjectsComponent4(1,1) as IComponent2;
            var selectedB=selection.GetSelectedObjectsComponent4(2,1) as IComponent2;
            if(selectedA==null||selectedB==null||GTComponentId(doc,selectedA)!=a||GTComponentId(doc,selectedB)!=b)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","基准面选择丢失组件上下文，未添加配合。");
            double distance=type==5?Convert.ToDouble(action["value"]):0,angle=type==6?Convert.ToDouble(action["value"]):0;int error;
            var added=((IAssemblyDoc)doc).AddMate5(type,2,false,distance,distance,distance,1,1,angle,angle,angle,false,false,0,out error);
            if(added==null||error!=1)throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","原生补约束未成功。",new{native_error=error,native_object_returned=added!=null,kind=kind});
            var features=EGAllMates(doc).Where(f=>!before.Contains(f.GetID())).ToArray();
            if(features.Length!=1)throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","未确认恰好新增一项约束。");
            return features[0];
        }finally{doc.ClearSelection2(true);}
    }
}
