using System;
using System.Linq;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    object MotorReferenceObservation(IModelDoc2 doc,object reference) {
        if(reference==null)return new{status="null"};
        try {
            var entity=reference as IEntity;var owner=entity==null?null:entity.GetComponent() as IComponent2;
            string persisted=null;try{var bytes=doc.Extension.GetPersistReference3(reference) as byte[];if(bytes!=null)persisted=Convert.ToBase64String(bytes);}catch{}
            object geometry=null;try{var face=reference as IFace2;if(face!=null)geometry=MateGeometry(doc,face,owner);}catch{}
            return new{status="observed",instance=owner==null?null:owner.Name2,component_id=owner==null?null:StableId("component_",Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(owner))),kind=reference is IFace2?"face":reference is IEdge?"edge":"other_native_reference",entity_id=persisted==null?null:StableId("entity_",persisted),geometry=geometry,registration_status="observation_only_query_reference_tool_before_creation"};
        }catch(Exception e){return new{status="unavailable",error_code=HistoryErrorCode(e)};}
    }
    object NativeMotorParameters(IModelDoc2 doc,ISimulationMotorFeatureData motor) {
        if(motor==null)return new{status="unavailable"};
        try{var relative=motor.RelativeComponent as IComponent2;return new{status="observed",motor_type=motor.MotorType,motion_type=motor.MotionType,magnitude_raw=motor.Magnitude,velocity_raw=motor.Velocity,units="native_adapter_raw_not_user_speed",reverse_direction=motor.ReverseDirection,relative_component=relative==null?null:relative.Name2,direction_reference=MotorReferenceObservation(doc,motor.DirectionReference),location=MotorReferenceObservation(doc,motor.Location)};}
        catch(Exception e){return new{status="unavailable",error_code=HistoryErrorCode(e)};}
    }
    bool SameMotorReference(IModelDoc2 doc,object actual,string expected) {
        return NativeObjectReferenceIdentity.Matches<object>(actual,expected,token=>{
            byte[] bytes;try{bytes=Convert.FromBase64String(token);}catch(FormatException){return null;}
            int error;var resolved=doc.Extension.GetObjectByPersistReference3(bytes,out error);return error==0?resolved:null;
        },(a,b)=>Sw.IsSame(a,b)==(int)SolidWorks.Interop.swconst.swObjectEquality.swObjectSame,
        (a,b)=>{
            if(!(a is IFace2)||!(b is IFace2))return false;
            var left=((IEntity)a).GetComponent() as IComponent2;var right=((IEntity)b).GetComponent() as IComponent2;
            return left!=null&&right!=null&&left.GetID()==right.GetID()&&left.Name2==right.Name2&&
                Sw.IsSame(left,right)==(int)SolidWorks.Interop.swconst.swObjectEquality.swObjectSame;
        });
    }
    object VerifyCreatedMotor(IModelDoc2 doc,ISimulationMotorFeatureData motor,string reference,double speed,string kind) {
        double expected=kind=="rotary"?speed*2*Math.PI/60:speed/1000;
        bool direction= motor!=null&&SameMotorReference(doc,motor.DirectionReference,reference);
        bool location= motor!=null&&SameMotorReference(doc,motor.Location,reference);
        if(motor==null||motor.MotionType!=0||motor.MotorType!=(kind=="rotary"?1:0)||!direction||!location||!MotorMagnitudeMatches(motor.Magnitude,expected))
            throw new CadFault("MOTOR_PARAMETERS_UNVERIFIED","原生马达的驱动参考、位置、类型或恒速参数未与请求一致。",new{expected_native_magnitude=expected,motor_type=kind,observed=NativeMotorParameters(doc,motor),solver_compatibility_proven=false});
        return new{direction_native_identity_verified=direction,location_native_identity_verified=location,
            method="resolve_requested_reference_then_native_entity_and_component_IsSame",
            geometry_substitution=false,registration_rebound=false};
    }
    internal static bool MotorMagnitudeMatches(double actual,double expected){return !double.IsNaN(actual)&&!double.IsInfinity(actual)&&Math.Abs(actual-expected)<=Math.Max(1e-10,Math.Abs(expected)*1e-8);}
}
