using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    sealed partial class ProbeWorkingState {
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
        public static string MateIdentity(IModelDoc2 doc,IFeature[] features=null,bool includeReferences=true) {
            return Json.Serialize(ReadMateRows(doc,features,false,includeReferences));
        }
        public static string MateParameters(IModelDoc2 doc,bool includeReferenceCalculation=false) {
            return Json.Serialize(ReadMateRows(doc,null,true,includeReferenceCalculation));
        }
        static Dictionary<string,object>[] ReadMateRows(IModelDoc2 doc,IFeature[] features,bool parameters,bool includeReferences) {
            // Only this synchronous read shares COM handles and names. Nothing
            // survives a snapshot, native write, configuration change or reopen.
            var names=parameters?new Dictionary<IComponent2,string>():null;
            var rows=(features??BasicMateFeatures(doc)).Select(f=>new{feature=f,id=f.GetID()})
                .GroupBy(f=>f.id).Select(g=>g.First()).OrderBy(f=>f.id);
            return rows.Select(observed=>{
                var feature=observed.feature;var mate=(IMate2)feature.GetSpecificFeature2();int type=mate.Type;
                var lockData=type==(int)SolidWorks.Interop.swconst.swMateType_e.swMateCONCENTRIC?feature.GetDefinition() as IConcentricMateFeatureData:null;
                double? distance=null,angle=null;
                if(type==5||type==6) {
                    var dimension=mate.DisplayDimension2[0] as IDisplayDimension;
                    if(dimension==null)throw new Exception("MATE_PARAMETER_UNREADABLE");
                    double value=((IDimension)dimension.GetDimension2(0)).SystemValue;
                    if(type==5)distance=value;else angle=value;
                }
                var row=new Dictionary<string,object>{{"id",observed.id},{"type",type},{"alignment",mate.Alignment},
                    {"lock_rotation",lockData==null?(bool?)null:lockData.LockRotation},{"distance_m",distance},{"angle_rad",angle}};
                int count=parameters||includeReferences?mate.GetMateEntityCount():0;
                string[] references=includeReferences?Enumerable.Range(0,count).Select(i=>MateReferenceIdentity(doc,feature,mate,i)).ToArray():null;
                if(!parameters)row.Add("references",references);
                else {
                    row.Add("component_bindings",Enumerable.Range(0,count).Select(i=>{
                        var component=mate.MateEntity(i).ReferenceComponent as IComponent2;if(component==null)return null;
                        string name;if(!names.TryGetValue(component,out name)){name=component.Name2;names.Add(component,name);}return name;
                    }).ToArray());
                    row.Add("suppression",feature.IsSuppressed2(1,null));
                    var gear=type==10?feature.GetDefinition() as IGearMateFeatureData:null;
                    if(gear!=null)row.Add("gear_parameters",new{numerator=gear.GearRatioNumerator,denominator=gear.GearRatioDenominator,reverse=gear.Reverse});
                }
                return row;
            }).ToArray();
        }
    }
}
