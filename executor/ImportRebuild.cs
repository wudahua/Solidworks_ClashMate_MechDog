using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    object PrepareImportedRebuild(UserModel model,IModelDoc2 doc,out bool rebuiltParts) {
        using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)){
        rebuiltParts=false;var importedPoses=Transforms(doc);var importedFixed=UserComponents(doc).ToDictionary(c=>c.Name2,c=>c.IsFixed());var importedStudies=StudyStates(doc);
        bool ordinary=doc.EditRebuild3();var errors=NativeFeatureDiagnostics(doc);
        var ordinaryDelta=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(PoseDifference(importedPoses,Transforms(doc))));
        if(Convert.ToDouble(ordinaryDelta["maximum_transform_delta"])>1e-7||UserComponents(doc).Any(c=>!importedFixed.ContainsKey(c.Name2)||importedFixed[c.Name2]!=c.IsFixed()))throw new CadFault("MODEL_PREFLIGHT_FAILED","普通重建改变了导入姿态或固定状态，未保存该变化。",new{stage="gear_import_ordinary_rebuild_pose_guard",difference=ordinaryDelta});
        VerifyStudyStates(doc,importedStudies);
        if(ordinary&&errors.Length==0)return new{attempted=false,reason="ordinary_rebuild_passed",native_rebuild_succeeded=true};
        var loaded=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().ToArray();
        if(loaded.Any(d=>!model.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)))
            throw new CadFault("MODEL_PREFLIGHT_FAILED","完整重建前发现非副本文档，未执行重建。",new{stage="import_full_rebuild_isolation",automatic_external_save=false});
        Progress(activeJobId,"import_rebuild_snapshot",0,0,null);var poses=importedPoses;var fixedStates=importedFixed;
        var features=BasicMateFeatures(doc);string references=ProbeWorkingState.MateIdentity(doc,features);string mates=ImportMateParameters(doc);
        var studies=importedStudies;
        string evidence=Path.Combine(model.Directory,"rebuild-preparation.json");
        AtomicJson(evidence,new{stage="before_force_rebuild",attempted=true,before_errors=errors,ordinary_rebuild_succeeded=ordinary,
            source_files_written=false,mate_or_fixed_state_changes_authorized=false});
        Progress(activeJobId,"import_full_rebuild",0,0,null);
        bool rebuilt=doc.ForceRebuild3(false);var after=NativeFeatureDiagnostics(doc);
        var difference=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(PoseDifference(poses,Transforms(doc))));
        var current=UserComponents(doc).ToDictionary(c=>c.Name2,c=>c.IsFixed());
        bool sameFixed=fixedStates.Count==current.Count&&fixedStates.All(p=>current.ContainsKey(p.Key)&&current[p.Key]==p.Value);
        bool sameMates=mates==ImportMateParameters(doc);bool sameReferences=references==ProbeWorkingState.MateIdentity(doc);
        VerifyStudyStates(doc,studies);VerifyUserSources(model);
        bool unchanged=sameFixed&&sameMates&&Convert.ToDouble(difference["maximum_transform_delta"])<=1e-7;
        var result=new{attempted=true,stage="after_force_rebuild",ordinary_rebuild_succeeded=ordinary,native_rebuild_succeeded=rebuilt,
            before_errors=errors,after_errors=after,fixed_states_unchanged=sameFixed,mate_parameters_and_component_bindings_unchanged=sameMates,persistent_reference_identity_unchanged=sameReferences,
            study_states_unchanged=true,pose_difference=difference,source_files_unchanged=true,
            automatic_fixed_or_mate_changes=false,verified=rebuilt&&after.Length==0&&unchanged,evidence_path=evidence};
        AtomicJson(evidence,result);
        if(!unchanged)throw new CadFault("MODEL_PREFLIGHT_FAILED","完整重建改变了组件姿态或约束，未保存该变化，也未继续配合规划。",result);
        // A failed force rebuild remains a preflight blocker; never repeat it.
        rebuiltParts=rebuilt&&after.Length==0;
        return result;
        }
    }
}
