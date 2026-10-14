using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    object ExistingMatePreflight(IModelDoc2 doc,IFace2 a,IFace2 b,string type,string alignment,double distance,bool lockRotation) {
        var names=new[]{((IComponent2)((IEntity)a).GetComponent()).Name2,((IComponent2)((IEntity)b).GetComponent()).Name2}.OrderBy(n=>n).ToArray();
        var references=new[]{Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(a)),Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(b))}.OrderBy(n=>n).ToArray();
        var related=new List<object>();
        foreach(var feature in BasicMateFeatures(doc).GroupBy(f=>f.GetID()).Select(g=>g.First())) {
            var mate=(IMate2)feature.GetSpecificFeature2();var entities=Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>mate.MateEntity(i)).ToArray();
            if(entities.Length!=2||!entities.Select(e=>e.ReferenceComponent as IComponent2).Where(c=>c!=null).Select(c=>c.Name2).OrderBy(n=>n).SequenceEqual(names))continue;
            var faces=entities.Select(e=>e.Reference as IFace2).ToArray();bool resolved=faces.All(f=>f!=null);
            bool exact=resolved&&faces.Select(f=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(f))).OrderBy(n=>n).SequenceEqual(references);
            var data=feature.GetDefinition() as IConcentricMateFeatureData;
            // Distance is deliberately not rejected until its native value is supported.
            bool parametersKnown=type!="distance"&&(type!="concentric"||data!=null);
            bool duplicate=exact&&mate.Type==BasicMateType(type)&&mate.Alignment==(alignment=="aligned"?0:1)&&parametersKnown&&(type!="concentric"||data.LockRotation==lockRotation);
            var evidence=new{native_feature_id=feature.GetID(),name=feature.Name,type=mate.Type,alignment=mate.Alignment,exact_face_references=exact,reference_comparison=resolved?"persistent_face_references":"unknown_unsupported_reference_kind",parameters_verified=parametersKnown,duplicate=duplicate};
            if(duplicate)throw new CadFault("MATE_EXACT_DUPLICATE","相同参考、类型、方向及已核验参数的配合已存在；未创建新配合。",evidence);
            related.Add(evidence);
        }
        return new{existing_mates_on_component_pair=related.ToArray(),possible_redundancy=related.Count>0,warnings=related.Count>0?new[]{"EXISTING_COMPONENT_PAIR_MATES_REVIEW_REQUIRED"}:new string[0],claim="exact_supported_reference_comparison_no_edge_face_equivalence_inference"};
    }
}
