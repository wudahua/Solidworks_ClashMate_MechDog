using System;
using System.Linq;
using System.Collections.Generic;

// Rigid component poses in SOLIDWORKS ArrayData convention (row basis vectors).
// Every sample is transformed into the supplied reference component's own frame.
public static class RelativeMotion {
    public static double[] Identity(){return new[]{1.0,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0};}
    static void Pose(double[] p){if(p==null||p.Length<12||p.Any(v=>double.IsNaN(v)||double.IsInfinity(v))||(p.Length>12&&Math.Abs(p[12]-1)>1e-8))throw new ArgumentException("RELATIVE_POSE_INVALID_OR_SCALED");for(int r=0;r<3;r++)for(int c=0;c<3;c++)if(Math.Abs(Enumerable.Range(0,3).Sum(k=>p[3*r+k]*p[3*c+k])-(r==c?1:0))>1e-6)throw new ArgumentException("RELATIVE_POSE_NOT_RIGID");}
    public static double[] Vector(double[] p,double[] v){Pose(p);return Enumerable.Range(0,3).Select(j=>Enumerable.Range(0,3).Sum(k=>v[k]*p[3*k+j])).ToArray();}
    public static double[] InverseVector(double[] p,double[] v){Pose(p);return Enumerable.Range(0,3).Select(j=>Enumerable.Range(0,3).Sum(k=>v[k]*p[3*j+k])).ToArray();}
    public static double[] Unit(double[] v){if(v==null||v.Length!=3||v.Any(x=>double.IsNaN(x)||double.IsInfinity(x)))throw new ArgumentException("INVALID_MOTION_AXIS");double n=Math.Sqrt(v.Sum(x=>x*x));if(n<1e-12)throw new ArgumentException("INVALID_MOTION_AXIS");return v.Select(x=>x/n).ToArray();}
    public static double[] InReference(double[] moving,double[] reference,double[] point) {
        Pose(moving);Pose(reference);if(point==null||point.Length!=3||point.Any(v=>double.IsNaN(v)||double.IsInfinity(v)))throw new ArgumentException("INVALID_MOTION_POINT");
        var p=Identity();for(int r=0;r<3;r++)for(int c=0;c<3;c++)p[3*r+c]=Enumerable.Range(0,3).Sum(k=>moving[3*r+k]*reference[3*c+k]);
        var offset=Vector(moving,point).Select((v,j)=>v+moving[9+j]-reference[9+j]).ToArray();var q=InverseVector(reference,offset);for(int j=0;j<3;j++)p[9+j]=q[j];return p;
    }
    public static double[][] Samples(double[][] moving,double[][] reference,double[] point) {
        if(moving==null||moving.Length<2||reference!=null&&reference.Length!=moving.Length)throw new ArgumentException("RELATIVE_SAMPLE_SCOPE_MISMATCH");
        return moving.Select((p,i)=>InReference(p,reference==null?Identity():reference[i],point)).ToArray();
    }
    public static Dictionary<string,object> DriveAudit(double[][] moving,double[][] reference,double[] axisLocal,double[] pointLocal,string kind,double speed,double duration) {
        if(!new[]{"linear","rotary"}.Contains(kind)||duration<=0||double.IsNaN(duration)||double.IsInfinity(duration)||speed<=0||double.IsNaN(speed)||double.IsInfinity(speed))throw new ArgumentException("INVALID_DRIVE_MEASUREMENT");
        var p=Samples(moving,reference,pointLocal);var axis=Unit(InverseVector(reference==null?Identity():reference[0],Vector(moving[0],Unit(axisLocal))));
        double maxAxisChange=moving.Select((v,i)=>Unit(InverseVector(reference==null?Identity():reference[i],Vector(v,axisLocal)))).Max(v=>Math.Atan2(Math.Sqrt(Enumerable.Range(0,3).Sum(j=>Math.Pow(v[j]-axis[j]*v.Zip(axis,(a,b)=>a*b).Sum(),2))),v.Zip(axis,(a,b)=>a*b).Sum())*180/Math.PI);
        var intent=MotionIntent.Evaluate(p,axis,kind,1e-12);
        double observed=Convert.ToDouble(intent["signed_net_travel"])/duration*(kind=="rotary"?1.0/6:1);
        double error=Math.Abs(Math.Abs(observed)-speed),tolerance=Math.Max(.001,speed*.005);
        double dt=duration/(p.Length-1);var intervalSpeeds=Enumerable.Range(1,p.Length-1).Select(i=>Convert.ToDouble(MotionIntent.Evaluate(new[]{p[i-1],p[i]},axis,kind,1e-12)["signed_net_travel"])/dt*(kind=="rotary"?1.0/6:1)).ToArray();
        double intervalError=intervalSpeeds.Max(v=>Math.Abs(Math.Abs(v)-speed));
        bool applicable=maxAxisChange<=.1&&(kind!="linear"||Convert.ToDouble(intent["slide_rotation_deg"])<=.1);
        return new Dictionary<string,object>{{"status",!applicable?"inconclusive":error<=tolerance&&intervalError<=tolerance?"pass":"fail"},{"kind",kind},{"requested",speed},{"observed_signed",observed},{"unit",kind=="linear"?"mm/s":"rpm"},{"absolute_magnitude_error",error},{"maximum_sampled_interval_magnitude_error",intervalError},{"sampled_interval_speed_min",intervalSpeeds.Min()},{"sampled_interval_speed_max",intervalSpeeds.Max()},{"sampled_intervals_checked",intervalSpeeds.Length},{"magnitude_tolerance",tolerance},{"axis_change_deg",maxAxisChange},{"axis_change_tolerance_deg",.1},{"direction_verified",false},{"direction_scope","native_arrow_reverse_readback_only"},{"method","rigid_pose_relative_reference_component_constant_axis"},{"measurement_version",2},{"reference_frame",reference==null?"assembly_global":"reference_component_local"},{"axis_reference_local",axis},{"reference_point_moving_local_m",pointLocal},{"applicability_reason",applicable?"relative_axis_and_motion_within_scope":"moving_axis_or_relative_rotation_requires_another_measurement"}};
    }
}
