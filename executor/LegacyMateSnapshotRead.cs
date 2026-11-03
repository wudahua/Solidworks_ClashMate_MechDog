// Exact alpha38 read-only reference implementation. Benchmark-only caller is fault-test gated.
using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
public partial class Cad {
    sealed class LegacyMateSnapshotReader {
        static string MateReferenceIdentity(IModelDoc2 doc,IFeature feature,IMate2 mate,int index) {
            var entity=mate.MateEntity(index);object reference=entity==null?null:entity.Reference;
            byte[] persistent=reference==null?null:doc.Extension.GetPersistReference3(reference) as byte[];
            if(persistent==null||persistent.Length==0) {
                var component=entity==null?null:entity.ReferenceComponent as IComponent2;
                throw new CadFault("CONNECTION_REFERENCE_INVALID","现有配合参考身份不可读取，未生成完整写入签名；AI读取具体参考及配合健康，不自动替换或忽略。",new {
                    reason="native_mate_reference_identity_unavailable",mate_name=feature.Name,native_feature_id=feature.GetID(),
                    native_mate_type=mate.Type,reference_index=index,native_reference_type=entity==null?(int?)null:entity.ReferenceType2,
                    component_instance=component==null?null:component.Name2,reference_object_available=reference!=null,
                    persistent_identity_available=false,signature_complete=false,write_dispatched=false,
                    automatic_reference_substitution=false,unavailable_reference_does_not_prove_broken_mate=true});
            }
            return Convert.ToBase64String(persistent);
        }
        public static string MateIdentity(IModelDoc2 doc,IFeature[] fs=null,bool includeReferences=true){var extension=doc.Extension;return Json.Serialize((fs??BasicMateFeatures(doc)).Select(f=>new{feature=f,id=f.GetID()}).GroupBy(f=>f.id).Select(g=>g.First()).OrderBy(f=>f.id).Select(row=>{var f=row.feature;var m=(IMate2)f.GetSpecificFeature2();var lockData=m.Type==(int)SolidWorks.Interop.swconst.swMateType_e.swMateCONCENTRIC?f.GetDefinition() as IConcentricMateFeatureData:null;double? distance=null,angle=null;if(m.Type==5||m.Type==6){var d=m.DisplayDimension2[0] as IDisplayDimension;if(d==null)throw new Exception("MATE_PARAMETER_UNREADABLE");double value=((IDimension)d.GetDimension2(0)).SystemValue;if(m.Type==5)distance=value;else angle=value;}return new{id=row.id,type=m.Type,alignment=m.Alignment,lock_rotation=lockData==null?(bool?)null:lockData.LockRotation,distance_m=distance,angle_rad=angle,references=includeReferences?Enumerable.Range(0,m.GetMateEntityCount()).Select(i=>MateReferenceIdentity(doc,f,m,i)).ToArray():null};}).ToArray());}
    }
    string LegacyImportMateParameters(IModelDoc2 doc,bool includeReferenceCalculation=false) {
        var features=BasicMateFeatures(doc).GroupBy(f=>f.GetID()).ToDictionary(g=>g.Key,g=>g.First());
        var rows=Json.Deserialize<List<Dictionary<string,object>>>(LegacyMateSnapshotReader.MateIdentity(doc,features.Values.ToArray(),includeReferenceCalculation));
        foreach(var row in rows) {
            row.Remove("references");var feature=features[Convert.ToInt32(row["id"])];var mate=(IMate2)feature.GetSpecificFeature2();
            row["component_bindings"]=Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>{
                var c=mate.MateEntity(i).ReferenceComponent as IComponent2;return c==null?null:c.Name2;}).ToArray();
            row["suppression"]=feature.IsSuppressed2(1,null);
            var gear=mate.Type==10?feature.GetDefinition() as IGearMateFeatureData:null;
            if(gear!=null)row["gear_parameters"]=new{numerator=gear.GearRatioNumerator,denominator=gear.GearRatioDenominator,reverse=gear.Reverse};
        }
        return Json.Serialize(rows);
    }
}
