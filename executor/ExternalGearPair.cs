using System;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    class ExternalGearPlan {
        public string Id,ModelId,Signature;public int Revision;public bool Consumed,Reverse;
        public Dictionary<string,string> Roles,References;
        public Dictionary<string,string[]> Groups;public string[] Stationary;
        public Dictionary<string,double[]> Poses;public Dictionary<string,bool> Fixed;
        public bool CompleteConstraints,SavedInitial;public List<Dictionary<string,object>> Completion;
        public int[] OriginalMateIds;public string OriginalMateParameters;
        public List<ExternalGearAction> Actions=new List<ExternalGearAction>();
        public double Numerator,Denominator;public double[] Axis;
        public int ExistingCount,ExistingGearId=-1;
        public object Description;
    }
    class ExternalGearAction {
        public string Kind,A,B,RefA,RefB,ExistingName;public double Distance;public int ExistingFeatureId=-1;
        public object Describe(){return new{kind=Kind,component_a=A,component_b=B,existing_native_feature_id=ExistingFeatureId<0?(int?)null:ExistingFeatureId,existing_native_feature_name=ExistingName,distance_mm=Kind=="add_axial_distance"?Distance*1000:(double?)null};}
    }
    readonly Dictionary<string,ExternalGearPlan> externalGearPlans=new Dictionary<string,ExternalGearPlan>();
    static bool EGSuppressed(IFeature feature) {
        var states=feature.IsSuppressed2(1,null) as Array;
        if(states==null||states.Length!=1)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","配合配置压缩状态无法核对。");
        return Convert.ToBoolean(states.GetValue(0));
    }
    static IFeature[] EGAllMates(IModelDoc2 doc) {
        var rows=new List<IFeature>();var f=doc.FirstFeature() as IFeature;
        while(f!=null){if(f.GetTypeName2()=="MateGroup"){var child=f.GetFirstSubFeature() as IFeature;while(child!=null){if(child.GetTypeName2().StartsWith("Mate")||child.GetSpecificFeature2() is IMate2)rows.Add(child);child=child.GetNextSubFeature() as IFeature;}}f=f.GetNextFeature() as IFeature;}
        return rows.ToArray();
    }
    static Dictionary<string,object> EGDict(object value){return (Dictionary<string,object>)value;}
    static string[] EGStrings(object value){return ((IEnumerable)value).Cast<object>().Select(Convert.ToString).ToArray();}
    IFace2 EGFace(IModelDoc2 doc,string reference,IComponent2 component) {
        var face=FaceReference(doc,reference);var owner=((IEntity)face).GetComponent() as IComponent2;
        if(owner==null||owner.Name2!=component.Name2||!((ISurface)face.GetSurface()).IsCylinder())throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","推荐轴面不属于当前角色。",new{instance=component.Name2});return face;
    }
    IFeature[] EGPairMates(IModelDoc2 doc,IComponent2 a,IComponent2 b) {
        return BasicMateFeatures(doc).Where(f=>!EGSuppressed(f)).Where(f=>{var m=(IMate2)f.GetSpecificFeature2();var names=Enumerable.Range(0,m.GetMateEntityCount()).Select(i=>m.MateEntity(i).ReferenceComponent as IComponent2).Where(c=>c!=null).Select(c=>c.Name2).Distinct().ToArray();return names.Length==2&&names.Contains(a.Name2)&&names.Contains(b.Name2);}).ToArray();
    }
    bool EGAxialMate(IModelDoc2 doc,IFeature feature,double[] axis) {
        var mate=(IMate2)feature.GetSpecificFeature2();if(mate.Type!=0&&mate.Type!=5)return false;
        return mate.GetMateEntityCount()==2&&Enumerable.Range(0,2).All(i=>{
            var e=mate.MateEntity(i);var f=e.Reference as IFace2;var c=e.ReferenceComponent as IComponent2;
            if(f==null||c==null||!((ISurface)f.GetSurface()).IsPlane())return false;
            var shape=MateGeometry(doc,f,c);return Math.Abs(GTDot((double[])shape["axis_global"],axis))>1-1e-8;
        });
    }
    void EGAddAxial(IModelDoc2 doc,ExternalGearPlan plan,IComponent2 a,IComponent2 b,string idA,string idB,double[] axis) {
        var fa=GTPlane(doc,a,axis);var fb=GTPlane(doc,b,axis);
        double distance=Math.Abs(GTDot(GTSub((double[])MateGeometry(doc,fa,a)["reference_point_global_m"],(double[])MateGeometry(doc,fb,b)["reference_point_global_m"]),axis));
        plan.Actions.Add(new ExternalGearAction{Kind="add_axial_distance",A=idA,B=idB,RefA=GTReference(doc,fa),RefB=GTReference(doc,fb),Distance=distance});
    }
    void EGPlanConnection(IModelDoc2 doc,ExternalGearPlan plan,IComponent2 a,IComponent2 b,string idA,string idB,double[] axis,IFace2 fa,IFace2 fb,bool rigid) {
        if(a.Name2==b.Name2)return;
        var mates=EGPairMates(doc,a,b);
        if(mates.Any(f=>((IMate2)f.GetSpecificFeature2()).Type==16)){
            if(!rigid)throw new CadFault("EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW","轴与固定支承已有刚性锁定，首版不自动删除该配合。");
            plan.Actions.Add(new ExternalGearAction{Kind="reuse_rigid",A=idA,B=idB});return;
        }
        var concentric=mates.Where(f=>((IMate2)f.GetSpecificFeature2()).Type==1).ToArray();
        var axial=mates.Where(f=>EGAxialMate(doc,f,axis)).ToArray();
        if(concentric.Length>1||axial.Length>1||mates.Length!=concentric.Length+axial.Length)
            throw new CadFault("EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW","这对零件已有不在首版可复用范围的配合，未添加冗余约束。",new{a=a.Name2,b=b.Name2,mates=mates.Select(f=>new{name=f.Name,type=((IMate2)f.GetSpecificFeature2()).Type}).ToArray()});
        if(rigid&&mates.Length==0){plan.Actions.Add(new ExternalGearAction{Kind="add_rigid_lock",A=idA,B=idB});return;}
        if(concentric.Length==1) {
            var data=concentric[0].GetDefinition() as IConcentricMateFeatureData;
            if(data==null)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","既有同轴数据无法读取。");
            var native=(IMate2)concentric[0].GetSpecificFeature2();var anchor=(double[])MateGeometry(doc,fa,a)["reference_point_global_m"];
            for(int i=0;i<native.GetMateEntityCount();i++){
                var entity=native.MateEntity(i);var owner=entity.ReferenceComponent as IComponent2;
                var face=entity.Reference as IFace2;var edge=entity.Reference as IEdge;Dictionary<string,object> shape=null;
                if(owner!=null&&face!=null&&((ISurface)face.GetSurface()).IsCylinder())shape=MateGeometry(doc,face,owner);
                else if(owner!=null&&edge!=null&&((ICurve)edge.GetCurve()).IsCircle())shape=CircularMateGeometry(doc,edge,owner);
                if(shape==null||Math.Abs(GTDot((double[])shape["axis_global"],axis))<1-1e-8||GTGap((double[])shape["reference_point_global_m"],anchor,axis)>1e-5)throw new CadFault("EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW","既有同轴引用不在推荐材料轴线上。");
            }
            if(!rigid&&data.LockRotation)plan.Actions.Add(new ExternalGearAction{Kind="unlock_existing_support_rotation",A=idA,B=idB,ExistingFeatureId=concentric[0].GetID(),ExistingName=concentric[0].Name});
            if(!rigid)plan.Actions.Add(new ExternalGearAction{Kind="reuse_concentric",A=idA,B=idB,ExistingFeatureId=concentric[0].GetID(),ExistingName=concentric[0].Name});
        } else if(!rigid) {
            plan.Actions.Add(new ExternalGearAction{Kind="add_concentric",A=idA,B=idB,RefA=GTReference(doc,fa),RefB=GTReference(doc,fb)});
        }
        if(rigid&&mates.Length>0) {
            // A LockRotation property readback alone did not rigidly couple
            // the rotor in SW34 Motion Analysis. Explicitly retain/suppress
            // these verified pair mates and replace them with one rigid mate.
            // This conversion is listed before confirmation and checkpointed.
            plan.Actions.RemoveAll(v=>v.A==idA&&v.B==idB);
            foreach(var feature in mates)plan.Actions.Add(new ExternalGearAction{Kind="suppress_existing_for_rigid",A=idA,B=idB,ExistingFeatureId=feature.GetID(),ExistingName=feature.Name});
            plan.Actions.Add(new ExternalGearAction{Kind="add_rigid_lock",A=idA,B=idB});return;
        }
        if(axial.Length==0)EGAddAxial(doc,plan,a,b,idA,idB,axis);
        else plan.Actions.Add(new ExternalGearAction{Kind="reuse_axial",A=idA,B=idB,ExistingFeatureId=axial[0].GetID(),ExistingName=axial[0].Name});
    }
    public object PreviewExternalGearPair(string id,string recommendationJson,double numerator,double denominator) {
        if(Sw.RevisionNumber()!="34.0.0")throw new CadFault("EXTERNAL_GEAR_SCOPE_UNSUPPORTED","原生齿轮方向适配目前限SW2026 revision34.0.0。");
        if(double.IsNaN(numerator)||double.IsInfinity(numerator)||double.IsNaN(denominator)||double.IsInfinity(denominator)||numerator<=0||denominator<=0||numerator>1000||denominator>1000)
            throw new CadFault("EXTERNAL_GEAR_RATIO_INVALID","齿轮比例必须为有限正数，分子分母各不超过1000。");
        var rec=Json.Deserialize<Dictionary<string,object>>(recommendationJson);var m=GetUserModel(id);
        using(var scope=new Scope(this,m.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
            var doc=scope.Doc;InspectUserCore(m,doc);bool complete=rec.ContainsKey("constraint_completion");
            var nonzero=StudyStates(doc).Where(v=>Math.Abs(v.time_s)>1e-8).ToArray();
            // Planning is read-only. A nonzero historical clock does not prevent
            // a separately confirmed new simulation from the saved assembly pose.
            // Its old frame-zero/cache is neither reconstructed nor certified.
            bool savedInitial=complete||nonzero.Length>0;RequireMatesHealthy(doc);
            if((string)rec["model_id"]!=id||(string)rec["reference_state_signature"]!=MateSignature(m,doc))throw new CadFault("GEAR_PLAN_STALE","推荐已过期，重新只读推荐后再确认。");
            var roles=EGDict(rec["roles"]).ToDictionary(v=>v.Key,v=>Convert.ToString(v.Value));
            if(!roles.Keys.OrderBy(v=>v).SequenceEqual(new[]{"input_shaft","output_shaft","input_gear","output_gear","body"}.OrderBy(v=>v)))throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","角色集合无效。");
            var groups=EGDict(rec["groups"]).ToDictionary(v=>v.Key,v=>EGStrings(v.Value));
            if(groups.Count!=2||!groups.ContainsKey("input")||!groups.ContainsKey("output")||groups.Values.Any(v=>v.Length<1||v.Length>6||v.Distinct().Count()!=v.Length)||groups["input"].Intersect(groups["output"]).Any()||groups.Values.Any(v=>v.Contains(roles["body"])))throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","两个轴系分组不能相交，且不能包含固定参考。");
            foreach(string side in new[]{"input","output"})if(!groups[side].Contains(roles[side+"_shaft"])||!groups[side].Contains(roles[side+"_gear"]))throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","轴和齿轮须在对应轴系中。");
            var stationary=rec.ContainsKey("stationary_components")?EGStrings(rec["stationary_components"]):new string[0];
            if(stationary.Length>128||stationary.Distinct().Count()!=stationary.Length||stationary.Intersect(groups.Values.SelectMany(v=>v)).Any())throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","静止侧与转子重叠或声明重复。");
            var allIds=roles.Values.Concat(groups.Values.SelectMany(v=>v)).Concat(stationary).Distinct().ToArray();var components=allIds.ToDictionary(v=>v,v=>ResolveUserComponent(m,doc,v));
            var moving=groups.Values.SelectMany(v=>v).Distinct().ToArray();var cs=UserComponents(doc);
            if(cs.Length>128||cs.Any(c=>c.IsSuppressed()||c.IsSpeedPak||c.GetModelDoc2()==null||!m.Files.Contains(c.GetPathName(),StringComparer.OrdinalIgnoreCase)))throw new CadFault("EXTERNAL_GEAR_SCOPE_UNSUPPORTED","要求已解析、隔离的顶层零件。");
            if(!components[roles["body"]].IsFixed()&&!stationary.Contains(roles["body"])||cs.Any(c=>!moving.Select(v=>components[v].Name2).Contains(c.Name2)&&!c.IsFixed()&&!stationary.Select(v=>components[v].Name2).Contains(c.Name2)))throw new CadFault("EXTERNAL_GEAR_SCOPE_UNSUPPORTED","轴系外未固定件须有明确静止侧声明，未自动固定未归属零件。");
            var p=new ExternalGearPlan{Id=Guid.NewGuid().ToString("N"),ModelId=id,Revision=m.Revision,Signature=MateSignature(m,doc),Roles=roles,Groups=groups,Stationary=stationary,Numerator=numerator,Denominator=denominator,
                References=new Dictionary<string,string>(),Poses=Transforms(doc),Fixed=cs.ToDictionary(c=>c.Name2,c=>c.IsFixed()),ExistingCount=EGAllMates(doc).Length};
            p.CompleteConstraints=complete;p.SavedInitial=savedInitial;
            if(complete) {
                p.OriginalMateIds=EGAllMates(doc).Select(f=>f.GetID()).ToArray();p.OriginalMateParameters=CompletionOriginalParameters(doc,p.OriginalMateIds);
                var completion=EGDict(rec["constraint_completion"]);p.Completion=Json.Deserialize<List<Dictionary<string,object>>>(Json.Serialize(completion["actions"]));
                if(p.Completion.Count>256||EGStrings(completion["uncompleted_components"]).Length>0||moving.Concat(stationary).Distinct().Count()!=cs.Length)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","补约束范围不完整或超过预算。");
                foreach(var action in p.Completion) {
                    string a=(string)action["component_a"],b=(string)action["component_b"];
                    if(a==b||!allIds.Contains(a)||!allIds.Contains(b)||!(stationary.Contains(a)&&stationary.Contains(b)||groups.Values.Any(v=>v.Contains(a)&&v.Contains(b))))throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","补约束不能跨机械分组锁定运动。");
                    action["model_id"]=id;
                    p.Actions.Add(new ExternalGearAction{Kind="add_completion_"+(string)action["kind"],A=a,B=b});
                }
            }else foreach(string cid in stationary)if(!components[cid].IsFixed())p.Actions.Add(new ExternalGearAction{Kind="fix_declared_stationary",A=cid});
            var description=new List<object>();var gearAxes=new List<double[]>();
            foreach(string side in new[]{"input","output"}) {
                var shaft=components[roles[side+"_shaft"]];var gear=components[roles[side+"_gear"]];
                var axisRec=EGDict(EGDict(rec["shaft_axes"])[side]);var shaftFace=EGFace(doc,(string)axisRec["native_reference"],shaft);
                var shape=MateGeometry(doc,shaftFace,shaft);var axis=(double[])shape["axis_global"];var point=(double[])shape["reference_point_global_m"];
                if(p.Axis==null)p.Axis=axis;else if(Math.Abs(GTDot(p.Axis,axis))<1-1e-8)throw new CadFault("EXTERNAL_GEAR_SCOPE_UNSUPPORTED","两根轴不平行。");
                var supportRec=EGDict(EGDict(rec["supports"])[side]);string supportId=(string)supportRec["component_id"];
                var support=ResolveUserComponent(m,doc,supportId);if(!support.IsFixed()&&!stationary.Contains(supportId)||moving.Contains(supportId))throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","支承参考必须固定且不属于运动组。");components[supportId]=support;
                var supportFace=EGFace(doc,(string)EGDict(supportRec["axis"])["native_reference"],support);var supportShape=MateGeometry(doc,supportFace,support);
                double gap=GTGap((double[])supportShape["reference_point_global_m"],point,p.Axis);
                if(gap>1e-5||Math.Abs(GTDot((double[])supportShape["axis_global"],p.Axis))<1-1e-8)throw new CadFault("GEAR_SUPPORT_ALIGNMENT_EXCEEDED","轴与推荐支承轴线不一致，未重定位。",new{side=side,offset_mm=gap*1000});
                var gearFace=GTCylinder(doc,gear,point,p.Axis);var gearShape=MateGeometry(doc,gearFace,gear);
                if(GTGap((double[])gearShape["reference_point_global_m"],point,p.Axis)>1e-5)throw new CadFault("EXTERNAL_GEAR_REFERENCE_INVALID","齿轮与轴不同轴。");
                gearAxes.Add((double[])gearShape["axis_global"]);p.References[side+"_axis"]=GTReference(doc,shaftFace);p.References[side+"_support"]=GTReference(doc,supportFace);p.References[side+"_gear"]=GTReference(doc,gearFace);p.Roles[side+"_support"]=supportId;
                foreach(string memberId in groups[side].Where(v=>!complete&&v!=roles[side+"_shaft"])) {
                    var member=ResolveUserComponent(m,doc,memberId);components[memberId]=member;
                    // Rigid conversion validates the actual existing mate references
                    // against the shaft axis inside EGPlanConnection. Its fb argument
                    // is used only when adding a NON-rigid support concentric mate.
                    // A rectangular key needs no separate cylindrical face, and we
                    // must not substitute a gear face as if it belonged to the key.
                    EGPlanConnection(doc,p,shaft,member,roles[side+"_shaft"],memberId,p.Axis,shaftFace,null,true);
                }
                if(!complete)EGPlanConnection(doc,p,shaft,support,roles[side+"_shaft"],supportId,p.Axis,shaftFace,supportFace,false);
                description.Add(new{side=side,shaft=shaft.Name2,gear=gear.Name2,support=support.Name2,axis=shape,support_axis=supportShape,radial_offset_mm=gap*1000});
            }
            if(GTGap((double[])MateGeometry(doc,FaceReference(doc,p.References["input_axis"]),components[roles["input_shaft"]])["reference_point_global_m"],(double[])MateGeometry(doc,FaceReference(doc,p.References["output_axis"]),components[roles["output_shaft"]])["reference_point_global_m"],p.Axis)<1e-4)throw new CadFault("EXTERNAL_GEAR_SCOPE_UNSUPPORTED","两轴重合，不属于普通外齿轮对。");
            var gearMates=BasicMateFeatures(doc).Where(f=>!EGSuppressed(f)&&((IMate2)f.GetSpecificFeature2()).Type==10).ToArray();
            foreach(var feature in gearMates) {
                var mate=(IMate2)feature.GetSpecificFeature2();var cids=Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>mate.MateEntity(i).ReferenceComponent as IComponent2).Select(c=>c==null?null:GTComponentId(doc,c)).ToArray();
                if(cids.Length!=2||!cids.Any(c=>groups["input"].Contains(c))||!cids.Any(c=>groups["output"].Contains(c)))continue;
                if(p.ExistingGearId!=-1)throw new CadFault("EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW","两轴已有多个齿轮配合。");
                var data=feature.GetDefinition() as IGearMateFeatureData;double value=data==null?double.NaN:data.GearRatioDenominator/data.GearRatioNumerator;
                if(groups["output"].Contains(cids[0]))value=1/value;
                if(double.IsNaN(value)||double.IsInfinity(value)||Math.Abs(value-numerator/denominator)>1e-8)throw new CadFault("EXTERNAL_GEAR_EXISTING_MATES_REQUIRE_REVIEW","既有齿轮比例与建议不一致，不自动覆盖。",new{observed=value,requested=numerator/denominator});
                p.ExistingGearId=feature.GetID();
            }
            // A cylinder's parameter-axis sign is not a directed mechanical
            // rotation axis. SW34 external-pair creation uses false for the
            // opposite world rotation in the calibrated Y and opposed-Z cases.
            // Every actual pair still requires the signed full-pose audit.
            p.Reverse=false;
            int added=p.Actions.Count(a=>a.Kind.StartsWith("add_"))+(p.ExistingGearId<0?1:0);
            p.Description=new{plan_id=p.Id,model_id=id,scope="two_parallel_axis_external_gear_pair_prescribed_ratio_not_contact",roles=p.Roles,groups=p.Groups,
                constraint_completion=complete,completion_action_count=p.Completion==null?0:p.Completion.Count,
                initial_state_strategy=savedInitial?"new_motion_from_saved_pose_remove_nonzero_copy_studies_activate_verified_model_scope":"existing_zero_study_requirement",
                initial_state_preparation=new{required=savedInitial,starting_pose="saved_imported_assembly_pose",nonzero_copy_studies_to_remove=nonzero,
                    explicit_plan_confirmation_required=true,old_study_frame_zero_verified=false,historical_solver_cache_recalculated=false,
                    source_and_import_checkpoint_preserved=true,public_checkpoint_or_reset_tools_required=false},
                supports=description,actions=p.Actions.Select(a=>a.Describe()).ToArray(),existing_mate_count=p.ExistingCount,expected_added_mates=added,expected_mate_count=p.ExistingCount+added,
                existing_gear_feature_id=p.ExistingGearId<0?(int?)null:p.ExistingGearId,
                modified_existing_mate_ids=p.Actions.Where(a=>a.Kind=="suppress_existing_for_rigid"||a.Kind=="unlock_existing_support_rotation").Select(a=>a.ExistingFeatureId).ToArray(),
                retained_suppressed_mate_ids=p.Actions.Where(a=>a.Kind=="suppress_existing_for_rigid").Select(a=>a.ExistingFeatureId).ToArray(),
                rigid_conversion=complete?"no_original_mate_suppression_or_replacement":"verified_rotor_pair_only_retain_and_suppress_originals_add_one_rigid_no_deletion",
                gear_ratio=new{numerator=numerator,denominator=denominator,expected_output_over_input=-numerator/denominator,creation_reverse_argument=p.Reverse,
                    direction_adapter="SW34_external_pair_world_signed_pose_required_not_cylinder_parameter_axis_sign",gear_reference_parameter_axes=gearAxes.ToArray()},
                maximum_setup_translation_mm=.01,maximum_setup_rotation_rad=1e-6,moving_components=moving,requires_explicit_confirmation=true,write_dispatched=false,contact_or_tooth_geometry_validated=false};
            externalGearPlans.Add(p.Id,p);return p.Description;
        }
    }
    IFeature EGFeature(IModelDoc2 doc,int id){var matches=EGAllMates(doc).Where(f=>f.GetID()==id).ToArray();if(matches.Length!=1)throw new CadFault("GEAR_PLAN_STALE","既有配合身份变化。");return matches[0];}
    void EGLockConcentric(IModelDoc2 doc,IFeature feature,bool locked=true) {
        var data=feature.GetDefinition() as IConcentricMateFeatureData;if(data==null)throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","无法核对既有同轴定义。");
        data.LockRotation=locked;if(!feature.ModifyDefinition(data,doc,null))throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","既有同轴旋转状态修改失败。");
        var read=feature.GetDefinition() as IConcentricMateFeatureData;if(read==null||read.LockRotation!=locked)throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","同轴旋转状态未回读确认。");
    }
    public object ApplyExternalGearPair(string planId,bool confirmed,bool testFault=false) {
        ExternalGearPlan p;if(!externalGearPlans.TryGetValue(planId??"",out p))throw new CadFault("GEAR_PLAN_STALE","普通两轴方案不存在。");
        if(!confirmed)throw new CadFault("MATE_CONFIRMATION_REQUIRED","须确认推荐角色、比例和副本配合修改。");
        if(p.Consumed)throw new CadFault("GEAR_PLAN_CONSUMED","方案已提交，不重放。");
        if(testFault&&System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new CadFault("FAULT_TESTS_DISABLED","受控故障仅用于本机开发验收。");
        var m=GetUserModel(p.ModelId);using(var s=new Scope(this,m.Path,null))if(m.Revision!=p.Revision||MateSignature(m,s.Doc)!=p.Signature)throw new CadFault("GEAR_PLAN_STALE","初态改变，重新推荐并确认。");
        p.Consumed=true;bool mutating=false;string checkpoint=null;object completionCheckpoint=null,savedInitial=null;var completionEvidence=new List<object>();
        try {
            var cp=EGDict(Json.DeserializeObject(Json.Serialize(CreateUserCheckpoint(m.Id))));checkpoint=(string)cp["checkpoint_id"];
            if(p.SavedInitial) {
                completionCheckpoint=ProbeCompletionSavedCheckpoint(m.Id,checkpoint,p.Poses,p.Fixed);m=GetUserModel(m.Id);
                using(var checkedScope=new Scope(this,m.Path,null)){p.Revision=m.Revision;p.Signature=MateSignature(m,checkedScope.Doc);}
            }else CheckpointProbeWithTiming(m,p.Id,checkpoint);
            using(var scope=new Scope(this,m.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
                var doc=scope.Doc;var ad=(IAssemblyDoc)doc;if(!p.SavedInitial)RequireMateInitialTime(doc,m);RequireMatesHealthy(doc);
                if(MateSignature(m,doc)!=p.Signature)throw new CadFault("GEAR_PLAN_STALE","检查点探测后初态变化，未修改。");
                var all=p.Roles.Values.Concat(p.Groups.Values.SelectMany(v=>v)).Distinct().ToDictionary(v=>v,v=>ResolveUserComponent(m,doc,v));
                var moving=p.Groups.Values.SelectMany(v=>v).Distinct().ToArray();mutating=true;LastOperationRestoration="pending";
                if(p.SavedInitial)savedInitial=PrepareCompletionSavedInitial(m,doc);
                if(!p.CompleteConstraints)foreach(string cid in p.Stationary){var c=ResolveUserComponent(m,doc,cid);if(!c.IsFixed()){doc.ClearSelection2(true);if(!c.Select4(false,null,false))throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","静止侧选择失败。");ad.FixComponent();doc.ClearSelection2(true);}if(!c.IsFixed())throw new CadFault("GEAR_FIXED_STATE_UNVERIFIED","已确认的静止侧固定未生效。");}
                foreach(string cid in moving){var c=all[cid];if(c.IsFixed()){doc.ClearSelection2(true);if(!c.Select4(false,null,false))throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","解除固定选择失败。");ad.UnfixComponent();doc.ClearSelection2(true);}if(c.IsFixed())throw new CadFault("GEAR_FIXED_STATE_UNVERIFIED","解除指定固定未生效。");}
                if(testFault)throw new CadFault("CONTROLLED_GEAR_FAULT","验收：普通两轴解除固定后受控回退。");
                if(p.CompleteConstraints) {
                    var beforeIds=new HashSet<int>(EGAllMates(doc).Select(f=>f.GetID()));int index=0;
                    foreach(var action in p.Completion) {
                        Progress(activeJobId,"assembly_constraint_completion",index,p.Completion.Count,null);
                        var added=CreateCompletionMate(doc,action);CheckMate(added,"minimum_constraint_supplement");
                        if(!doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","最小补约束后重建失败。");RequireMatesHealthy(doc);
                        completionEvidence.Add(VerifyCompletionPose(doc,p.Poses,added,action));
                        index++;
                    }
                    if(!beforeIds.IsSubsetOf(new HashSet<int>(EGAllMates(doc).Select(f=>f.GetID()))))throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","补齐期间旧配合被移除。");
                }
                foreach(var action in p.Actions) {
                    if(action.Kind.StartsWith("add_completion_"))continue;
                    if(action.Kind.StartsWith("reuse_")||action.Kind=="fix_declared_stationary")continue;
                    if(action.Kind=="suppress_existing_for_rigid") {
                        var feature=EGFeature(doc,action.ExistingFeatureId);
                        if(!feature.SetSuppression2(0,1,null)||!EGSuppressed(feature))throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","已确认的轴系既有配合压缩未生效。",action.Describe());
                        continue;
                    }
                    if(action.Kind=="add_rigid_lock"){LockPair(doc,all[action.A],all[action.B]);continue;}
                    if(action.Kind=="unlock_existing_support_rotation"){EGLockConcentric(doc,EGFeature(doc,action.ExistingFeatureId),false);continue;}
                    int error;
                    SelectMateFaces(doc,FaceReference(doc,action.RefA),FaceReference(doc,action.RefB));
                    bool axial=action.Kind=="add_axial_distance";var mate=ad.AddMate5(axial?5:1,2,false,action.Distance,action.Distance,action.Distance,1,1,0,0,0,false,false,0,out error);doc.ClearSelection2(true);
                    if(mate==null||error!=1)throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","新增配合未成功。",new{action=action.Describe(),native_error=error});
                    if(!doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","配合后重建失败。");
                    if(axial) {
                        // Only this shaft's axial branch decides Flip. A small
                        // already accepted change on another rotor must not flip
                        // a correct distance mate into the opposite branch.
                        var shaft=all[action.A];var initial=p.Poses[shaft.Name2];var current=(double[])shaft.GetTotalTransform(false).ArrayData;
                        double delta=Math.Abs(GTDot(GTSub(current.Skip(9).Take(3).ToArray(),initial.Skip(9).Take(3).ToArray()),p.Axis));
                        if(delta>1e-7) {
                            mate.Flipped=!mate.Flipped;if(!doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","轴向分支调整重建失败。");
                            current=(double[])shaft.GetTotalTransform(false).ArrayData;
                            delta=Math.Abs(GTDot(GTSub(current.Skip(9).Take(3).ToArray(),initial.Skip(9).Take(3).ToArray()),p.Axis));
                        }
                        if(delta>1e-7)throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","轴向分支未保留确认初态。",new{instance=shaft.Name2,axial_translation_m=delta});
                    }
                }
                IFeature gear;
                if(p.ExistingGearId<0) {
                    var data=(IGearMateFeatureData)ad.CreateMateData(10);data.EntitiesToMate=new DispatchWrapper[]{new DispatchWrapper(FaceReference(doc,p.References["input_gear"])),new DispatchWrapper(FaceReference(doc,p.References["output_gear"]))};
                    data.GearRatioNumerator=p.Numerator;data.GearRatioDenominator=p.Denominator;data.Reverse=p.Reverse;
                    gear=ad.CreateMate(data) as IFeature;CheckMate(gear,"confirmed_external_pair_ratio");
                }else gear=EGFeature(doc,p.ExistingGearId);
                if(!doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","两轴传动重建失败。");RequireMatesHealthy(doc);
                var actual=gear.GetDefinition() as IGearMateFeatureData;
                double ratio=actual==null?double.NaN:actual.GearRatioDenominator/actual.GearRatioNumerator;
                // SW34 GetDefinition's length getters are reciprocal to the
                // CreateMate inputs. Retain raw getters and native entity order;
                // this adapter is separately checked by signed solved poses.
                var nativeMate=(IMate2)gear.GetSpecificFeature2();
                var nativeIds=Enumerable.Range(0,nativeMate.GetMateEntityCount()).Select(i=>nativeMate.MateEntity(i).ReferenceComponent as IComponent2).Select(c=>c==null?null:GTComponentId(doc,c)).ToArray();
                if(nativeIds.Length!=2||!(p.Groups["input"].Contains(nativeIds[0])&&p.Groups["output"].Contains(nativeIds[1])||p.Groups["output"].Contains(nativeIds[0])&&p.Groups["input"].Contains(nativeIds[1])))throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","原生齿轮引用不再绑定两侧轴系。");
                if(p.Groups["output"].Contains(nativeIds[0]))ratio=1/ratio;
                int count=p.ExistingCount+p.Actions.Count(a=>a.Kind.StartsWith("add_"))+(p.ExistingGearId<0?1:0);
                var allMates=EGAllMates(doc);var suppressed=p.Actions.Where(a=>a.Kind=="suppress_existing_for_rigid").Select(a=>a.ExistingFeatureId).ToArray();
                if(p.CompleteConstraints&&CompletionOriginalParameters(doc,p.OriginalMateIds)!=p.OriginalMateParameters)throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","补齐期间旧配合的参数、绑定或压缩状态变化。");
                if(allMates.Length!=count||suppressed.Any(fid=>!EGSuppressed(EGFeature(doc,fid))))throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","保留的原配合或新增配合数量不符。");
                if(actual==null||double.IsNaN(ratio)||double.IsInfinity(ratio)||Math.Abs(ratio-p.Numerator/p.Denominator)>1e-8)throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","比例或新配合数量不符。",new{requested_numerator=p.Numerator,requested_denominator=p.Denominator,observed_numerator=actual==null?(double?)null:actual.GearRatioNumerator,observed_denominator=actual==null?(double?)null:actual.GearRatioDenominator,native_reference_components=nativeIds,observed_normalized_ratio=double.IsNaN(ratio)||double.IsInfinity(ratio)?(double?)null:ratio,expected_mates=count,observed_mates=allMates.Length});
                var poses=Transforms(doc);var budget=MatePosePolicy.Evaluate(p.Poses,poses,.01,1e-6*180/Math.PI);
                if(!(bool)budget["accepted"])throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","自动补齐后的姿态超过确认预算。",budget);
                if(p.CompleteConstraints&&!p.Poses.All(v=>poses.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,poses[v.Key])))throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","配合补齐模式要求保留全部组件保存姿态。");
                var movingNames=moving.Select(v=>all[v].Name2).ToArray();foreach(var c in UserComponents(doc))if((p.CompleteConstraints?(movingNames.Contains(c.Name2)?c.IsFixed():c.IsFixed()!=p.Fixed[c.Name2]):c.IsFixed()==movingNames.Contains(c.Name2))||!movingNames.Contains(c.Name2)&&!PoseValidation.Matches(p.Poses[c.Name2],poses[c.Name2]))throw new CadFault("GEAR_FIXED_STATE_UNVERIFIED","固定状态或非目标组件姿态变化。");
                SaveOwnedDocuments(m);Save(doc,m.Path);var saved=Transforms(doc);var savedBudget=MatePosePolicy.Evaluate(p.Poses,saved,.01,1e-6*180/Math.PI);
                if(!(bool)savedBudget["accepted"])throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","保存后姿态超出预算。",savedBudget);
                if(p.CompleteConstraints&&!p.Poses.All(v=>saved.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,saved[v.Key])))throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","补齐成果保存后姿态变化。");
                m.Revision++;var motorFace=FaceReference(doc,p.References["input_axis"]);var motor=MateGeometry(doc,motorFace,all[p.Roles["input_shaft"]]);string entity=(string)motor["entity_id"];m.Entities[entity]=p.References["input_axis"];m.EntityRegistrationRevisions[entity]=m.Revision;SaveUserModel(m);VerifyUserSources(m);
                var shaftAxes=new Dictionary<string,object>();var supportAxes=new Dictionary<string,object>();foreach(string side in new[]{"input","output"}){shaftAxes[side]=MateGeometry(doc,FaceReference(doc,p.References[side+"_axis"]),all[p.Roles[side+"_shaft"]]);supportAxes[side]=MateGeometry(doc,FaceReference(doc,p.References[side+"_support"]),all[p.Roles[side+"_support"]]);}
                LastOperationRestoration="restored";
                return new{model_id=m.Id,plan_id=p.Id,roles=p.Roles,groups=p.Groups,axis_global=p.Axis,drive=motor,shaft_axes=shaftAxes,support_axes=supportAxes,
                    constraint_completion=p.CompleteConstraints,completion_checkpoint=completionCheckpoint,new_saved_initial_state=savedInitial,
                    completion_evidence=completionEvidence,observed_mate_suppression=EGAllMates(doc).ToDictionary(f=>f.GetID().ToString(System.Globalization.CultureInfo.InvariantCulture),f=>EGSuppressed(f)),
                    observed_fixed_states=UserComponents(doc).ToDictionary(c=>GTComponentId(doc,c),c=>c.IsFixed()),
                    native_parameters=new{verified=true,numerator=p.Numerator,denominator=p.Denominator,native_numerator=actual.GearRatioNumerator,native_denominator=actual.GearRatioDenominator,native_reference_components=nativeIds,observed_normalized_ratio=ratio,native_reverse=actual.Reverse,creation_reverse_argument=p.Reverse,direction_verified=false,mate_count=count,reported_mate_count=BasicMateFeatures(doc).Length,retained_suppressed_mate_ids=suppressed},
                    pose_budget=savedBudget,checkpoint_id=checkpoint,source_files_unchanged=true,restoration_status="restored",original_import_checkpoint_not_restored_yet=true};
            }
        }catch(Exception failure){
            if(!mutating)throw;
            if(failure is COMException){LastOperationRestoration="unknown";throw new CadFault("GEAR_ROLLBACK_FAILED","原生调用返回异常，未再次派发恢复写入；保留现场。",new{checkpoint_id=checkpoint,original_failure=FailureEvidence(failure),rollback_attempted=false,native_state="unknown"});}
            try{RestoreUserCheckpoint(m.Id,checkpoint);LastOperationRestoration="restored";}catch(Exception rollback){LastOperationRestoration="unknown";throw new CadFault("GEAR_ROLLBACK_FAILED","补齐失败且回退未确认。",new{checkpoint_id=checkpoint,original_failure=FailureEvidence(failure),rollback_failure=FailureEvidence(rollback)});}
            throw new CadFault("GEAR_APPLY_ROLLED_BACK","两轴补齐未通过，已恢复创建前检查点。",new{checkpoint_id=checkpoint,original_failure=FailureEvidence(failure),rollback_verified=true,automatic_retry=false});
        }
    }
}
