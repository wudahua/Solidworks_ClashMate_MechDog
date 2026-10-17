using System;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object UserDriveCandidates(string id,string componentFilter,string kind,int limit,string cursor,bool groupFaces=true,bool compact=false,int faceOffset=0) {
        if(limit<1||limit>50||!new[]{"","cylindrical_axis","planar_normal"}.Contains(kind??""))throw new CadFault("INVALID_CANDIDATE_OPTIONS","limit 须在 1–50，kind 须为空、cylindrical_axis 或 planar_normal。");
        if(faceOffset<0||(faceOffset>0&&string.IsNullOrEmpty(componentFilter)))throw new CadFault("INVALID_FACE_OFFSET","非零face_offset必须限定component_id。");
        var queryTiming=new OperationTiming();queryTiming.Start("model_manifest");componentFilter=componentFilter??"";kind=kind??"";var m=GetUserModel(id);queryTiming.Start("open_scope");
        using(var s=new Scope(this,m.Path,null)) {
            queryTiming.Start("input_fingerprint");string fingerprint=Fingerprint(s.Doc,s.DocumentPath)+":"+m.Revision+":group_faces="+groupFaces+":compact="+compact+":face_offset="+faceOffset;var components=UserComponents(s.Doc);
            if(components.Length>500)throw new CadFault("COMPONENT_BUDGET_EXCEEDED","组件超过 500 个；请拆分装配后导入。");
            queryTiming.Start("component_inventory");InspectUserCore(m,s.Doc);int offset=0;string requestedScanIdentity=null;
            if(!string.IsNullOrEmpty(cursor)){try{var data=Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(Convert.FromBase64String(cursor)));if((string)data["model_id"]!=id||(string)data["fingerprint"]!=fingerprint||(string)data["component_filter"]!=componentFilter||(string)data["kind"]!=kind)throw new Exception();offset=Convert.ToInt32(data["offset"]);requestedScanIdentity=data.ContainsKey("scan_identity")?(string)data["scan_identity"]:null;if(offset<0)throw new Exception();}catch{throw new CadFault("CANDIDATE_CURSOR_STALE","模型、配置或过滤条件已改变；请从第一页查询。");}}
            if(componentFilter!="")ResolveUserComponent(m,s.Doc,componentFilter);
            queryTiming.Start("candidate_geometry");var entities=new List<Dictionary<string,object>>();var references=new Dictionary<string,string>();var excluded=new List<object>();var skipped=new List<object>();var truncated=new List<string>();var geometryBudget=NewGeometryBudget();var nextQueries=new List<object>();
            foreach(var c in components) {
                string componentId=StableId("component_",Convert.ToBase64String((byte[])s.Doc.Extension.GetPersistReference3(c)));if(componentFilter!=""&&componentFilter!=componentId)continue;
                if(!geometryBudget.Continue()){nextQueries.Add(new{component_id=componentId,face_offset=0});continue;}
                string reason=c.IsSuppressed()?"suppressed":c.IsFixed()?"fixed":!c.GetPathName().EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase)?"subassembly":c.IsSpeedPak?"speedpak":null;
                if(reason!=null){excluded.Add(GeometryIssue(c,componentId,reason));continue;}
                string geometryStatus;IFace2[] geometry;
                try{geometry=ComponentFaces(c,out geometryStatus);}catch(CadFault e){skipped.Add(GeometryIssue(c,componentId,e.Code,e));continue;}
                if(geometryStatus=="resolved_bodyless"){excluded.Add(GeometryIssue(c,componentId,geometryStatus));continue;}
                var faces=new List<Dictionary<string,object>>();var componentPose=(double[])c.GetTotalTransform(false).ArrayData;string componentInstance=c.Name2;
                if(faceOffset>geometry.Length)throw new CadFault("FACE_OFFSET_OUT_OF_RANGE","face_offset超出原生面列表，请从0重查。");
                for(int faceIndex=faceOffset;faceIndex<geometry.Length;faceIndex++){if(!geometryBudget.Continue()||faces.Count>=64){nextQueries.Add(new{component_id=componentId,face_offset=faceIndex});break;}var face=geometry[faceIndex];geometryBudget.ReadFaces++;var surface=(ISurface)face.GetSurface();if(!surface.IsCylinder()&&!surface.IsPlane())continue;string faceKind=surface.IsCylinder()?"cylindrical_axis":"planar_normal";if(kind!=""&&faceKind!=kind)continue;
                    string reference=Convert.ToBase64String((byte[])s.Doc.Extension.GetPersistReference3(face)),entityId=StableId("entity_",reference);double[] local=surface.IsCylinder()?((double[])surface.CylinderParams).Skip(3).Take(3).ToArray():((double[])surface.PlaneParams).Take(3).ToArray(),axis=ApplyPose(componentPose,local,false);double norm=Math.Sqrt(axis.Sum(v=>v*v));if(norm<1e-12||double.IsNaN(norm))continue;
                    var parameters=(double[])(surface.IsCylinder()?surface.CylinderParams:surface.PlaneParams);
                    var point=ApplyPose(componentPose,surface.IsCylinder()?parameters.Take(3).ToArray():parameters.Skip(3).Take(3).ToArray(),true);
                    references[entityId]=reference;faces.Add(new Dictionary<string,object>{{"entity_id",entityId},{"component_id",componentId},{"instance",componentInstance},{"kind",faceKind},{"suggested_motor",surface.IsCylinder()?"rotary":"linear"},{"compatible_geometry_motor_types",new[]{surface.IsCylinder()?"rotary":"linear"}},{"motion_compatibility","not_checked"},{"warning_codes",new[]{"GEOMETRY_ONLY_NOT_MECHANISM_COMPATIBILITY"}},{"axis_global",axis.Select(v=>v/norm).ToArray()},{"reference_point_global_m",point},{"geometry_key",CandidateGeometry.Key(componentId,faceKind,axis,point)},{"area_m2",face.GetArea()},{"requires_user_selection",true}});
                }
                if(faces.Count>64)truncated.Add(c.Name2);entities.AddRange(faces.OrderByDescending(v=>Convert.ToDouble(v["area_m2"])).ThenBy(v=>(string)v["entity_id"],StringComparer.Ordinal).Take(64));
            }
            geometryBudget.Finish();queryTiming.Start("mate_context");var mateContextScan=AnnotateCandidateMates(s.Doc,entities);int rawTotal=entities.Count;
            foreach(var entity in entities){entity["geometry_key_semantics"]="axis_or_plane_equivalence_not_face_identity";entity["geometrically_equivalent_observed_face_count"]=entities.Count(e=>(string)e["geometry_key"]==(string)entity["geometry_key"]);entity["deduplication_key"]="entity_id";entity["registration_lifetime"]="shared_face_namespace_invalidated_by_checkpoint_restore_or_reference_state_change_requery";}
            if(groupFaces)entities=entities.GroupBy(v=>(string)v["geometry_key"]).Select(g=>{var first=g.First();first["equivalent_face_count"]=g.Count();first["grouped_face_ids"]=g.Select(e=>(string)e["entity_id"]).ToArray();first["grouping_scope"]="current_observed_subset_only";return first;}).ToList();
            else foreach(var entity in entities){entity["equivalent_face_count"]=1;entity["equivalent_face_count_semantics"]="represented_face_count_ungrouped_not_equivalence_class_size";}
            if(compact)foreach(var entity in entities){entity.Remove("geometry_key");entity.Remove("suggested_motor");entity.Remove("requires_user_selection");}
            string scanIdentity=StableId("scan_",Json.Serialize(entities.Select(e=>new{id=e["entity_id"],axis=e["axis_global"],point=e["reference_point_global_m"]}).ToArray()));if(!string.IsNullOrEmpty(cursor)&&requestedScanIdentity!=scanIdentity)throw new CadFault("CANDIDATE_CURSOR_STALE","本次预算内扫描集合发生变化；请从第一页或geometry_scan.next_queries指定组件继续。");
            if(offset>entities.Count)throw new CadFault("CANDIDATE_CURSOR_STALE","分页位置超出候选范围，请重新查询。");
            var page=entities.Skip(offset).Take(limit).ToList();var response=new Dictionary<string,object>{{"model_id",id},{"model_revision",m.Revision},{"group_faces",groupFaces},{"raw_candidate_count",rawTotal},{"total",entities.Count},{"offset",offset},{"entities",page},{"claim","geometric_candidates_only_no_automatic_design_intent_inference"}};
            response["units"]=new{reference_point_global_m="m",area_m2="m2",axis_global="unit_vector",rotary_drive_input="rpm",linear_drive_input="mm/s",mate_distance_input="mm"};response["detail_level"]=compact?"compact":"full";response["motion_compatibility"]="not_checked";response["requires_user_selection"]=true;response["excluded_components"]=excluded.Take(20).ToArray();response["excluded_component_count"]=excluded.Count;response["skipped_components"]=skipped.Take(20).ToArray();response["skipped_component_count"]=skipped.Count;response["truncated_components"]=truncated.Take(20).ToArray();response["truncated_component_count"]=truncated.Count;response["diagnostic_component_limit"]=20;response["geometry_complete"]=skipped.Count==0&&truncated.Count==0&&nextQueries.Count==0;response["suggested_motor_semantics"]="deprecated_geometry_type_alias_not_drive_recommendation";
            queryTiming.Finish();response["host_timings"]=queryTiming.Export();response["timing_scope"]="query_body_through_context_excludes_registration_disposal_transport";response["fixed_state_source"]="IComponent2.IsFixed";response["mate_context_scan"]=mateContextScan;response["geometry_scan"]=geometryBudget.Export(nextQueries.Take(5).ToArray(),nextQueries.Count,!string.IsNullOrEmpty(componentFilter));response["face_offset"]=faceOffset;response["total_scope"]=nextQueries.Count>0?"observed_subset_not_full_model":"observed_full_scan";response["warning_codes"]=QueryWarningCodes(geometryBudget.Exhausted,mateContextScan);response["query_completion_status"]=(bool)response["geometry_complete"]?"complete_supported_geometry":"partial_pending_or_unresolved";response["absence_of_kind_proven"]=false;response["client_next_action"]=nextQueries.Count>0?"read_pages_then_continue_components_never_infer_missing_geometry":"read_pages_and_review_skipped_unresolved_no_automatic_retry";
            GeometryQueryScope.Apply(response,componentFilter,components.Length,string.IsNullOrEmpty(componentFilter)?components.Length:1,skipped.Count==0&&truncated.Count==0&&nextQueries.Count==0,nextQueries.Count);
            BoundGeometryPage(response,page,offset,entities.Count,limit,next=>Convert.ToBase64String(Encoding.UTF8.GetBytes(Json.Serialize(new{model_id=id,fingerprint=fingerprint,component_filter=componentFilter,kind=kind,scan_identity=scanIdentity,offset=next}))));
            foreach(var entity in page){string key=(string)entity["entity_id"];RegisterEntity(m,key,references[key],(string)entity["component_id"],(string)entity["kind"]);}SaveUserModel(m);return response;
        }
    }
}
