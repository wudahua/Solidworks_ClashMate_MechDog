using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    Dictionary<string,object> AuditUserDrive(UserModel model,IModelDoc2 doc,UserDrive drive,Dictionary<string,double[][]> poses,double duration) {
        var component=ResolveUserComponent(model,doc,drive.ComponentId);var moving=poses[component.Name2];double[][] reference=null;
        if(!string.IsNullOrEmpty(drive.ReferenceComponentId)){var relative=ResolveUserComponent(model,doc,drive.ReferenceComponentId);if(!poses.TryGetValue(relative.Name2,out reference))throw new CadFault("DRIVE_REFERENCE_POSES_MISSING","相对组件不在采样集合中。",new{reference_component_id=drive.ReferenceComponentId});}
        var localAxis=drive.AxisLocal??RelativeMotion.InverseVector(moving[0],drive.Axis);var localPoint=drive.PointLocal??new double[3];
        var audit=RelativeMotion.DriveAudit(moving,reference,localAxis,localPoint,drive.Kind,drive.Speed,duration);
        audit["component_id"]=drive.ComponentId;audit["reference_component_id"]=drive.ReferenceComponentId??"";audit["reverse_direction"]=drive.Reverse;audit["registration_measurement_version"]=drive.MeasurementVersion;
        audit["native_motor_identity_status"]=drive.NativeMotorReference==null?"legacy_registration_not_verified":"registered_persistent_reference";
        if(drive.NativeMotorReference!=null){int error;var feature=doc.Extension.GetObjectByPersistReference3(Convert.FromBase64String(drive.NativeMotorReference),out error) as IFeature;
            if(feature==null||error!=0){var study=(IMotionStudy)((IMotionStudyManager)doc.Extension.GetMotionStudyManager()).GetMotionStudy(drive.Study);var features=(study.GetMotionFeatures() as object[]??new object[0]).OfType<IFeature>().Where(f=>f.GetID()==drive.NativeMotorId&&f.Name==drive.NativeMotorName).ToArray();feature=features.Length==1?features[0]:null;audit["native_motor_identity_status"]=feature==null?"not_verified":"study_feature_id_name_and_parameters";audit["persistent_reference_error"]=error;}
            if(feature==null){audit["status"]="inconclusive";audit["applicability_reason"]="registered_motor_identity_not_verified";}
            else {audit["native_motor_feature"]=feature.Name;var data=feature.GetDefinition() as ISimulationMotorFeatureData;double expected=drive.Kind=="rotary"?drive.Speed*2*Math.PI/60:drive.Speed/1000;var nativeRelative=data==null?null:data.RelativeComponent as IComponent2;var wantedRelative=string.IsNullOrEmpty(drive.ReferenceComponentId)?null:ResolveUserComponent(model,doc,drive.ReferenceComponentId);
                bool matched=data!=null&&Math.Abs(data.Magnitude-expected)<=Math.Max(1e-9,expected*1e-7)&&data.ReverseDirection==drive.Reverse&&(wantedRelative==null?nativeRelative==null:nativeRelative!=null&&nativeRelative.Name2==wantedRelative.Name2);audit["native_motor_parameters_match"]=matched;
                if(!matched){audit["status"]="inconclusive";audit["applicability_reason"]="registered_motor_parameters_changed_or_unreadable";}
            }
        }
        return audit;
    }
    static Dictionary<string,object> MeasurementCriteria(string kind,double minimum,string reference) {
        return new Dictionary<string,object>{{"expected_motion",kind},{"minimum_travel",minimum},{"travel_unit",kind=="rotary"?"deg":"mm"},{"reference_component_id",reference??""},{"reference_frame",string.IsNullOrEmpty(reference)?"assembly_global":"reference_component_local"},{"off_axis_tolerance",kind=="linear"?.01:.1},{"off_axis_unit",kind=="linear"?"mm":"deg"},{"slide_rotation_tolerance_deg",.1},{"criteria_status","not_evaluated"}};
    }
}
