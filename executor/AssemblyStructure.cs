using System;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

// Read-only assembly feature relationships. A pattern relationship is not
// silently turned into a rigid mate or interpreted as missing constraints.
public partial class Cad {
    object AssemblyStructureObservation(IModelDoc2 doc) {
        var clock=Stopwatch.StartNew();var features=new List<IFeature>();
        var next=doc.FirstFeature() as IFeature;
        while(next!=null&&features.Count<512){features.Add(next);next=next.GetNextFeature() as IFeature;}
        var components=new List<object>();var patterns=new List<object>();var issues=new List<object>();
        foreach(var feature in features) {
            string type=feature.GetTypeName2();
            try {
                if(type=="Reference"||type=="ReferencePattern") {
                    var c=feature.GetSpecificFeature2() as IComponent2;
                    if(c==null)continue;
                    var parents=(feature.GetParents() as object[]??new object[0]).OfType<IFeature>().Take(64).ToArray();
                    components.Add(new{component_id=GTComponentId(doc,c),instance=c.Name2,is_pattern_instance=c.IsPatternInstance(),
                        native_feature_id=feature.GetID(),native_feature_type=type,
                        parent_features=parents.Select(p=>new{native_feature_id=p.GetID(),name=p.Name,type=p.GetTypeName2()}).ToArray()});
                }
                if(type=="LocalLPattern"||type=="LocalCirPattern"||type=="DerivedLPattern"||type=="DerivedCirPattern"||type=="DerivedPattern") {
                    object rawSeeds=null;var definition=feature.GetDefinition();
                    if(definition is ILocalLinearPatternFeatureData)rawSeeds=((ILocalLinearPatternFeatureData)definition).SeedComponentArray;
                    else if(definition is ILocalCircularPatternFeatureData)rawSeeds=((ILocalCircularPatternFeatureData)definition).SeedComponentArray;
                    else if(definition is IDerivedPatternFeatureData)rawSeeds=((IDerivedPatternFeatureData)definition).SeedComponentArray;
                    var seeds=new List<string>();
                    foreach(var seed in rawSeeds as object[]??new object[0]) {
                        var c=seed as IComponent2;var sf=seed as IFeature;
                        if(c==null&&sf!=null)c=sf.GetSpecificFeature2() as IComponent2;
                        if(c!=null)seeds.Add(GTComponentId(doc,c));
                    }
                    var children=(feature.GetChildren() as object[]??new object[0]).OfType<IFeature>().Take(256).ToArray();
                    patterns.Add(new{native_feature_id=feature.GetID(),name=feature.Name,type=type,suppressed=EGSuppressed(feature),
                        seed_component_ids=seeds.Distinct().ToArray(),
                        child_features=children.Select(c=>new{native_feature_id=c.GetID(),name=c.Name,type=c.GetTypeName2()}).ToArray(),
                        relationship_scope="native_pattern_dependency_not_rigid_motion_proof"});
                }
            }catch(COMException error){issues.Add(new{native_feature_id=feature.GetID(),name=feature.Name,type=type,hresult=error.HResult});}
        }
        return new{components=components,patterns=patterns,issues=issues,feature_inventory_truncated=next!=null,
            elapsed_ms=clock.Elapsed.TotalMilliseconds,write_dispatched=false,pattern_dependency_is_rigid_motion_proof=false};
    }
}
