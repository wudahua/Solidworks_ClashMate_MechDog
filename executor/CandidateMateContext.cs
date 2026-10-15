using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    void AnnotateCandidateMates(IModelDoc2 doc,IEnumerable<Dictionary<string,object>> candidates) {
        var candidateRows=candidates.ToArray();var targetNames=new HashSet<string>(candidateRows.Select(r=>(string)r["instance"]));var timer=System.Diagnostics.Stopwatch.StartNew();bool truncatedScan=false;var references=new List<Dictionary<string,object>>();int unresolved=0;int scanned=0;
        foreach(var feature in BasicMateFeatures(doc)) {
            if(scanned>=256||timer.Elapsed.TotalSeconds>10){truncatedScan=true;break;}scanned++;try {
                var mate=(IMate2)feature.GetSpecificFeature2();IConcentricMateFeatureData lockData=null;bool definitionRead=false;
                for(int i=0;i<mate.GetMateEntityCount();i++) {
                    var entity=mate.MateEntity(i);var face=entity.Reference as IFace2;var component=entity.ReferenceComponent as IComponent2;
                    if(component!=null&&!targetNames.Contains(component.Name2))continue;if(face==null||component==null){unresolved++;continue;}if(!definitionRead){lockData=feature.GetDefinition() as IConcentricMateFeatureData;definitionRead=true;}
                    var geometry=MateGeometry(doc,face,component);var axis=(double[])geometry["axis_global"];var point=(double[])geometry["reference_point_global_m"];
                    references.Add(new Dictionary<string,object>{{"entity_id",geometry["entity_id"]},{"geometry_key",CandidateGeometry.Key((string)geometry["component_id"],(string)geometry["kind"],axis,point)},{"mate_name",feature.Name},{"native_feature_id",feature.GetID()},{"native_mate_type",mate.Type},{"native_alignment",mate.Alignment},{"native_lock_rotation",lockData==null?(bool?)null:lockData.LockRotation},{"reference_index",i},{"component_instance",component.Name2}});
                }
            }catch{unresolved++;}
        }
        foreach(var candidate in candidateRows) {
            var axis=(double[])candidate["axis_global"];var point=(double[])candidate["reference_point_global_m"];
            string key=CandidateGeometry.Key((string)candidate["component_id"],(string)candidate["kind"],axis,point),eid=(string)candidate["entity_id"];
            var matches=references.Where(r=>(string)r["entity_id"]==eid||(string)r["geometry_key"]==key).Select(r=>new{mate_name=r["mate_name"],native_feature_id=r["native_feature_id"],native_mate_type=r["native_mate_type"],native_alignment=r["native_alignment"],native_lock_rotation=r["native_lock_rotation"],reference_index=r["reference_index"],reference_entity_id=r["entity_id"],relation=(string)r["entity_id"]==eid?"exact_persistent_face":"same_axis_or_plane_geometry_not_same_face"}).ToArray();
            candidate["mechanical_context"]=new{origin=matches.Length>0?"existing_mate_reference_geometry":"component_surface_geometry",matching_mate_reference_count=matches.Length,mate_references=matches.Take(8).ToArray(),truncated=matches.Length>8,scanned_mate_count=scanned,unresolved_reference_count=unresolved,complete=unresolved==0&&!truncatedScan,scan_truncated=truncatedScan,cooperative_scan_budget_s=10,free_axis_proven=false,motion_compatibility="not_checked",claim="native_reference_association_only_not_joint_or_DOF_inference"};
            candidate["reference_tools"]=new{entity_id=eid,tools=new[]{"list_drive_candidates","list_mate_references"},identity_scope="same_registered_model_and_resolvable_persistent_face"};
        }
    }
}
