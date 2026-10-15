using System;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object UserDriveCandidates(string id,string componentFilter,string kind,int limit,string cursor,bool groupFaces=true,bool compact=false) {
        if(limit<1||limit>50||!new[]{"","cylindrical_axis","planar_normal"}.Contains(kind??""))throw new CadFault("INVALID_CANDIDATE_OPTIONS","limit 须在 1–50，kind 须为空、cylindrical_axis 或 planar_normal。");
        componentFilter=componentFilter??"";kind=kind??"";var m=GetUserModel(id);
        using(var s=new Scope(this,m.Path,null)) {
            string fingerprint=Fingerprint(s.Doc,s.DocumentPath)+":"+m.Revision+":group_faces="+groupFaces+":compact="+compact;var components=UserComponents(s.Doc);
            if(components.Length>500)throw new CadFault("COMPONENT_BUDGET_EXCEEDED","组件超过 500 个；请拆分装配后导入。");
            InspectUserCore(m,s.Doc);int offset=0;
            if(!string.IsNullOrEmpty(cursor)){try{var data=Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(Convert.FromBase64String(cursor)));if((string)data["model_id"]!=id||(string)data["fingerprint"]!=fingerprint||(string)data["component_filter"]!=componentFilter||(string)data["kind"]!=kind)throw new Exception();offset=Convert.ToInt32(data["offset"]);if(offset<0)throw new Exception();}catch{throw new CadFault("CANDIDATE_CURSOR_STALE","模型、配置或过滤条件已改变；请从第一页查询。");}}
            if(componentFilter!="")ResolveUserComponent(m,s.Doc,componentFilter);
            var entities=new List<Dictionary<string,object>>();var references=new Dictionary<string,string>();var excluded=new List<object>();var skipped=new List<object>();var truncated=new List<string>();
            foreach(var c in components) {
                string componentId=StableId("component_",Convert.ToBase64String((byte[])s.Doc.Extension.GetPersistReference3(c)));if(componentFilter!=""&&componentFilter!=componentId)continue;
                string reason=c.IsSuppressed()?"suppressed":c.IsFixed()?"fixed":!c.GetPathName().EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase)?"subassembly":c.IsSpeedPak?"speedpak":null;
                if(reason!=null){excluded.Add(GeometryIssue(c,componentId,reason));continue;}
                string geometryStatus;IFace2[] geometry;
                try{geometry=ComponentFaces(c,out geometryStatus);}catch(CadFault e){skipped.Add(GeometryIssue(c,componentId,e.Code,e));continue;}
                if(geometryStatus=="resolved_bodyless"){excluded.Add(GeometryIssue(c,componentId,geometryStatus));continue;}
                var faces=new List<Dictionary<string,object>>();
                foreach(var face in geometry){var surface=(ISurface)face.GetSurface();if(!surface.IsCylinder()&&!surface.IsPlane())continue;string faceKind=surface.IsCylinder()?"cylindrical_axis":"planar_normal";if(kind!=""&&faceKind!=kind)continue;
                    string reference=Convert.ToBase64String((byte[])s.Doc.Extension.GetPersistReference3(face)),entityId=StableId("entity_",reference);double[] local=surface.IsCylinder()?((double[])surface.CylinderParams).Skip(3).Take(3).ToArray():((double[])surface.PlaneParams).Take(3).ToArray(),axis=ApplyPose((double[])c.GetTotalTransform(false).ArrayData,local,false);double norm=Math.Sqrt(axis.Sum(v=>v*v));if(norm<1e-12||double.IsNaN(norm))continue;
                    var parameters=(double[])(surface.IsCylinder()?surface.CylinderParams:surface.PlaneParams);
                    var point=ApplyPose((double[])c.GetTotalTransform(false).ArrayData,surface.IsCylinder()?parameters.Take(3).ToArray():parameters.Skip(3).Take(3).ToArray(),true);
                    references[entityId]=reference;faces.Add(new Dictionary<string,object>{{"entity_id",entityId},{"component_id",componentId},{"instance",c.Name2},{"kind",faceKind},{"suggested_motor",surface.IsCylinder()?"rotary":"linear"},{"compatible_geometry_motor_types",new[]{surface.IsCylinder()?"rotary":"linear"}},{"motion_compatibility","not_checked"},{"warning_codes",new[]{"GEOMETRY_ONLY_NOT_MECHANISM_COMPATIBILITY"}},{"axis_global",axis.Select(v=>v/norm).ToArray()},{"reference_point_global_m",point},{"geometry_key",CandidateGeometry.Key(componentId,faceKind,axis,point)},{"area_m2",face.GetArea()},{"requires_user_selection",true}});
                }
                if(faces.Count>64)truncated.Add(c.Name2);entities.AddRange(faces.OrderByDescending(v=>Convert.ToDouble(v["area_m2"])).ThenBy(v=>(string)v["entity_id"],StringComparer.Ordinal).Take(64));
            }
            int rawTotal=entities.Count;
            if(groupFaces)entities=entities.GroupBy(v=>(string)v["geometry_key"]).Select(g=>{var first=g.First();first["equivalent_face_count"]=g.Count();return first;}).ToList();
            else foreach(var entity in entities)entity["equivalent_face_count"]=1;
            if(compact)foreach(var entity in entities){entity.Remove("geometry_key");entity.Remove("suggested_motor");entity.Remove("requires_user_selection");}
            if(offset>entities.Count)throw new CadFault("CANDIDATE_CURSOR_STALE","分页位置超出候选范围，请重新查询。");
            var page=entities.Skip(offset).Take(limit).ToList();var response=new Dictionary<string,object>{{"model_id",id},{"model_revision",m.Revision},{"group_faces",groupFaces},{"raw_candidate_count",rawTotal},{"total",entities.Count},{"offset",offset},{"entities",page},{"claim","geometric_candidates_only_no_automatic_design_intent_inference"}};
            response["units"]=new{reference_point_global_m="m",area_m2="m2",axis_global="unit_vector",rotary_drive_input="rpm",linear_drive_input="mm/s",mate_distance_input="mm"};response["detail_level"]=compact?"compact":"full";response["motion_compatibility"]="not_checked";response["requires_user_selection"]=true;response["excluded_components"]=excluded.Take(20).ToArray();response["excluded_component_count"]=excluded.Count;response["skipped_components"]=skipped.Take(20).ToArray();response["skipped_component_count"]=skipped.Count;response["truncated_components"]=truncated.Take(20).ToArray();response["truncated_component_count"]=truncated.Count;response["diagnostic_component_limit"]=20;response["geometry_complete"]=skipped.Count==0&&truncated.Count==0;response["suggested_motor_semantics"]="deprecated_geometry_type_alias_not_drive_recommendation";
            BoundGeometryPage(response,page,offset,entities.Count,limit,next=>Convert.ToBase64String(Encoding.UTF8.GetBytes(Json.Serialize(new{model_id=id,fingerprint=fingerprint,component_filter=componentFilter,kind=kind,offset=next}))));
            foreach(var entity in page){string key=(string)entity["entity_id"];RegisterEntity(m,key,references[key],(string)entity["component_id"],(string)entity["kind"]);}SaveUserModel(m);return response;
        }
    }
}
