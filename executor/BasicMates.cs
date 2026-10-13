using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public partial class Cad {
    class MatePlan {
        public string Id,ModelId,EntityA,EntityB,Type,Alignment,Signature,BaselineRunId,CheckpointId;
        public int Revision,AppliedRevision;
        public double DistanceMm;
        public bool LockRotation,Consumed;
    }
    readonly Dictionary<string,MatePlan> matePlans=new Dictionary<string,MatePlan>();
    static int BasicMateType(string type){switch(type){case "coincident":return (int)swMateType_e.swMateCOINCIDENT;case "concentric":return (int)swMateType_e.swMateCONCENTRIC;case "distance":return (int)swMateType_e.swMateDISTANCE;case "parallel":return (int)swMateType_e.swMatePARALLEL;case "perpendicular":return (int)swMateType_e.swMatePERPENDICULAR;default:throw new CadFault("UNSUPPORTED_BASIC_MATE","仅支持同心、重合、距离、平行、垂直配合。");}}
    IFace2 MateFace(UserModel m,IModelDoc2 doc,string id) {
        string value;if(!m.Entities.TryGetValue(id??"",out value))throw new CadFault("MATE_REFERENCE_NOT_REGISTERED","请先查询本模型的配合参考。");
        int error;var face=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(value),out error) as IFace2;
        if(face==null||error!=0)throw new CadFault("MATE_REFERENCE_STALE","配合参考已过期，请重新查询。");
        var owner=((IEntity)face).GetComponent() as IComponent2;
        var top=((object[])((IAssemblyDoc)doc).GetComponents(true)).Cast<IComponent2>();
        if(owner==null||!top.Any(c=>c.Name2==owner.Name2)||owner.IsSuppressed()||owner.IsSpeedPak||owner.GetModelDoc2()==null||!owner.GetPathName().EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase))throw new CadFault("MATE_COMPONENT_UNSUPPORTED","首版仅支持已解析的顶层刚体零件。");
        if(!m.Files.Contains(owner.GetPathName(),StringComparer.OrdinalIgnoreCase))throw new CadFault("MATE_REFERENCE_NOT_ISOLATED","参考零件不在登记的副本文件集合中。");
        return face;
    }
    Dictionary<string,object> MateGeometry(IModelDoc2 doc,IFace2 face) {
        var surface=(ISurface)face.GetSurface();bool cylinder=surface.IsCylinder();if(!cylinder&&!surface.IsPlane())throw new CadFault("MATE_GEOMETRY_UNSUPPORTED","仅支持圆柱面及平面。");
        var c=(IComponent2)((IEntity)face).GetComponent();var data=(double[])(cylinder?surface.CylinderParams:surface.PlaneParams);var pose=(double[])c.GetTotalTransform(false).ArrayData;
        var axis=ApplyPose(pose,cylinder?data.Skip(3).Take(3).ToArray():data.Take(3).ToArray(),false);double norm=Math.Sqrt(axis.Sum(v=>v*v));if(norm<1e-12)throw new Exception("INVALID_MATE_GEOMETRY");
        string reference=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(face));
        return new Dictionary<string,object>{{"entity_id",StableId("entity_",reference)},{"component_id",StableId("component_",Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(c)))},{"instance",c.Name2},{"kind",cylinder?"cylindrical_axis":"planar_normal"},{"axis_global",axis.Select(v=>v/norm).ToArray()},{"reference_point_global_m",ApplyPose(pose,cylinder?data.Take(3).ToArray():data.Skip(3).Take(3).ToArray(),true)},{"area_m2",face.GetArea()},{"fixed_component",c.IsFixed()},{"requires_user_selection",true}};
    }
    string MateSignature(UserModel m,IModelDoc2 doc) {
        var loaded=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Where(d=>m.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)).OrderBy(d=>d.GetPathName(),StringComparer.OrdinalIgnoreCase).Select(d=>new{path=d.GetPathName(),stamp=d.GetUpdateStamp(),dirty=d.GetSaveFlag()}).ToArray();
        return StableId("state_",Json.Serialize(new{revision=m.Revision,configuration=doc.ConfigurationManager.ActiveConfiguration.Name,files=m.Files.ToDictionary(p=>p,p=>FileHash(p)),documents=loaded,poses=Transforms(doc),studies=StudyStates(doc),mates=UserMates(doc)}));
    }
    public object ListMateReferences(string id,string componentId,string kind,int limit,string cursor) {
        if(limit<1||limit>50||!new[]{"","cylindrical_axis","planar_normal"}.Contains(kind??""))throw new CadFault("INVALID_MATE_REFERENCE_OPTIONS","limit须在1–50，kind须为平面或圆柱面类型。");
        var m=GetUserModel(id);using(var scope=new Scope(this,m.Path,null)) {
            InspectUserCore(m,scope.Doc);var cs=((object[])((IAssemblyDoc)scope.Doc).GetComponents(true)).Cast<IComponent2>().OrderBy(c=>c.Name2,StringComparer.Ordinal).ToArray();if(cs.Length>500)throw new Exception("COMPONENT_BUDGET_EXCEEDED");
            if(!string.IsNullOrEmpty(componentId)&&!cs.Any(c=>StableId("component_",Convert.ToBase64String((byte[])scope.Doc.Extension.GetPersistReference3(c)))==componentId))throw new CadFault("MATE_COMPONENT_UNSUPPORTED","请选择顶层组件。");
            var entities=new List<Dictionary<string,object>>();var references=new Dictionary<string,string>();var omitted=new List<string>();var truncated=new List<string>();
            foreach(var c in cs) {
                string cid=StableId("component_",Convert.ToBase64String((byte[])scope.Doc.Extension.GetPersistReference3(c)));if(!string.IsNullOrEmpty(componentId)&&cid!=componentId)continue;
                if(c.IsSuppressed()||c.IsSpeedPak||c.GetModelDoc2()==null||!c.GetPathName().EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase)){omitted.Add(c.Name2);continue;}
                var eligible=Faces(c).Where(f=>{var s=(ISurface)f.GetSurface();return kind=="cylindrical_axis"?s.IsCylinder():kind=="planar_normal"?s.IsPlane():s.IsCylinder()||s.IsPlane();}).OrderByDescending(f=>f.GetArea()).Take(129).ToArray();if(eligible.Length>128)truncated.Add(c.Name2);
                foreach(var face in eligible.Take(128)){var row=MateGeometry(scope.Doc,face);entities.Add(row);references[(string)row["entity_id"]]=Convert.ToBase64String((byte[])scope.Doc.Extension.GetPersistReference3(face));}
            }
            string signature=MateSignature(m,scope.Doc);int offset=0;
            if(!string.IsNullOrEmpty(cursor)){try{var d=Json.Deserialize<Dictionary<string,object>>(System.Text.Encoding.UTF8.GetString(Convert.FromBase64String(cursor)));if((string)d["signature"]!=signature||(string)d["component_id"]!=(componentId??"")||(string)d["kind"]!=(kind??""))throw new Exception();offset=Convert.ToInt32(d["offset"]);if(offset<0||offset>entities.Count)throw new Exception();}catch{throw new CadFault("MATE_CURSOR_STALE","分页输入已改变，请从第一页查询。");}}
            var page=entities.Skip(offset).Take(limit).ToArray();foreach(var row in page)m.Entities[(string)row["entity_id"]]=references[(string)row["entity_id"]];SaveUserModel(m);
            return new{model_id=id,model_revision=m.Revision,entities=page,returned=page.Length,total=entities.Count,omitted_components=omitted,truncated_components=truncated,per_component_face_budget=128,next_cursor=offset+page.Length<entities.Count?Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(Json.Serialize(new{signature=signature,component_id=componentId??"",kind=kind??"",offset=offset+page.Length}))):null,claim="explicit_geometric_references_no_design_intent_inference"};
        }
    }
    void CheckMatePair(IFace2 a,IFace2 b,string type,bool lockRotation) {
        BasicMateType(type);if(lockRotation&&type!="concentric")throw new CadFault("INVALID_MATE_OPTIONS","锁定旋转仅适用于同心配合。");
        var ca=(IComponent2)((IEntity)a).GetComponent();var cb=(IComponent2)((IEntity)b).GetComponent();if(ca.Name2==cb.Name2)throw new CadFault("MATE_SAME_COMPONENT","须选择两个不同零件实例。");if(ca.IsFixed()&&cb.IsFixed())throw new CadFault("MATE_BOTH_COMPONENTS_FIXED","两个零件均固定，拒绝添加配合。");
        var sa=(ISurface)a.GetSurface();var sb=(ISurface)b.GetSurface();if(type=="concentric"?!(sa.IsCylinder()&&sb.IsCylinder()):!(sa.IsPlane()&&sb.IsPlane()))throw new CadFault("MATE_REFERENCE_TYPE_MISMATCH","同心配合须选两个圆柱面，其余首版配合须选两个平面。");
    }
    void RequireMateInitialTime(IModelDoc2 doc){if(StudyStates(doc).Any(s=>Math.Abs(s.time_s)>1e-8))throw new CadFault("MATE_REQUIRES_INITIAL_TIME","所有算例须在初始时刻；请显式归零后重新生成方案。");}
    void RequireMatesHealthy(IModelDoc2 doc){foreach(var row in UserMates(doc)){var d=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(row));if(Convert.ToInt32(d["error"])!=0)throw new CadFault("MATE_REBUILD_FAILED","存在配合错误，不能判定创建成功。",d);}}
    static IFeature[] BasicMateFeatures(IModelDoc2 doc){var rows=new List<IFeature>();var f=(IFeature)doc.FirstFeature();while(f!=null){if(f.GetTypeName2()=="MateGroup"){var child=(IFeature)f.GetFirstSubFeature();while(child!=null){if(child.GetSpecificFeature2() is IMate2)rows.Add(child);child=(IFeature)child.GetNextSubFeature();}}f=(IFeature)f.GetNextFeature();}return rows.ToArray();}
    static string[] DirectRotationLocks(IModelDoc2 doc,string instance){return BasicMateFeatures(doc).Where(f=>{var data=f.GetDefinition() as IConcentricMateFeatureData;if(data==null||!data.LockRotation)return false;var mate=(IMate2)f.GetSpecificFeature2();var cs=Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>mate.MateEntity(i).ReferenceComponent as IComponent2).Where(c=>c!=null).ToArray();return cs.Any(c=>c.Name2==instance)&&cs.Any(c=>c.Name2!=instance&&c.IsFixed());}).Select(f=>f.Name).ToArray();}
    public object PreviewBasicMate(string id,string a,string b,string type,string alignment,double distance,bool lockRotation,string baselineId) {
        BasicMateType(type);if(!new[]{"aligned","anti_aligned"}.Contains(alignment)||double.IsNaN(distance)||double.IsInfinity(distance)||distance<0||distance>10000||(type!="distance"&&distance!=0))throw new CadFault("INVALID_MATE_OPTIONS","方向须明确指定；距离为0–10000mm且仅用于距离配合。");
        if(matePlans.Count>=128)throw new CadFault("MATE_PLAN_BUDGET_EXCEEDED","本会话方案数超过128，请完成已有方案或重新连接。");
        var m=GetUserModel(id);using(var s=new Scope(this,m.Path,null)) {
            InspectUserCore(m,s.Doc);RequireMateInitialTime(s.Doc);RequireMatesHealthy(s.Doc);var fa=MateFace(m,s.Doc,a);var fb=MateFace(m,s.Doc,b);CheckMatePair(fa,fb,type,lockRotation);
            if(!string.IsNullOrEmpty(baselineId)){Run r;if(!runs.TryGetValue(baselineId,out r)||!r.Generic||r.Assembly!=id)throw new CadFault("MATE_BASELINE_INVALID","基线须为本会话、本模型的已验证运行。");ValidateUserStoredRun(r);}
            var p=new MatePlan{Id=Guid.NewGuid().ToString("N"),ModelId=id,EntityA=a,EntityB=b,Type=type,Alignment=alignment,DistanceMm=distance,LockRotation=lockRotation,Revision=m.Revision,Signature=MateSignature(m,s.Doc),BaselineRunId=baselineId};matePlans.Add(p.Id,p);
            return new{plan_id=p.Id,model_id=id,model_revision=m.Revision,reference_a=MateGeometry(s.Doc,fa),reference_b=MateGeometry(s.Doc,fb),mate_type=type,alignment=alignment,distance_mm=distance,lock_rotation=lockRotation,baseline_run_id=baselineId,preview_kind="descriptive_only_no_geometry_change",motion_preservation_status="not_checked",requires_explicit_confirmation=true,warnings=lockRotation?new[]{"RELATIVE_ROTATION_WILL_BE_LOCKED","MOTION_NOT_YET_VERIFIED"}:new[]{"MOTION_NOT_YET_VERIFIED"},expires="on_state_change_or_executor_restart"};
        }
    }
    MatePlan GetMatePlan(string id){MatePlan p;if(!matePlans.TryGetValue(id??"",out p))throw new CadFault("MATE_PLAN_NOT_FOUND","方案不存在或执行器已重启，请重新预览。");return p;}
    public object ApplyBasicMate(string planId,bool confirmed,bool testFault=false) {
        if(!confirmed)throw new CadFault("MATE_CONFIRMATION_REQUIRED","请在用户明确确认参考、配合类型及参数后执行。");if(testFault&&System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TESTS_DISABLED");
        var p=GetMatePlan(planId);if(p.Consumed)throw new CadFault("MATE_PLAN_CONSUMED","方案已经执行，不自动重复写入。");var m=GetUserModel(p.ModelId);
        using(var s=new Scope(this,m.Path,null)){InspectUserCore(m,s.Doc);if(m.Revision!=p.Revision||MateSignature(m,s.Doc)!=p.Signature)throw new CadFault("MATE_PLAN_STALE","模型、姿态、文件或更新标记已改变，请重新预览。");RequireMateInitialTime(s.Doc);CheckMatePair(MateFace(m,s.Doc,p.EntityA),MateFace(m,s.Doc,p.EntityB),p.Type,p.LockRotation);}
        var cp=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(m.Id)));p.CheckpointId=(string)cp["checkpoint_id"];p.Consumed=true;LastOperationRestoration="pending";
        try {
            using(var s=new Scope(this,m.Path,null)) {
                RequireMateInitialTime(s.Doc);var a=MateFace(m,s.Doc,p.EntityA);var b=MateFace(m,s.Doc,p.EntityB);CheckMatePair(a,b,p.Type,p.LockRotation);RequireMatesHealthy(s.Doc);
                var beforeFeatures=BasicMateFeatures(s.Doc).Select(f=>f.Name).ToArray();int before=beforeFeatures.Length;var poses=Transforms(s.Doc);s.EnsureActive();s.Doc.ClearSelection2(true);
                try{var select=((ISelectionMgr)s.Doc.SelectionManager).CreateSelectData();select.Mark=1;if(!((IEntity)a).Select4(false,select)||!((IEntity)b).Select4(true,select))throw new CadFault("MATE_SELECTION_FAILED","SolidWorks拒绝选择配合参考。");
                    int error;var mate=((IAssemblyDoc)s.Doc).AddMate5(BasicMateType(p.Type),p.Alignment=="aligned"?0:1,false,p.DistanceMm/1000,p.DistanceMm/1000,p.DistanceMm/1000,1,1,0,0,0,false,p.LockRotation,0,out error);
                    if(mate==null||error!=(int)swAddMateError_e.swAddMateError_NoError)throw new CadFault("MATE_CREATE_FAILED","原生配合创建失败，将恢复检查点。",new{native_error=error,mate_created=mate!=null});
                }finally{s.Doc.ClearSelection2(true);}
                if(testFault)throw new CadFault("CONTROLLED_MATE_FAULT","测试：创建后触发恢复。");
                if(!s.Doc.EditRebuild3())throw new CadFault("MATE_REBUILD_FAILED","添加配合后的重建失败。");RequireMatesHealthy(s.Doc);int after=UserMates(s.Doc).Length;if(after!=before+1)throw new CadFault("MATE_COUNT_UNVERIFIED","未确认恰好新增一项配合。");
                var added=BasicMateFeatures(s.Doc).Where(f=>!beforeFeatures.Contains(f.Name)).ToArray();if(added.Length!=1)throw new CadFault("MATE_PARAMETERS_UNVERIFIED","未确认新配合的原生特征。");var actual=(IMate2)added[0].GetSpecificFeature2();var concentric=added[0].GetDefinition() as IConcentricMateFeatureData;
                double? actualDistance=null;if(p.Type=="distance"){var display=actual.DisplayDimension2[0] as IDisplayDimension;if(display==null)throw new CadFault("MATE_PARAMETERS_UNVERIFIED","距离配合尺寸不可读取。");actualDistance=((IDimension)display.GetDimension2(0)).SystemValue*1000;}
                if(actual.Type!=BasicMateType(p.Type)||(p.Type!="perpendicular"&&actual.Alignment!=(p.Alignment=="aligned"?0:1))||(p.Type=="concentric"&&(concentric==null||concentric.LockRotation!=p.LockRotation))||(actualDistance.HasValue&&Math.Abs(Math.Abs(actualDistance.Value)-p.DistanceMm)>1e-5))throw new CadFault("MATE_PARAMETERS_UNVERIFIED","原生配合参数与确认方案不一致。",new{native_type=actual.Type,native_alignment=actual.Alignment,native_lock_rotation=concentric==null?(bool?)null:concentric.LockRotation,native_distance_mm=actualDistance});
                var nativeParameters=new{feature=added[0].Name,type=actual.Type,alignment=actual.Alignment,lock_rotation=concentric==null?(bool?)null:concentric.LockRotation,distance_mm=actualDistance,verified=true};
                SaveOwnedDocuments(m);Save(s.Doc,m.Path);m.Revision++;SaveUserModel(m);VerifyUserSources(m);p.AppliedRevision=m.Revision;LastOperationRestoration="restored";
                return new{plan_id=p.Id,model_id=m.Id,model_revision=m.Revision,checkpoint_id=p.CheckpointId,mate_type=p.Type,alignment=p.Alignment,distance_mm=p.DistanceMm,lock_rotation=p.LockRotation,native_parameters=nativeParameters,mate_count_before=before,mate_count_after=after,position_change=PoseDifference(poses,Transforms(s.Doc)),baseline_run_id=p.BaselineRunId,motion_preservation_status="not_checked",results_invalidated=true,source_files_unchanged=true,restoration_status="restored",claim="mate_created_and_rebuilt_only"};
            }
        }catch(Exception failure){try{RestoreUserCheckpoint(m.Id,p.CheckpointId);LastOperationRestoration="restored";}catch(Exception rollback){LastOperationRestoration="unknown";throw new CadFault("MATE_ROLLBACK_FAILED","配合操作失败且恢复未确认，必须恢复检查点。",new{checkpoint_id=p.CheckpointId,original_error=failure.Message,rollback_error=rollback.Message});}throw new CadFault("MATE_APPLY_ROLLED_BACK","配合操作失败，已恢复检查点。",new{checkpoint_id=p.CheckpointId,original_error=HistoryErrorCode(failure),native_diagnostics=failure is CadFault?((CadFault)failure).Diagnostics:null});}
    }
    public object VerifyRequestedMotion(string id,string study,string componentId,string entityId,string kind,double minimum,double duration,int fps,string runId,string planId) {
        if(!System.Text.RegularExpressions.Regex.IsMatch(runId??"","^[a-f0-9]{32}$"))throw new CadFault("INVALID_RUN_ID","运行标识格式无效。");
        if(double.IsNaN(duration)||double.IsInfinity(duration)||duration<=0||duration>5||fps<5||fps>120||Math.Abs(duration*fps-Math.Round(duration*fps))>1e-8||Math.Round(duration*fps)+1>601)throw new CadFault("MOTION_BUDGET_REJECTED","显式验证最多5秒、601帧。");
        if(!new[]{"rotary","linear"}.Contains(kind)||double.IsNaN(minimum)||double.IsInfinity(minimum)||minimum<=0)throw new CadFault("INVALID_MOTION_INTENT","指定旋转/直线运动及有限正数的最低运动量。");
        var m=GetUserModel(id);MatePlan plan=null;Run baseline=null;
        if(!string.IsNullOrEmpty(planId)){plan=GetMatePlan(planId);if(plan.ModelId!=id||!plan.Consumed||plan.AppliedRevision==0||plan.AppliedRevision!=m.Revision)throw new CadFault("MATE_VALIDATION_PLAN_STALE","配合方案未成功应用或模型已再次变化。");if(!string.IsNullOrEmpty(plan.BaselineRunId)){baseline=runs[plan.BaselineRunId];if(baseline.Study!=study||!baseline.ComponentNames.ContainsKey(componentId)||baseline.Duration!=duration||baseline.Fps!=fps)throw new CadFault("MATE_BASELINE_SCOPE_MISMATCH","前后比较须使用相同算例、组件、时长和帧率。");}}
        double[] axis;string[] directLocks;using(var s=new Scope(this,m.Path,null)){var c=ResolveUserComponent(m,s.Doc,componentId);if(c.IsFixed())throw new CadFault("MOTION_COMPONENT_FIXED","指定运动零件已固定。");var face=MateFace(m,s.Doc,entityId);if(((IComponent2)((IEntity)face).GetComponent()).Name2!=c.Name2)throw new CadFault("MOTION_REFERENCE_COMPONENT_MISMATCH","运动参考须属于指定零件。");var geometry=MateGeometry(s.Doc,face);if((string)geometry["kind"]!=(kind=="rotary"?"cylindrical_axis":"planar_normal"))throw new CadFault("MOTION_REFERENCE_TYPE_MISMATCH","旋转选圆柱面，直线选法向与目标方向一致的平面。");axis=(double[])geometry["axis_global"];directLocks=DirectRotationLocks(s.Doc,c.Name2);}
        string reportPath=Path.Combine(Root,"runs",runId,"motion-validation.json");Dictionary<string,object> result;
        try {
            RunUserStudy(id,study,duration,fps,runId);var r=runs[runId];if(!r.ComponentNames.ContainsKey(componentId))throw new Exception("RUN_COMPONENT_NOT_FOUND");
            result=MotionIntent.Evaluate(r.Poses[r.ComponentNames[componentId]],axis,kind,minimum);result["before_after_comparison"]="not_requested";
            if(baseline!=null){var before=MotionIntent.Evaluate(baseline.Poses[baseline.ComponentNames[componentId]],axis,kind,minimum);double bt=Convert.ToDouble(before["travel"]),at=Convert.ToDouble(result["travel"]);bool comparable=(string)before["assertion"]=="pass";double tolerance=Math.Max(kind=="rotary"?.1:.01,bt*.05);bool retained=comparable&&Math.Abs(bt-at)<=tolerance;result["baseline"]=new{run_id=baseline.Id,travel=bt,assertion=before["assertion"],travel_difference=Math.Abs(bt-at),tolerance=tolerance};result["before_after_comparison"]=comparable?(retained?"travel_retained":"travel_changed"):"baseline_requirement_not_met";if(!retained)result["assertion"]=comparable?"fail":"inconclusive";}
            result["restoration_status"]="restored";result["native_time_axis_verified"]=true;
            if(kind=="rotary"&&directLocks.Length>0){result["assertion"]="inconclusive";result["error_code"]="DECLARED_ROTATION_LOCK_CONFLICT";result["direct_fixed_component_rotation_locks"]=directLocks;result["claim"]="requested_rotation_conflicts_with_native_lock_no_preservation_conclusion";}
        }catch(Exception failure){if(LastOperationRestoration=="unknown")throw;result=new Dictionary<string,object>{{"assertion","inconclusive"},{"error_code",HistoryErrorCode(failure)},{"failure",failure.Message},{"restoration_status",LastOperationRestoration},{"claim","no_motion_preservation_conclusion"}};}
        result["run_id"]=runId;result["model_id"]=id;result["study"]=study;result["component_id"]=componentId;result["plan_id"]=planId;result["checkpoint_id"]=plan==null?null:plan.CheckpointId;result["duration_s"]=duration;result["output_fps"]=fps;result["source_files_unchanged"]=UserSourcesUnchanged(m);result["report_path"]=reportPath;
        if(!(bool)result["source_files_unchanged"])result["assertion"]="inconclusive";Directory.CreateDirectory(Path.GetDirectoryName(reportPath));AtomicJson(reportPath,result);
        // Keep the distinct motion requirement conclusion available after an MCP restart.
        string solvePath=Path.Combine(Root,"runs",runId,"solve.json");if(File.Exists(solvePath)){var saved=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(solvePath));saved["motion_validation"]=result;AtomicJson(solvePath,saved);}return result;
    }
}

