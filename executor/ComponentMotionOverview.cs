using System;
using System.Linq;
using System.Collections.Generic;

public static class ComponentMotionOverview {
    public static Dictionary<string,object> Analyze(Dictionary<string,double[][]> poses,Dictionary<string,bool> fixedStates,string registeredTarget) {
        if(!poses.Keys.OrderBy(v=>v).SequenceEqual(fixedStates.Keys.OrderBy(v=>v)))throw new Exception("COMPONENT_SCOPE_CHANGED");
        var rows=poses.OrderBy(p=>p.Key,StringComparer.Ordinal).Select(p=>{
            var samples=p.Value;if(samples==null||samples.Length<2||samples.Any(v=>v==null||v.Length<12||v.Any(x=>double.IsNaN(x)||double.IsInfinity(x))))throw new Exception("MOTION_OVERVIEW_SAMPLES_INVALID");
            double translation=samples.Max(v=>PoseValidation.TranslationDistance(samples[0],v)),rotation=samples.Max(v=>PoseValidation.RotationDistance(samples[0],v)),angularPath=Enumerable.Range(1,samples.Length-1).Sum(i=>PoseValidation.RotationDistance(samples[i-1],samples[i]));
            return new Dictionary<string,object>{{"instance",p.Key},{"fixed_component",fixedStates[p.Key]},{"registered_drive_target",registeredTarget==null?(bool?)null:p.Key==registeredTarget},{"maximum_translation_from_frame0_m",translation},{"maximum_rotation_from_frame0_rad",rotation},{"sampled_angular_path_rad",angularPath},{"motion_detected",translation>1e-9||rotation>1e-9}};
        }).ToArray();
        var movable=rows.Where(r=>!(bool)r["fixed_component"]).ToArray();var target=rows.FirstOrDefault(r=>(string)r["instance"]==registeredTarget);bool targetMoved=target!=null&&(bool)target["motion_detected"];var others=movable.Where(r=>(string)r["instance"]!=registeredTarget).ToArray();
        bool informational=registeredTarget!=null&&targetMoved&&others.Length>0&&others.All(r=>!(bool)r["motion_detected"]);
        return new Dictionary<string,object>{{"scope","sampled_component_origin_motion_not_design_intent"},{"checked_component_count",rows.Length},{"movable_component_count",movable.Length},{"fixed_component_count",rows.Length-movable.Length},{"registered_drive_target",registeredTarget},{"native_drive_inventory_status","not_proven_complete"},{"registered_target_motion_detected",target==null?(bool?)null:targetMoved},{"other_movable_components_checked",registeredTarget==null?(int?)null:others.Length},{"other_movable_motion_detected",registeredTarget==null?(bool?)null:others.Any(r=>(bool)r["motion_detected"])},{"translation_detection_threshold_m",1e-9},{"rotation_detection_threshold_rad",1e-9},{"informational",informational?"REGISTERED_TARGET_MOVED_OTHER_MOVABLE_COMPONENTS_NOT_DETECTED":null},{"claim","sampled observation only; no claim of missed motion, absent native motors, friction requirement or correct mechanism intent"},{"components",rows}};
    }
}
