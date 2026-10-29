using System;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public partial class Cad {
    object AdditionalConstraintGeometry(IModelDoc2 doc,IMateEntity2 entity,IComponent2 component) {
        if(component==null)return null;
        try {
            bool root=component.IsRoot();object reference=entity.Reference;var face=reference as IFace2;double[] point=null,axis=null;string kind=null;
            if(face!=null&&((ISurface)face.GetSurface()).IsCone()) {
                var values=(double[])((ISurface)face.GetSurface()).ConeParams2;
                if(values==null||values.Length<8)return null;
                point=values.Take(3).ToArray();axis=values.Skip(3).Take(3).ToArray();kind="conical_axis";
            }else if(entity.ReferenceType2==(int)swSelectType_e.swSelDATUMPLANES) {
                var underlying=root?reference:doc.Extension.GetCorresponding2(reference);var feature=underlying as IFeature;
                var plane=underlying as IRefPlane;
                if(plane==null&&feature!=null)plane=feature.GetSpecificFeature2() as IRefPlane;
                if(plane==null) {
                    feature=reference as IFeature;var part=component.GetModelDoc2() as IModelDoc2;
                    if(feature==null||part==null||(!root&&part.GetType()!=1))return null;var local=root?((IAssemblyDoc)doc).FeatureByName(feature.Name) as IFeature:((IPartDoc)part).FeatureByName(feature.Name) as IFeature;
                    plane=local==null?null:local.GetSpecificFeature2() as IRefPlane;
                }
                if(plane==null)return null;
                var values=(double[])plane.Transform.ArrayData;
                point=ApplyPose(values,new[]{0.0,0.0,0.0},true);axis=ApplyPose(values,new[]{0.0,0.0,1.0},false);kind="planar_normal";
            }else if(entity.ReferenceType2==(int)swSelectType_e.swSelDATUMAXES) {
                var feature=reference as IFeature;var datum=reference as IRefAxis;
                if(datum==null&&feature!=null){var part=component.GetModelDoc2() as IModelDoc2;var local=part==null||part.GetType()!=1?null:((IPartDoc)part).FeatureByName(feature.Name) as IFeature;datum=local==null?null:local.GetSpecificFeature2() as IRefAxis;}
                if(datum==null)return null;var values=datum.GetRefAxisParams() as double[];
                if(values==null||values.Length!=6)return null;
                point=values.Take(3).ToArray();axis=values.Skip(3).Zip(point,(a,b)=>a-b).ToArray();kind="reference_axis";
            }
            if(point==null||axis==null)return null;var pose=root?new[]{1.0,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0}:(double[])component.GetTotalTransform(false).ArrayData;
            axis=ApplyPose(pose,axis,false);double length=Math.Sqrt(axis.Sum(v=>v*v));if(length<1e-12)return null;
            return new{kind=kind,axis_global=axis.Select(v=>v/length).ToArray(),reference_point_global_m=ApplyPose(pose,point,true),
                source="native_mate_reference_axis_observation",creation_reference_supported=false,entity_registered=false};
        }catch(COMException){return null;}
    }
    object ConcentricRotationObservation(IFeature feature,IMate2 mate) {
        if(mate.Type!=1)return null;
        try {
            var data=feature.GetDefinition() as IConcentricMateFeatureData;
            if(data==null)return new{status="unavailable",locked=(bool?)null,error="native_definition_unavailable"};
            return new{status="observed",locked=(bool?)data.LockRotation,error=(string)null};
        }catch(COMException error){return new{status="unavailable",locked=(bool?)null,error="COM_"+error.HResult};}
    }
    object MateReferenceEvidence(IModelDoc2 doc,IMateEntity2 entity,UserModel registerModel=null) {
        var component=entity.ReferenceComponent as IComponent2;
        var row=new Dictionary<string,object>{{"instance",component==null?null:component.Name2},{"reference_type",entity.ReferenceType2},{"reference_type_name",Enum.GetName(typeof(swSelectType_e),entity.ReferenceType2)??"unknown_native_reference_type"},{"component_id",component==null?null:StableId("component_",Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(component)))},{"geometry_status","unsupported_reference_kind"},{"creation_reference_capability","top_level_planar_cylindrical_faces_and_concentric_circular_edges"},{"unsupported_reference_action","query_supported_faces_on_same_component_or_use_native_CAD_no_automatic_substitution"},{"automatic_edge_or_sketch_to_face_conversion",false}};
        try{object reference=entity.Reference;var face=reference as IFace2;row["reference_kind"]=face!=null?"face":reference is IEdge?"edge":reference is IVertex?"vertex":reference==null?"null":"other_native_reference";if(face!=null){var surface=face.GetSurface() as ISurface;row["surface_type"]=SurfaceTypeName(surface);row["geometry_status"]=surface==null?"native_surface_unavailable":"unsupported_surface_type";row["entity_registration_status"]="not_registered_unsupported_geometry";if(surface!=null&&(surface.IsPlane()||surface.IsCylinder())){row["geometry"]=MateGeometry(doc,face,component);row["geometry_status"]="resolved_face";row["entity_registration_status"]="inspection_only_query_mate_references_before_use";row["reference_source"]="inspect_model_native_mate";row["entity_id"]=((Dictionary<string,object>)row["geometry"])["entity_id"];row["kind"]=((Dictionary<string,object>)row["geometry"])["kind"];row["registration_check_scope"]="not_checked_by_inspection";row["required_tool"]="list_mate_references";row["required_query"]=new{component_id=row["component_id"],kind=(string)((Dictionary<string,object>)row["geometry"])["kind"]};if(registerModel!=null){RegisterInspectedFace(registerModel,doc,face,row);}}}else if(reference is IEdge&&((ICurve)((IEdge)reference).GetCurve()).IsCircle()){var geometry=CircularMateGeometry(doc,(IEdge)reference,component);row["geometry"]=geometry;row["entity_id"]=geometry["entity_id"];row["kind"]="circular_edge";row["geometry_status"]="resolved_circular_edge";row["entity_registration_status"]="inspection_only_query_mate_references_before_use";row["required_tool"]="list_mate_references";row["required_query"]=new{component_id=row["component_id"],kind="circular_edge"};}else if(reference==null)row["geometry_status"]="native_reference_unavailable";}
        catch(COMException e){row["geometry_status"]="native_reference_unavailable";row["native_hresult"]=e.HResult;}
        catch(CadFault e){row["geometry_status"]=e.Code;}
        if(!row.ContainsKey("geometry")&&((string)row["geometry_status"]=="unsupported_surface_type"||(string)row["geometry_status"]=="unsupported_reference_kind"))row["constraint_geometry"]=AdditionalConstraintGeometry(doc,entity,component);
        bool isRoot=component!=null&&component.IsRoot();row["reference_owner_scope"]=isRoot?"assembly_root":"component_or_unresolved";
        row["root_reference_verified"]=isRoot&&row.ContainsKey("constraint_geometry")&&row["constraint_geometry"]!=null;
        return row;
    }
    object[] UserMates(IModelDoc2 doc,UserModel registerModel=null) {
        var items=new List<object>();foreach(var f in BasicMateFeatures(doc).GroupBy(v=>v.GetID()).Select(g=>g.First())) {
            var mate=(IMate2)f.GetSpecificFeature2();bool warning;int error=f.GetErrorCode2(out warning);
            items.Add(new{name=f.Name,native_feature_id=f.GetID(),native_feature_type=f.GetTypeName2(),type=mate.Type,type_name=Enum.GetName(typeof(swMateType_e),mate.Type)??"unknown_native_mate_type",creation_mate_type_supported=new[]{"concentric","coincident","distance","parallel","perpendicular"}.Any(t=>BasicMateType(t)==mate.Type),alignment=mate.Alignment,alignment_name=mate.Alignment==0?"aligned":mate.Alignment==1?"anti_aligned":"other_native_alignment",error=error,warning=warning,suppressed=EGSuppressed(f),rotation_lock_observation=ConcentricRotationObservation(f,mate),entities=Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>MateReferenceEvidence(doc,mate.MateEntity(i),registerModel)).ToArray()});
        }return items.ToArray();
    }
    static string SurfaceTypeName(ISurface surface){if(surface==null)return "unavailable";if(surface.IsPlane())return "plane";if(surface.IsCylinder())return "cylinder";if(surface.IsSphere())return "sphere";if(surface.IsTorus())return "torus";if(surface.IsCone())return "cone";return "other_surface";}
}
