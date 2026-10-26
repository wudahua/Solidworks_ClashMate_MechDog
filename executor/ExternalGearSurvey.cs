using System;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

// Observations only. Pattern instance counts are NOT automatically tooth counts.
public partial class Cad {
    object EGDesignEvidence(IModelDoc2 part,string configuration) {
        var properties=new List<object>();var patterns=new List<object>();var features=new List<object>();
        var issues=new List<object>();int count=0;
        foreach(string scope in new[]{"",configuration}.Distinct()) {
            var manager=part.Extension.CustomPropertyManager[scope];var names=manager.GetNames() as string[]??new string[0];
            if(names.Length>64)issues.Add(new{code="PROPERTY_LIMIT",total=names.Length});
            foreach(string name in names.Take(64)) {
                string raw,resolved;bool evaluated,linked;int status=manager.Get6(name,true,out raw,out resolved,out evaluated,out linked);
                properties.Add(new{scope=scope,name=name,raw=(raw??"").Substring(0,Math.Min(256,(raw??"").Length)),resolved=(resolved??"").Substring(0,Math.Min(256,(resolved??"").Length)),was_resolved=evaluated,native_status=status,cached_only=true});
            }
        }
        var feature=part.FirstFeature() as IFeature;
        while(feature!=null&&count++<256) {
            string type=feature.GetTypeName2();features.Add(new{name=feature.Name,type=type});
            if(type=="CirPattern") {
                try {
                    var definition=feature.GetDefinition() as ICircularPatternFeatureData;
                    if(definition!=null)patterns.Add(new{feature=feature.Name,total_instances=definition.TotalInstances,
                        equal_spacing=definition.EqualSpacing,spacing_rad=definition.Spacing,interpretation="circular_pattern_not_proven_tooth_count"});
                }catch(COMException error){issues.Add(new{code="PATTERN_UNAVAILABLE",feature=feature.Name,hresult=error.HResult});}
            }
            feature=feature.GetNextFeature() as IFeature;
        }
        if(feature!=null)issues.Add(new{code="FEATURE_LIMIT",limit=256});
        return new{properties=properties,patterns=patterns,features=features,issues=issues,configuration_observed=part.ConfigurationManager.ActiveConfiguration.Name,requested_configuration=configuration};
    }
    public object SurveyExternalGearPair(string id,bool includeCompletionReferences=false) {
        var m=GetUserModel(id);var clock=Stopwatch.StartNew();
        using(var scope=new Scope(this,m.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
            var doc=scope.Doc;var cs=UserComponents(doc);
            if(cs.Length>128)throw new CadFault("EXTERNAL_GEAR_SCOPE_UNSUPPORTED","首版两轴推荐限128个顶层零件。",new{components=cs.Length});
            var rows=new List<object>();var design=new Dictionary<string,object>();var skipped=new List<object>();
            var completionTemplates=new Dictionary<string,List<CompletionPlaneTemplate>>();
            string signature=MateSignature(m,doc);
            foreach(var c in cs) {
                var part=c.GetModelDoc2() as IModelDoc2;
                if(c.IsSuppressed()||c.IsSpeedPak||part==null||part.GetType()!=1||!m.Files.Contains(c.GetPathName(),StringComparer.OrdinalIgnoreCase)) {
                    skipped.Add(new{instance=c.Name2,reason="unresolved_suppressed_or_not_owned_top_level_part"});continue;
                }
                string key=c.GetPathName()+"|"+c.ReferencedConfiguration;
                if(!design.ContainsKey(key))design[key]=EGDesignEvidence(part,c.ReferencedConfiguration);
                string faceStatus;var faces=ComponentFaces(c,out faceStatus);var cylinders=faces.Where(f=>((ISurface)f.GetSurface()).IsCylinder()).ToArray();
                var selected=cylinders.OrderByDescending(f=>f.GetArea()).Take(24).Select(f=>{
                    var shape=MateGeometry(doc,f,c);shape["area_m2"]=f.GetArea();shape["native_reference"]=GTReference(doc,f);return shape;
                }).ToArray();
                rows.Add(new{component_id=GTComponentId(doc,c),instance=c.Name2,fixed_component=c.IsFixed(),constraint_state=ComponentConstraintObservation(c),
                    transform=(double[])c.GetTotalTransform(false).ArrayData,box=c.GetBox(false,false),
                    face_count=faces.Length,cylindrical_face_count=cylinders.Length,cylinders=selected,
                    cylindrical_faces_truncated=cylinders.Length>selected.Length,geometry_status=faceStatus,design_key=key,
                    completion_planes=includeCompletionReferences?CompletionPlaneReferences(doc,c,completionTemplates):new object[0],
                    source_configuration_matches=part.ConfigurationManager.ActiveConfiguration.Name==c.ReferencedConfiguration});
            }
            var mates=Json.Deserialize<List<Dictionary<string,object>>>(Json.Serialize(UserMates(doc)));
            foreach(var row in mates)row["suppressed"]=EGSuppressed(EGFeature(doc,Convert.ToInt32(row["native_feature_id"])));
            foreach(var row in mates.Where(v=>Convert.ToInt32(v["type"])==10&&!(bool)v["suppressed"])) {
                var feature=BasicMateFeatures(doc).Single(f=>f.GetID()==Convert.ToInt32(row["native_feature_id"]));
                var data=feature.GetDefinition() as IGearMateFeatureData;
                if(data!=null) {
                    bool adapter=Sw.RevisionNumber()=="34.0.0";
                    row["gear_ratio"]=new{numerator=adapter?data.GearRatioDenominator:data.GearRatioNumerator,denominator=adapter?data.GearRatioNumerator:data.GearRatioDenominator,
                        native_numerator=data.GearRatioNumerator,native_denominator=data.GearRatioDenominator,native_reverse=data.Reverse,
                        readback_adapter=adapter?"SW34_reciprocal_definition_getters_pose_calibrated":"unvalidated_native_definition"};
                }
            }
            var structuralRelations=AssemblyStructureObservation(doc);
            bool unchanged=signature==MateSignature(m,doc);
            if(!unchanged)throw new CadFault("GEAR_PLAN_STALE","只读推荐期间初态变化，未写入。",new{write_dispatched=false});
            return new{model_id=id,model_revision=m.Revision,reference_state_signature=signature,components=rows,
                design_evidence=design,mates=mates,structural_relations=structuralRelations,skipped=skipped,inventory_complete=skipped.Count==0,
                elapsed_ms=clock.Elapsed.TotalMilliseconds,write_dispatched=false,contact_or_tooth_geometry_validated=false,
                recommendation_scope="two_parallel_axis_external_gear_pair_evidence_not_arbitrary_transmission"};
        }
    }
}
