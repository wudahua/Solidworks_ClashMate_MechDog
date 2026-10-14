using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    void RegisterInspectedFace(UserModel model,IModelDoc2 doc,IFace2 face,Dictionary<string,object> row) {
        var owner=((IEntity)face).GetComponent() as IComponent2;
        var top=((object[])((IAssemblyDoc)doc).GetComponents(true)).Cast<IComponent2>();
        if(owner==null||!top.Any(c=>c.Name2==owner.Name2)||owner.IsSuppressed()||owner.IsSpeedPak||owner.GetModelDoc2()==null||!owner.GetPathName().EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase)||!model.Files.Contains(owner.GetPathName(),StringComparer.OrdinalIgnoreCase)){
            row["entity_registration_status"]="not_registered_unsupported_component_scope";return;
        }
        string reference=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(face));int error;
        var resolved=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(reference),out error) as IFace2;
        if(resolved==null||error!=0){row["entity_registration_status"]="not_registered_native_reference_unverified";return;}
        var actual=((IEntity)resolved).GetComponent() as IComponent2;
        if(actual==null||actual.Name2!=owner.Name2){row["entity_registration_status"]="not_registered_owner_unverified";return;}
        string id=(string)row["entity_id"];
        if(id!=StableId("entity_",reference))throw new CadFault("INSPECTION_REFERENCE_ID_MISMATCH","检查所得参考与持久引用不一致，未登记。",new{model_id=model.Id,entity_id=id});
        RegisterEntity(model,id,reference,(string)row["component_id"],(string)row["kind"]);
        row["entity_registration_status"]="registered_supported_inspected_face";row["registration_check_scope"]="native_reference_owner_model_and_top_level_scope";row["reference_source"]="inspect_model_registered_face";
    }
}
