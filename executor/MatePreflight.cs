using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    object ExistingMatePreflight(IModelDoc2 doc,IFace2 a,IFace2 b,string type,string alignment,double distance,bool lockRotation) {
        var names=new[]{((IComponent2)((IEntity)a).GetComponent()).Name2,((IComponent2)((IEntity)b).GetComponent()).Name2}.OrderBy(n=>n).ToArray();
        var references=new[]{Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(a)),Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(b))}.OrderBy(n=>n).ToArray();
        var related=new List<object>();bool oppositeAlignment=false;
        foreach(var feature in BasicMateFeatures(doc).GroupBy(f=>f.GetID()).Select(g=>g.First())) {
            var mate=(IMate2)feature.GetSpecificFeature2();var entities=Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>mate.MateEntity(i)).ToArray();
            if(entities.Length!=2||!entities.Select(e=>e.ReferenceComponent as IComponent2).Where(c=>c!=null).Select(c=>c.Name2).OrderBy(n=>n).SequenceEqual(names))continue;
            var faces=entities.Select(e=>e.Reference as IFace2).ToArray();bool resolved=faces.All(f=>f!=null);
            bool exact=resolved&&faces.Select(f=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(f))).OrderBy(n=>n).SequenceEqual(references);
            var data=feature.GetDefinition() as IConcentricMateFeatureData;
            // Distance is deliberately not rejected until its native value is supported.
            bool parametersKnown=mate.Type!=BasicMateType("distance")&&(mate.Type!=BasicMateType("concentric")||data!=null);
            if(exact&&mate.Type==BasicMateType(type)&&mate.Alignment!=(alignment=="aligned"?0:1))oppositeAlignment=true;
            bool duplicate=exact&&mate.Type==BasicMateType(type)&&mate.Alignment==(alignment=="aligned"?0:1)&&parametersKnown&&(type!="concentric"||data.LockRotation==lockRotation);
            var evidence=new{native_feature_id=feature.GetID(),name=feature.Name,type=mate.Type,alignment=mate.Alignment,alignment_name=mate.Alignment==0?"aligned":mate.Alignment==1?"anti_aligned":"other_native_alignment",same_faces_different_alignment=exact&&mate.Type==BasicMateType(type)&&mate.Alignment!=(alignment=="aligned"?0:1),exact_face_references=exact,reference_comparison=resolved?"persistent_face_references":"unknown_unsupported_reference_kind",parameters_verified=parametersKnown,duplicate=duplicate};
            if(duplicate)throw new CadFault("MATE_EXACT_DUPLICATE","相同参考、类型、方向及已核验参数的配合已存在；未创建新配合。",evidence);
            related.Add(evidence);
        }
        return new{existing_mates_on_component_pair=related.ToArray(),possible_redundancy=related.Count>0,overdefinition_risk=related.Count>0?"elevated_review_required":"unknown_not_excluded",risk_basis="existing_direct_component_pair_constraints_not_a_native_overdefinition_prediction",review_guidance="review_existing_mates_before_confirming; descriptive_preview_does_not_predict_native_solver_result; do_not_reuse_success_from_another_model_state",possible_redundancy_scope="direct_component_pair_observation_not_full_constraint_graph",possible_redundancy_false_means="no_direct_pair_mates_observed_not_a_nonredundancy_proof",constraint_interaction_status=related.Count>0?"review_required_kind_unknown":"not_proven",redundancy_or_overconstraint_predicted=(bool?)null,constraint_prediction=new{status="not_computed",redundant=(bool?)null,overconstrained=(bool?)null,reason="native_constraint_solve_not_performed_in_descriptive_preview"},warnings=oppositeAlignment?new[]{"EXISTING_COMPONENT_PAIR_MATES_REVIEW_REQUIRED","EXACT_FACES_SAME_TYPE_DIFFERENT_ALIGNMENT"}:related.Count>0?new[]{"EXISTING_COMPONENT_PAIR_MATES_REVIEW_REQUIRED"}:new string[0],claim="exact_supported_reference_comparison_no_edge_face_equivalence_inference"};
    }
}
