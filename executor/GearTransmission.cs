using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

// First scope: a named two-shaft pump, one prescribed 1:1 external gear relation.
// No tooth geometry, contact, force or generic mechanism inference is claimed.
public partial class Cad {
    class TransmissionPlan {
        public string Id,ModelId,Signature;
        public int Revision;
        public bool Consumed,GearReverse;
        public Dictionary<string,string> Roles,References;
        public Dictionary<string,double[]> Poses;
        public Dictionary<string,bool> Fixed;
        public double[] Axis;
        public double[] AxialDistances;
        public object Description;
    }
    readonly Dictionary<string,TransmissionPlan> transmissionPlans=new Dictionary<string,TransmissionPlan>();
    static double GTDot(double[] a,double[] b){return a.Zip(b,(x,y)=>x*y).Sum();}
    static double[] GTSub(double[] a,double[] b){return a.Zip(b,(x,y)=>x-y).ToArray();}
    static double GTGap(double[] point,double[] anchor,double[] axis){var d=GTSub(point,anchor);double t=GTDot(d,axis);return Math.Sqrt(d.Zip(axis,(x,y)=>(x-t*y)*(x-t*y)).Sum());}
    string GTReference(IModelDoc2 doc,object value){return Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(value));}
    string GTComponentId(IModelDoc2 doc,IComponent2 c){return StableId("component_",GTReference(doc,c));}
    IComponent2 GTUnique(IComponent2[] cs,string hint){var found=cs.Where(c=>c.Name2.IndexOf(hint,StringComparison.OrdinalIgnoreCase)>=0).ToArray();if(found.Length!=1)throw new CadFault("GEAR_ROLE_SELECTION_REQUIRED","泵角色名称未唯一匹配；本版不会猜测其他机构。",new{hint=hint,candidates=found.Select(c=>c.Name2).ToArray()});return found[0];}
    double[] GTCenter(IComponent2 c){var box=c.GetBox(false,false) as double[];if(box==null||box.Length!=6)throw new CadFault("GEAR_GEOMETRY_UNAVAILABLE","组件包围盒不可读取。");return new[]{(box[0]+box[3])/2,(box[1]+box[4])/2,(box[2]+box[5])/2};}
    IFace2 GTCylinder(IModelDoc2 doc,IComponent2 c,double[] anchor=null,double[] axis=null,double? radius=null){
        var pose=(double[])c.GetTotalTransform(false).ArrayData;
        var faces=Faces(c).Where(f=>((ISurface)f.GetSurface()).IsCylinder()).ToArray();
        if(axis!=null)faces=faces.Where(f=>Math.Abs(GTDot(ApplyPose(pose,((double[])((ISurface)f.GetSurface()).CylinderParams).Skip(3).Take(3).ToArray(),false),axis))>=1-1e-10).ToArray();
        if(faces.Length==0)throw new CadFault("GEAR_GEOMETRY_UNAVAILABLE","缺少适用圆柱轴线。",new{instance=c.Name2});
        return faces.OrderBy(f=>anchor==null?0:Math.Round(GTGap(ApplyPose(pose,((double[])((ISurface)f.GetSurface()).CylinderParams).Take(3).ToArray(),true),anchor,axis),7))
            .ThenBy(f=>radius.HasValue?Math.Abs(((double[])((ISurface)f.GetSurface()).CylinderParams)[6]-radius.Value):0).ThenByDescending(f=>f.GetArea()).First();
    }
    IFace2 GTPlane(IModelDoc2 doc,IComponent2 c,double[] axis){var pose=(double[])c.GetTotalTransform(false).ArrayData;var faces=Faces(c).Where(f=>((ISurface)f.GetSurface()).IsPlane()).Where(f=>Math.Abs(GTDot(ApplyPose(pose,((double[])((ISurface)f.GetSurface()).PlaneParams).Take(3).ToArray(),false),axis))>=1-1e-10).OrderByDescending(f=>f.GetArea()).ToArray();if(faces.Length==0)throw new CadFault("GEAR_GEOMETRY_UNAVAILABLE","缺少轴向定位平面。",new{instance=c.Name2});return faces[0];}
    void GTAssignPair(IModelDoc2 doc,IComponent2[] items,IComponent2[] shafts,IFace2[] axes,Dictionary<string,IComponent2> roles,string suffix){
        if(items.Length!=2)throw new CadFault("GEAR_ROLE_SELECTION_REQUIRED","首版要求恰好两个齿轮、两把键。",new{role=suffix,instances=items.Select(c=>c.Name2).ToArray()});
        var points=axes.Select((f,i)=>(double[])MateGeometry(doc,f,shafts[i])["reference_point_global_m"]).ToArray();
        var direction=(double[])MateGeometry(doc,axes[0],shafts[0])["axis_global"];
        foreach(var c in items){var center=GTCenter(c);var distances=points.Select(p=>GTGap(center,p,direction)).ToArray();if(Math.Abs(distances[0]-distances[1])<.001)throw new CadFault("GEAR_ROLE_SELECTION_REQUIRED","两侧距离不足以区分，请核对组件用途。",new{instance=c.Name2,axis_distances_m=distances});string side=distances[0]<distances[1]?"input_":"output_";if(roles.ContainsKey(side+suffix))throw new CadFault("GEAR_ROLE_SELECTION_REQUIRED","两个组件落在同一侧，未自动重分组。");roles[side+suffix]=c;}
    }
    public object PreviewGearTransmission(string id){
        if(Sw.RevisionNumber()!="34.0.0")throw new CadFault("GEAR_PUMP_SCOPE_UNSUPPORTED","本齿轮方向回读适配仅在SolidWorks 2026 revision 34.0.0校准。",new{revision=Sw.RevisionNumber()});
        var m=GetUserModel(id);using(var s=new Scope(this,m.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)){
            InspectUserCore(m,s.Doc);RequireMateInitialTime(s.Doc,m);
            var cs=((object[])((IAssemblyDoc)s.Doc).GetComponents(true)).Cast<IComponent2>().ToArray();
            if(cs.Length!=18||BasicMateFeatures(s.Doc).Length!=0||cs.Any(c=>c.IsSuppressed()||c.IsSpeedPak||c.GetModelDoc2()==null||!m.Files.Contains(c.GetPathName(),StringComparer.OrdinalIgnoreCase)))throw new CadFault("GEAR_PUMP_SCOPE_UNSUPPORTED","首版只接受18个已解析顶层零件、无既有配合的泵副本，未知装配不改写。");
            var body=GTUnique(cs,"泵体");var shafts=new[]{GTUnique(cs,"长轴"),GTUnique(cs,"短轴")};
            if(!body.IsFixed())throw new CadFault("GEAR_PUMP_SCOPE_UNSUPPORTED","泵体须保持固定。");
            var axes=shafts.Select(c=>GTCylinder(s.Doc,c)).ToArray();var ax=(double[])MateGeometry(s.Doc,axes[0],shafts[0])["axis_global"];
            if(Math.Abs(GTDot(ax,(double[])MateGeometry(s.Doc,axes[1],shafts[1])["axis_global"]))<1-1e-10)throw new CadFault("GEAR_PUMP_SCOPE_UNSUPPORTED","两轴不平行，不进入此外齿轮模板。");
            var roles=new Dictionary<string,IComponent2>{{"body",body},{"input_shaft",shafts[0]},{"output_shaft",shafts[1]}};
            GTAssignPair(s.Doc,cs.Where(c=>c.Name2.IndexOf("Spur_gear",StringComparison.OrdinalIgnoreCase)>=0).ToArray(),shafts,axes,roles,"gear");
            GTAssignPair(s.Doc,cs.Where(c=>c.Name2.IndexOf("KEYS",StringComparison.OrdinalIgnoreCase)>=0).ToArray(),shafts,axes,roles,"key");
            if(roles.Values.Distinct().Count()!=7||cs.Any(c=>!roles.Values.Contains(c)&&!c.IsFixed()))throw new CadFault("GEAR_PUMP_SCOPE_UNSUPPORTED","六个运动件之外必须全部固定。");
            var refs=new Dictionary<string,string>();var descriptions=new List<object>();var distances=new double[2];var gearAxes=new double[2][];
            for(int i=0;i<2;i++){
                string side=i==0?"input":"output";var shaft=shafts[i];var shape=MateGeometry(s.Doc,axes[i],shaft);var anchor=(double[])shape["reference_point_global_m"];
                var support=GTCylinder(s.Doc,body,anchor,ax,(double?)shape["cylinder_radius_m"]);var supportGeometry=MateGeometry(s.Doc,support,body);
                double gap=GTGap((double[])supportGeometry["reference_point_global_m"],anchor,ax);if(gap>.00001)throw new CadFault("GEAR_SUPPORT_ALIGNMENT_EXCEEDED","轴与支承轴线偏差超过0.01mm，不自动装配。",new{side=side,radial_offset_mm=gap*1000});
                var plane=GTPlane(s.Doc,shaft,ax);var bodyPlane=GTPlane(s.Doc,body,ax);var gearAxis=GTCylinder(s.Doc,roles[side+"_gear"],anchor,ax);
                gearAxes[i]=(double[])MateGeometry(s.Doc,gearAxis,roles[side+"_gear"])["axis_global"];
                distances[i]=Math.Abs(GTDot(GTSub((double[])MateGeometry(s.Doc,plane,shaft)["reference_point_global_m"],(double[])MateGeometry(s.Doc,bodyPlane,body)["reference_point_global_m"]),ax));
                refs[side+"_axis"]=GTReference(s.Doc,axes[i]);refs[side+"_support"]=GTReference(s.Doc,support);refs[side+"_plane"]=GTReference(s.Doc,plane);refs[side+"_body_plane"]=GTReference(s.Doc,bodyPlane);refs[side+"_gear_axis"]=GTReference(s.Doc,gearAxis);
                descriptions.Add(new{side=side,shaft_axis=shape,support_axis=supportGeometry,radial_offset_mm=gap*1000,axial_distance_mm=distances[i]*1000});
            }
            // Native mate direction is not the sign of a cylinder parameterization.
            // This named-pump template uses its calibrated default; the signed
            // waveform must independently prove external counter-rotation.
            var p=new TransmissionPlan{Id=Guid.NewGuid().ToString("N"),ModelId=id,Revision=m.Revision,Roles=roles.ToDictionary(k=>k.Key,k=>GTComponentId(s.Doc,k.Value)),References=refs,Poses=Transforms(s.Doc),Fixed=cs.ToDictionary(c=>c.Name2,c=>c.IsFixed()),Axis=ax,AxialDistances=distances,GearReverse=false};
            p.Signature=MateSignature(m,s.Doc);p.Description=new{plan_id=p.Id,model_id=id,model_revision=m.Revision,roles=roles.ToDictionary(k=>k.Key,k=>(object)new{component_id=p.Roles[k.Key],instance=k.Value.Name2,currently_fixed=k.Value.IsFixed()}),supports=descriptions,gear_ratio=new{numerator=1,denominator=1,expected_output_over_input=-1,source="explicit_trial_ratio_not_tooth_measurement",creation_reverse_argument=p.GearReverse,expected_reverse_readback=!p.GearReverse,direction_requires_independent_signed_pose_verification=true},maximum_setup_translation_mm=.01,maximum_setup_rotation_rad=1e-6,expected_added_mates=9,floating_after=6,fixed_after=12,scope="named_pump_two_rigid_rotors_prescribed_external_1_to_1_not_contact",contact_or_tooth_geometry_validated=false,requires_explicit_confirmation=true,write_dispatched=false};
            transmissionPlans.Add(p.Id,p);SaveUserModel(m);return p.Description;
        }
    }
    void GTShaftSupport(IModelDoc2 doc,IComponent2 shaft,TransmissionPlan p,string side,int index){
        var initial=(double[])shaft.Transform2.ArrayData;int error;SelectMateFaces(doc,FaceReference(doc,p.References[side+"_axis"]),FaceReference(doc,p.References[side+"_support"]));
        var ad=(IAssemblyDoc)doc;var mate=ad.AddMate5(1,2,false,0,0,0,1,1,0,0,0,false,false,0,out error);doc.ClearSelection2(true);if(mate==null||error!=1)throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","轴支承同轴配合失败。",new{native_error=error,side=side});
        SelectMateFaces(doc,FaceReference(doc,p.References[side+"_plane"]),FaceReference(doc,p.References[side+"_body_plane"]));double distance=p.AxialDistances[index];mate=ad.AddMate5(5,2,false,distance,distance,distance,1,1,0,0,0,false,false,0,out error);doc.ClearSelection2(true);if(mate==null||error!=1)throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","轴向定位配合失败。",new{native_error=error,side=side});
        if(!doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","轴系重建失败。");var current=(double[])shaft.Transform2.ArrayData;
        double axial=Math.Abs(GTDot(GTSub(current.Skip(9).Take(3).ToArray(),initial.Skip(9).Take(3).ToArray()),p.Axis));
        if(axial>1e-7){mate.Flipped=!mate.Flipped;if(!doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","轴向分支重建失败。");current=(double[])shaft.Transform2.ArrayData;axial=Math.Abs(GTDot(GTSub(current.Skip(9).Take(3).ToArray(),initial.Skip(9).Take(3).ToArray()),p.Axis));}
        if(axial>1e-7)throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","轴向定位未保留起点。",new{side=side,axial_translation_m=axial});
    }
    public object ApplyGearTransmission(string planId,bool confirmed,bool testFault=false){
        if(testFault&&System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new CadFault("FAULT_TESTS_DISABLED","受控故障仅用于本机开发验收。");
        TransmissionPlan p;if(!transmissionPlans.TryGetValue(planId??"",out p))throw new CadFault("GEAR_PLAN_STALE","齿轮方案不存在。");if(!confirmed)throw new CadFault("MATE_CONFIRMATION_REQUIRED","须明确同意解除指定固定和完整传动方案。");if(p.Consumed)throw new CadFault("GEAR_PLAN_CONSUMED","完整传动方案已提交，不重放写入。");
        var m=GetUserModel(p.ModelId);using(var s=new Scope(this,m.Path,null)){if(m.Revision!=p.Revision||MateSignature(m,s.Doc)!=p.Signature)throw new CadFault("GEAR_PLAN_STALE","初态、文件或引用改变，须重新规划。");RequireMateInitialTime(s.Doc,m);}
        p.Consumed=true;string checkpoint=null;bool mutating=false;
        try{
            var cp=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(m.Id)));checkpoint=(string)cp["checkpoint_id"];CheckpointProbeWithTiming(m,p.Id,checkpoint);
            using(var s=new Scope(this,m.Path,null)){
                RequireMateInitialTime(s.Doc,m);if(BasicMateFeatures(s.Doc).Length!=0)throw new CadFault("GEAR_PLAN_STALE","探测后已有配合状态改变。");var ad=(IAssemblyDoc)s.Doc;
                var roles=p.Roles.ToDictionary(k=>k.Key,k=>ResolveUserComponent(m,s.Doc,k.Value));mutating=true;LastOperationRestoration="pending";WriteStage("gear_unfix",m.Id,p.Id,checkpoint);
                foreach(var item in roles.Where(k=>k.Key!="body")){var c=item.Value;if(c.IsFixed()){s.Doc.ClearSelection2(true);if(!c.Select4(false,null,false))throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","组件选择失败。");ad.UnfixComponent();s.Doc.ClearSelection2(true);}if(c.IsFixed())throw new CadFault("GEAR_FIXED_STATE_UNVERIFIED","解除固定未生效。");}
                if(testFault)throw new CadFault("CONTROLLED_GEAR_FAULT","验收：解除指定固定后触发回退。");
                foreach(string side in new[]{"input","output"}){LockPair(s.Doc,roles[side+"_shaft"],roles[side+"_gear"]);LockPair(s.Doc,roles[side+"_shaft"],roles[side+"_key"]);}
                WriteStage("gear_shaft_supports",m.Id,p.Id,checkpoint);GTShaftSupport(s.Doc,roles["input_shaft"],p,"input",0);GTShaftSupport(s.Doc,roles["output_shaft"],p,"output",1);
                var definition=(IGearMateFeatureData)ad.CreateMateData(10);definition.EntitiesToMate=new DispatchWrapper[]{new DispatchWrapper(FaceReference(s.Doc,p.References["input_gear_axis"])),new DispatchWrapper(FaceReference(s.Doc,p.References["output_gear_axis"]))};definition.GearRatioNumerator=1;definition.GearRatioDenominator=1;definition.Reverse=p.GearReverse;
                WriteStage("gear_ratio_mate",m.Id,p.Id,checkpoint);var gear=(IFeature)ad.CreateMate(definition);CheckMate(gear,"confirmed_external_1_to_1");s.Doc.ClearSelection2(true);if(!s.Doc.EditRebuild3())throw new CadFault("GEAR_CONSTRAINT_CREATE_FAILED","完整轴系重建失败。");RequireMatesHealthy(s.Doc);
                var actual=gear.GetDefinition() as IGearMateFeatureData;double numerator=actual==null?double.NaN:actual.GearRatioNumerator,denominator=actual==null?double.NaN:actual.GearRatioDenominator;int observedCount=BasicMateFeatures(s.Doc).Length;
                var observedGear=new{definition_available=actual!=null,numerator=double.IsNaN(numerator)||double.IsInfinity(numerator)?(double?)null:numerator,denominator=double.IsNaN(denominator)||double.IsInfinity(denominator)?(double?)null:denominator,native_reverse=actual==null?(bool?)null:actual.Reverse,creation_reverse_argument=p.GearReverse,expected_reverse_readback=!p.GearReverse,adapter="SW34_named_pump_creation_vs_feature_readback",mate_count=observedCount,expected_mate_count=9,types=BasicMateFeatures(s.Doc).Select(f=>((IMate2)f.GetSpecificFeature2()).Type).ToArray()};
                if(actual==null||double.IsNaN(numerator)||double.IsNaN(denominator)||double.IsInfinity(numerator)||double.IsInfinity(denominator)||numerator<=0||denominator<=0||Math.Abs(numerator/denominator-1)>1e-10||actual.Reverse==p.GearReverse||observedCount!=9)throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","齿轮比例、方向回读或9项约束未核实。",observedGear);
                var poses=Transforms(s.Doc);var budget=MatePosePolicy.Evaluate(p.Poses,poses,.01,1e-6*180/Math.PI);if(!(bool)budget["accepted"])throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","轴系装配移动超过确认预算。",budget);
                var moving=roles.Where(k=>k.Key!="body").Select(k=>k.Value.Name2).ToArray();foreach(IComponent2 c in (object[])ad.GetComponents(true)){if(c.IsFixed()==moving.Contains(c.Name2))throw new CadFault("GEAR_FIXED_STATE_UNVERIFIED","固定状态不符合六动件范围。");if(!moving.Contains(c.Name2)&&!PoseValidation.Matches(p.Poses[c.Name2],poses[c.Name2]))throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","固定组件发生移动。");}
                var types=BasicMateFeatures(s.Doc).Select(f=>((IMate2)f.GetSpecificFeature2()).Type).ToArray();if(types.Count(v=>v==16)!=4||types.Count(v=>v==1)!=2||types.Count(v=>v==5)!=2||types.Count(v=>v==10)!=1)throw new CadFault("GEAR_PARAMETERS_UNVERIFIED","原生约束类型不符合四刚性、两同轴、两轴向及一齿轮。");
                SaveOwnedDocuments(m);Save(s.Doc,m.Path);var savedPoses=Transforms(s.Doc);var savedBudget=MatePosePolicy.Evaluate(p.Poses,savedPoses,.01,1e-6*180/Math.PI);if(!(bool)savedBudget["accepted"]||p.Poses.Any(v=>!moving.Contains(v.Key)&&!PoseValidation.Matches(v.Value,savedPoses[v.Key])))throw new CadFault("GEAR_SETUP_POSE_EXCEEDED","保存后姿态超出方案预算。",savedBudget);
                m.Revision++;var motorFace=FaceReference(s.Doc,p.References["input_axis"]);var motorGeometry=MateGeometry(s.Doc,motorFace);string entity=(string)motorGeometry["entity_id"];m.Entities[entity]=p.References["input_axis"];m.EntityRegistrationRevisions[entity]=m.Revision;SaveUserModel(m);VerifyUserSources(m);LastOperationRestoration="restored";
                var shaftAxes=new Dictionary<string,object>();var supportAxes=new Dictionary<string,object>();foreach(string side in new[]{"input","output"}){shaftAxes[side]=MateGeometry(s.Doc,FaceReference(s.Doc,p.References[side+"_axis"]),roles[side+"_shaft"]);supportAxes[side]=MateGeometry(s.Doc,FaceReference(s.Doc,p.References[side+"_support"]),roles["body"]);}
                return new{model_id=m.Id,plan_id=p.Id,checkpoint_id=checkpoint,roles=p.Roles,axis_global=p.Axis,drive=motorGeometry,shaft_axes=shaftAxes,support_axes=supportAxes,native_parameters=new{gear_ratio_numerator=actual.GearRatioNumerator,gear_ratio_denominator=actual.GearRatioDenominator,native_reverse=actual.Reverse,creation_reverse_argument=p.GearReverse,expected_reverse_readback=!p.GearReverse,direction_verified=false,direction_verification="requires_signed_pose_samples_not_boolean_equality",mate_count=9,mate_types=types,verified=true},pose_budget=savedBudget,source_files_unchanged=true,scope="prescribed_external_1_to_1_not_contact",restoration_status="restored",original_import_checkpoint_not_restored_yet=true};
            }
        }catch(Exception failure){
            if(!mutating)throw;
            try{RestoreUserCheckpoint(m.Id,checkpoint);LastOperationRestoration="restored";}catch(Exception rollback){LastOperationRestoration="unknown";throw new CadFault("GEAR_ROLLBACK_FAILED","轴系准备失败且恢复未验证，保留现场。",new{checkpoint_id=checkpoint,original_failure=FailureEvidence(failure),rollback_failure=FailureEvidence(rollback)});}
            throw new CadFault("GEAR_APPLY_ROLLED_BACK","轴系准备未通过，已恢复准备前检查点。",new{checkpoint_id=checkpoint,rollback_verified=true,original_failure=FailureEvidence(failure),automatic_retry=false});
        }
    }
}
