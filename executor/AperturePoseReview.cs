using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

internal static class AperturePoseReview {
    public static void RequireEndpoint(int frame, IDictionary<string,double[]> initial, IDictionary<string,double[]> actual,
        string directory,string runId,double strokeMm,Action<string,object> save,
        string posesPath=null,string interferencePath=null) {
        if((frame!=0&&frame!=40)||initial.All(p=>PoseValidation.Matches(p.Value,actual[p.Key])))return;
        string reason=frame==0?"aperture_initial_pose_changed":"aperture_cycle_did_not_return_to_saved_pose";
        var endpoint=Describe(frame,initial,actual);
        string evidence=Path.Combine(directory,"aperture-endpoint-violation.json");
        string persistence="written";
        try {save(evidence,new{run_id=runId,stroke_mm=strokeMm,reason,endpoint,poses_path=posesPath,interference_path=interferencePath});}
        catch(IOException) {persistence="write_failed";}
        catch(UnauthorizedAccessException) {persistence="write_failed";}
        throw new CadFault("CONNECTION_EVIDENCE_FAILED","开口仿真的首帧或末帧偏离保存姿态。",
            new{reason,run_id=runId,stroke_mm=strokeMm,endpoint,endpoint_artifact_status=persistence,
                endpoint_artifact=persistence=="written"?evidence:null,poses_path=posesPath,interference_path=interferencePath});
    }

    public static object Describe(int frame, IDictionary<string,double[]> initial, IDictionary<string,double[]> actual) {
        var rows=initial.Select(p=>{
            var pose=actual[p.Key];
            bool valid=Valid(p.Value)&&Valid(pose);
            double distance=valid?PoseValidation.TranslationDistance(p.Value,pose):double.NaN;
            double angle=valid?PoseValidation.RotationDistance(p.Value,pose):double.NaN;
            return new {instance=p.Key,translation_m=Finite(distance)?(double?)distance:null,
                rotation_rad=Finite(angle)?(double?)angle:null,rotation_deg=Finite(angle)?(double?)(angle*180/Math.PI):null};
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
