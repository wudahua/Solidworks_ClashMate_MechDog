using System;
using System.Linq;
using System.Collections.Generic;

public sealed class MotionSampleException : ArgumentException {
    public readonly object Diagnostics;
    public MotionSampleException(int frame,double angle):base("ROTATION_SAMPLE_AMBIGUOUS") {
        Diagnostics=new{frame_before=frame-1,frame_after=frame,observed_interval_rotation_deg=angle*180/Math.PI,maximum_supported_interval_deg=45,required_action="increase_output_fps_and_rerun_explicit_verification",higher_fps_guarantees_success=false};
    }
}

// A sampled, user-declared axis test. This is not a DOF counter or a physics oracle.
public static class MotionIntent {
    public static Dictionary<string,object> Evaluate(double[][] poses,double[] axis,string kind,double minimumTravel) {
        if(poses==null||poses.Length<2||poses.Any(p=>p==null||p.Length<12||p.Any(v=>double.IsNaN(v)||double.IsInfinity(v)))||axis==null||axis.Length!=3||axis.Any(v=>double.IsNaN(v)||double.IsInfinity(v))||!new[]{"rotary","linear"}.Contains(kind)||double.IsNaN(minimumTravel)||double.IsInfinity(minimumTravel)||minimumTravel<=0)throw new ArgumentException("INVALID_MOTION_INTENT");
        double norm=Math.Sqrt(axis.Sum(v=>v*v));if(norm<1e-12)throw new ArgumentException("INVALID_MOTION_AXIS");axis=axis.Select(v=>v/norm).ToArray();
        double signed=0,travel=0,offAxis=0,rotationTravel=0,translationTravel=0;
        if(kind=="linear") {
            var projections=poses.Select(p=>Enumerable.Range(0,3).Sum(k=>(p[9+k]-poses[0][9+k])*axis[k])*1000).ToArray();
            signed=projections.Last();travel=projections.Max()-projections.Min();
            offAxis=poses.Max(p=>{var v=Enumerable.Range(0,3).Select(k=>(p[9+k]-poses[0][9+k])*1000).ToArray();double dot=v.Zip(axis,(a,b)=>a*b).Sum();return Math.Sqrt(v.Zip(axis,(a,b)=>Math.Pow(a-dot*b,2)).Sum());});
            // Rotation in a declared straight slide is an unintended motion.
            foreach(var p in poses){double trace=Enumerable.Range(0,9).Sum(k=>poses[0][k]*p[k]);rotationTravel=Math.Max(rotationTravel,Math.Acos(Math.Max(-1,Math.Min(1,(trace-1)/2)))*180/Math.PI);}
        } else {
            var totals=new List<double>{0};
            for(int i=1;i<poses.Length;i++) {
                var a=poses[i-1];var b=poses[i];var q=new double[9];for(int r=0;r<3;r++)for(int c=0;c<3;c++)q[3*r+c]=Enumerable.Range(0,3).Sum(k=>a[3*k+r]*b[3*k+c]);
                double angle=Math.Acos(Math.Max(-1,Math.Min(1,(q[0]+q[4]+q[8]-1)/2)));
                // Shortest-arc samples cannot prove multiple turns between frames.
                if(angle>Math.PI/4+1e-8)throw new MotionSampleException(i,angle);
                double factor=angle<1e-7?.5:angle/(2*Math.Sin(angle));var v=new[]{(q[5]-q[7])*factor,(q[6]-q[2])*factor,(q[1]-q[3])*factor};
                double dot=v.Zip(axis,(x,y)=>x*y).Sum();signed+=dot*180/Math.PI;totals.Add(signed);
                offAxis+=Math.Sqrt(v.Zip(axis,(x,y)=>Math.Pow(x-dot*y,2)).Sum())*180/Math.PI;
            }
            travel=totals.Max()-totals.Min();
            // Translation of a component origin can be valid when the origin is off the shaft.
            translationTravel=poses.Max(p=>Math.Sqrt(Enumerable.Range(9,3).Sum(k=>Math.Pow(p[k]-poses[0][k],2)))*1000);
        }
        double offTolerance=kind=="linear"?.01:.1;
        // Rounding budget only; cap relative to the requirement so zero motion never passes.
        double numericTolerance=Math.Min(minimumTravel*1e-9,Math.Max(1e-9,Math.Max(travel,minimumTravel)*1e-12));
        bool roundedBoundary=travel<minimumTravel&&minimumTravel-travel<=numericTolerance;
        bool passed=(travel>=minimumTravel||roundedBoundary)&&offAxis<=offTolerance&&(kind!="linear"||rotationTravel<=.1);
        return new Dictionary<string,object>{{"assertion",passed?"pass":"fail"},{"expected_motion",kind},{"travel",travel},{"signed_net_travel",signed},{"travel_unit",kind=="linear"?"mm":"deg"},{"minimum_travel",minimumTravel},{"minimum_travel_residual",travel-minimumTravel},{"minimum_travel_numeric_tolerance",numericTolerance},{"minimum_travel_rounding_applied",roundedBoundary},{"numeric_tolerance_scope","floating_roundoff_only_not_mechanical_allowance"},{"off_axis_travel",offAxis},{"off_axis_tolerance",offTolerance},{"off_axis_unit",kind=="linear"?"mm":"deg"},{"slide_rotation_deg",rotationTravel},{"slide_rotation_tolerance_deg",.1},{"rotary_origin_translation_mm",translationTravel},{"axis_global",axis},{"claim","sampled_requested_axis_motion_only"},{"degrees_of_freedom_status","unknown"},{"direction_verified",false}};
    }
}
