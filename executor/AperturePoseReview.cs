using System.Collections.Generic;
using System.Linq;

internal static class AperturePoseReview {
    public static object Describe(int frame, IDictionary<string,double[]> initial, IDictionary<string,double[]> actual) {
        var rows=initial.Select(p=>{
            var pose=actual[p.Key];
            bool valid=Valid(p.Value)&&Valid(pose);
            double distance=valid?PoseValidation.TranslationDistance(p.Value,pose):double.NaN;
            double angle=valid?PoseValidation.RotationDistance(p.Value,pose):double.NaN;
            return new {instance=p.Key,translation_m=Finite(distance)?(double?)distance:null,
                rotation_rad=Finite(angle)?(double?)angle:null};
        }).ToArray();
        var translation=rows.Where(r=>r.translation_m.HasValue).OrderByDescending(r=>r.translation_m).ThenBy(r=>r.instance,System.StringComparer.Ordinal).ToArray();
        var rotation=rows.Where(r=>r.rotation_rad.HasValue).OrderByDescending(r=>r.rotation_rad).ThenBy(r=>r.instance,System.StringComparer.Ordinal).ToArray();
        return new {frame,time_s=frame/10.0,comparison=frame==0?"first_frame_to_saved_pose":"last_frame_to_saved_pose",
            component_count=rows.Length,invalid_pose_count=rows.Count(r=>!r.translation_m.HasValue||!r.rotation_rad.HasValue),
            maximum_translation_m=translation.Length==0?null:translation[0].translation_m,
            maximum_rotation_rad=rotation.Length==0?null:rotation[0].rotation_rad,
            allowed_translation_m=PoseValidation.TranslationToleranceM,allowed_rotation_rad=PoseValidation.RotationToleranceRad,
            worst_translation_components=translation.Take(4).ToArray(),worst_rotation_components=rotation.Take(4).ToArray(),
            root_cause_proven=false};
    }

    static bool Valid(double[] pose) {
        return pose!=null&&pose.Length>=12&&pose.All(Finite);
    }
    static bool Finite(double value) {return !double.IsNaN(value)&&!double.IsInfinity(value);}
}
