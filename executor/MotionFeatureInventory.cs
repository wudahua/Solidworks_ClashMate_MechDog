using System;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    object RegisteredDriveReferenceEvidence(IModelDoc2 doc,UserDrive drive) {
        if(drive==null)return new{status="no_project_registration",study_membership="not_proven"};
        try {
            int error;var feature=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(drive.NativeMotorReference),out error) as IFeature;
            string identitySource="native_persistent_reference";
            if(error!=0||feature==null){feature=((IAssemblyDoc)doc).FeatureByName(drive.NativeMotorName) as IFeature;identitySource="exact_feature_name_and_native_id";}
            if(feature==null||feature.GetID()!=drive.NativeMotorId||feature.Name!=drive.NativeMotorName)return new{status="registered_native_reference_not_verified",native_reference_error=error,study_membership="project_registration_only"};
            var motor=feature.GetDefinition() as ISimulationMotorFeatureData;
            return (object)new{status=motor==null?"native_feature_resolved_parameters_unavailable":"native_feature_identity_and_parameters_observed",native_feature_id=feature.GetID(),identity_source=identitySource,persistent_reference_error=error,name=feature.Name,native_type=feature.GetTypeName2(),parameters=NativeMotorParameters(doc,motor),study_membership="project_registration_not_independent_native_study_membership",inventory_complete=false};
        }catch(COMException e){return new{status="native_reference_unavailable",native_hresult=e.HResult,study_membership="not_proven"};}catch(FormatException){return new{status="registered_reference_invalid",study_membership="not_proven"};}
    }
    sealed class InventoryNode {public IFeature Feature;public int Depth;}
    object UnassignedMotorFeatureObservations(IModelDoc2 doc) {
        var rows=new List<object>();var visited=new HashSet<int>();var queue=new Queue<InventoryNode>();int scanned=0,failures=0;bool truncated=false;
        try{for(var f=(IFeature)doc.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature()){queue.Enqueue(new InventoryNode{Feature=f,Depth=0});if(queue.Count>=1000){truncated=true;break;}}}catch(COMException){failures++;}
        while(queue.Count>0&&scanned<1000){var node=queue.Dequeue();try{var f=node.Feature;if(!visited.Add(f.GetID()))continue;scanned++;string type=f.GetTypeName2();
            if(type.IndexOf("motor",StringComparison.OrdinalIgnoreCase)>=0){var motor=f.GetDefinition() as ISimulationMotorFeatureData;if(motor!=null){if(rows.Count<20)rows.Add(new{name=f.Name,native_feature_id=f.GetID(),type=type,motor_type=motor.MotorType,motion_type=motor.MotionType,magnitude_raw=motor.Magnitude,parameters=NativeMotorParameters(doc,motor),study_membership_status="unproven_not_assigned_to_any_study",reference_source="assembly_feature_tree"});else truncated=true;}}
            if(node.Depth>=8){if(f.GetFirstSubFeature()!=null)truncated=true;continue;}for(var child=(IFeature)f.GetFirstSubFeature();child!=null;child=(IFeature)child.GetNextSubFeature()){if(queue.Count>=1000){truncated=true;break;}queue.Enqueue(new InventoryNode{Feature=child,Depth=node.Depth+1});}
        }catch(COMException){failures++;}}
        if(queue.Count>0)truncated=true;
        return new{scan_scope="bounded_assembly_feature_tree_motor_types",scanned_features=scanned,read_failures=failures,truncated=truncated,motors=rows.ToArray(),study_membership_status="unproven",inventory_complete=false,claim="diagnostic observations only; not a replacement for native per-study inventory; empty does not prove no motors",activation_performed=false,calculate_performed=false};
    }
}
