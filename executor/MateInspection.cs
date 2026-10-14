using System;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public partial class Cad {
    object MateReferenceEvidence(IModelDoc2 doc,IMateEntity2 entity,UserModel registerModel=null) {
        var component=entity.ReferenceComponent as IComponent2;
        var row=new Dictionary<string,object>{{"instance",component==null?null:component.Name2},{"reference_type",entity.ReferenceType2},{"reference_type_name",Enum.GetName(typeof(swSelectType_e),entity.ReferenceType2)??"unknown_native_reference_type"},{"component_id",component==null?null:StableId("component_",Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(component)))},{"geometry_status","unsupported_reference_kind"}};
        try{var face=entity.Reference as IFace2;if(face!=null){var surface=face.GetSurface() as ISurface;if(surface!=null&&(surface.IsPlane()||surface.IsCylinder())){row["geometry"]=MateGeometry(doc,face,component);row["geometry_status"]="resolved_face";row["entity_registration_status"]="inspection_only_query_mate_references_before_use";row["reference_source"]="inspect_model_native_mate";row["entity_id"]=((Dictionary<string,object>)row["geometry"])["entity_id"];row["kind"]=((Dictionary<string,object>)row["geometry"])["kind"];row["registration_check_scope"]="not_checked_by_inspection";row["required_tool"]="list_mate_references";row["required_query"]=new{component_id=row["component_id"],kind=(string)((Dictionary<string,object>)row["geometry"])["kind"]};if(registerModel!=null){RegisterInspectedFace(registerModel,doc,face,row);}}}}
        catch(COMException e){row["geometry_status"]="native_reference_unavailable";row["native_hresult"]=e.HResult;}
        catch(CadFault e){row["geometry_status"]=e.Code;}
        return row;
    }
    object[] UserMates(IModelDoc2 doc,UserModel registerModel=null) {
        var items=new List<object>();foreach(var f in BasicMateFeatures(doc).GroupBy(v=>v.GetID()).Select(g=>g.First())) {
            var mate=(IMate2)f.GetSpecificFeature2();bool warning;int error=f.GetErrorCode2(out warning);
            items.Add(new{name=f.Name,native_feature_id=f.GetID(),native_feature_type=f.GetTypeName2(),type=mate.Type,type_name=Enum.GetName(typeof(swMateType_e),mate.Type)??"unknown_native_mate_type",alignment=mate.Alignment,alignment_name=mate.Alignment==0?"aligned":mate.Alignment==1?"anti_aligned":"other_native_alignment",error=error,warning=warning,entities=Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>MateReferenceEvidence(doc,mate.MateEntity(i),registerModel)).ToArray()});
        }return items.ToArray();
    }
}
