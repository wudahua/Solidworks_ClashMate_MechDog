using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    sealed partial class ProbeWorkingState {
        public static Dictionary<string,object> NonlinearParameters(IFeature feature,IMate2 mate,int type) {
            Dictionary<string,object> result=null;
            bool limitDistance=type==5&&feature.GetTypeName2().IndexOf("limit",StringComparison.OrdinalIgnoreCase)>=0;
            // Read the actual mate's alignment. Feature-data alignment can
            // return invalid, changing integers for an existing advanced mate.
            // It is not a second mechanical setting and must not enter a guard.
            int alignment=0;
            if(type==17||limitDistance) {
                alignment=mate.Alignment;
                if(alignment<0||alignment>2)throw NonlinearUnavailable(feature,type,"native_mate_alignment");
            }
            if(type==17) {
                var data=feature.GetDefinition() as IScrewMateFeatureData;
                if(data==null)throw NonlinearUnavailable(feature,type,"screw_definition");
                double value=data.RevolutionVal;if(double.IsNaN(value)||double.IsInfinity(value)||value<=0)throw NonlinearUnavailable(feature,type,"screw_revolution_value");
                result=new Dictionary<string,object>{{"kind","screw"},{"native_revolution_type",data.RevolutionType},{"native_revolution_value",value},{"reverse",data.Reverse},{"mate_alignment",alignment},{"mate_alignment_source","IMate2.Alignment"}};
            } else if(limitDistance) {
                var data=feature.GetDefinition() as IDistanceMateFeatureData;
                if(data==null||!data.IsAdvancedMate)throw NonlinearUnavailable(feature,type,"limit_definition");
                double minimum=data.MinimumDistance,maximum=data.MaximumDistance;
                if(double.IsNaN(minimum)||double.IsInfinity(minimum)||double.IsNaN(maximum)||double.IsInfinity(maximum)||minimum>maximum)throw NonlinearUnavailable(feature,type,"limit_bounds");
                result=new Dictionary<string,object>{{"kind","limit_distance"},{"minimum_distance_m",minimum},{"maximum_distance_m",maximum},{"flip_dimension",data.FlipDimension},{"mate_alignment",alignment},{"mate_alignment_source","IMate2.Alignment"}};
            }
            return result;
        }
        static CadFault NonlinearUnavailable(IFeature feature,int type,string field) {
            return new CadFault("CONNECTION_REFERENCE_INVALID","既有非线性配合参数未完整读取，未建立可写入或联动验证签名。",new{reason="native_nonlinear_parameters_unavailable",native_feature_id=feature.GetID(),native_mate_type=type,parameter=field,write_dispatched=false,signature_complete=false});
        }
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
                var nonlinear=NonlinearParameters(feature,mate,type);
                var lockData=type==(int)SolidWorks.Interop.swconst.swMateType_e.swMateCONCENTRIC?feature.GetDefinition() as IConcentricMateFeatureData:null;
                double? distance=null,angle=null;
                if(type==5||type==6) {
                    var dimension=mate.DisplayDimension2[0] as IDisplayDimension;
                    if(dimension==null)throw new Exception("MATE_PARAMETER_UNREADABLE");
                    double value=((IDimension)dimension.GetDimension2(0)).SystemValue;
                    // The current separation of a limit mate is a pose observation,
                    // not a constant parameter. Bounds remain guarded in both modes.
                    if(type==5){if(!parameters||nonlinear==null)distance=value;}else angle=value;
                }
                int observedAlignment=nonlinear==null?mate.Alignment:Convert.ToInt32(nonlinear["mate_alignment"]);
                var row=new Dictionary<string,object>{{"id",observed.id},{"type",type},{"alignment",observedAlignment},
                    {"lock_rotation",lockData==null?(bool?)null:lockData.LockRotation},{"distance_m",distance},{"angle_rad",angle}};
                if(nonlinear!=null)row.Add("nonlinear_parameters",nonlinear);
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
