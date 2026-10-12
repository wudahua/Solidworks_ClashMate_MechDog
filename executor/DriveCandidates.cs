using System;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object UserDriveCandidates(string id,string componentFilter,string kind,int limit,string cursor) {
        if(limit<1||limit>50||!new[]{"","cylindrical_axis","planar_normal"}.Contains(kind??""))throw new CadFault("INVALID_CANDIDATE_OPTIONS","limit 须在 1–50，kind 须为空、cylindrical_axis 或 planar_normal。");
        componentFilter=componentFilter??"";kind=kind??"";var m=GetUserModel(id);
        using(var s=new Scope(this,m.Path,null)) {
            string fingerprint=Fingerprint(s.Doc)+":"+m.Revision;var components=UserComponents(s.Doc);
            if(components.Length>500)throw new CadFault("COMPONENT_BUDGET_EXCEEDED","组件超过 500 个；请拆分装配后导入。");
            InspectUserCore(m,s.Doc);int offset=0;
            if(!string.IsNullOrEmpty(cursor)){try{var data=Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(Convert.FromBase64String(cursor)));if((string)data["model_id"]!=id||(string)data["fingerprint"]!=fingerprint||(string)data["component_filter"]!=componentFilter||(string)data["kind"]!=kind)throw new Exception();offset=Convert.ToInt32(data["offset"]);if(offset<0)throw new Exception();}catch{throw new CadFault("CANDIDATE_CURSOR_STALE","模型、配置或过滤条件已改变；请从第一页查询。");}}
            if(componentFilter!="")ResolveUserComponent(m,s.Doc,componentFilter);
            var entities=new List<Dictionary<string,object>>();var references=new Dictionary<string,string>();
            foreach(var c in components.Where(c=>!c.IsSuppressed()&&!c.IsFixed()&&c.GetPathName().EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase))) {
                string componentId=StableId("component_",Convert.ToBase64String((byte[])s.Doc.Extension.GetPersistReference3(c)));if(componentFilter!=""&&componentFilter!=componentId)continue;
                var faces=new List<Dictionary<string,object>>();
                foreach(var face in Faces(c)){var surface=(ISurface)face.GetSurface();if(!surface.IsCylinder()&&!surface.IsPlane())continue;string faceKind=surface.IsCylinder()?"cylindrical_axis":"planar_normal";if(kind!=""&&faceKind!=kind)continue;
                    string reference=Convert.ToBase64String((byte[])s.Doc.Extension.GetPersistReference3(face)),entityId=StableId("entity_",reference);double[] local=surface.IsCylinder()?((double[])surface.CylinderParams).Skip(3).Take(3).ToArray():((double[])surface.PlaneParams).Take(3).ToArray(),axis=ApplyPose((double[])c.GetTotalTransform(false).ArrayData,local,false);double norm=Math.Sqrt(axis.Sum(v=>v*v));if(norm<1e-12||double.IsNaN(norm))continue;
                    references[entityId]=reference;faces.Add(new Dictionary<string,object>{{"entity_id",entityId},{"component_id",componentId},{"instance",c.Name2},{"kind",faceKind},{"suggested_motor",surface.IsCylinder()?"rotary":"linear"},{"axis_global",axis.Select(v=>v/norm).ToArray()},{"area_m2",face.GetArea()},{"requires_user_selection",true}});
                }
                entities.AddRange(faces.OrderByDescending(v=>Convert.ToDouble(v["area_m2"])).ThenBy(v=>(string)v["entity_id"],StringComparer.Ordinal).Take(64));
            }
            if(offset>entities.Count)throw new CadFault("CANDIDATE_CURSOR_STALE","分页位置超出候选范围，请重新查询。");
            var page=entities.Skip(offset).Take(limit).ToList();var response=new Dictionary<string,object>{{"model_id",id},{"model_revision",m.Revision},{"total",entities.Count},{"offset",offset},{"entities",page},{"claim","geometric_candidates_only_no_automatic_design_intent_inference"}};
            while(page.Count>1&&Encoding.UTF8.GetByteCount(Json.Serialize(response))>16000)page.RemoveAt(page.Count-1);
            response["returned"]=page.Count;response["next_cursor"]=offset+page.Count<entities.Count?Convert.ToBase64String(Encoding.UTF8.GetBytes(Json.Serialize(new{model_id=id,fingerprint=fingerprint,component_filter=componentFilter,kind=kind,offset=offset+page.Count}))):null;
            foreach(var entity in page){string key=(string)entity["entity_id"];m.Entities[key]=references[key];}SaveUserModel(m);return response;
        }
    }
}
