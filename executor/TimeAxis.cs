using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    double[] VerifiedUserTimes(IMotionStudy study,IModelDoc2 doc,double duration,int fps,string directory,double[] replayExpected=null) {
        var axisTiming=new OperationTiming("native_axis_read_grid_comparison_and_readback_excludes_artifact_write");axisTiming.Start("native_time_axis_read");IComponent2 carrier;object nativeReadTiming;var times=NativeUserTimes(study,doc,out carrier,out nativeReadTiming);axisTiming.Start("managed_grid_comparison");
        var expected=replayExpected??Enumerable.Range(0,(int)Math.Round(duration*fps)+1).Select(i=>(double)i/fps).ToArray();
        bool finite=times!=null&&times.All(t=>!double.IsNaN(t)&&!double.IsInfinity(t));
        var steps=finite&&times.Length>1?times.Skip(1).Zip(times,(a,b)=>a-b).ToArray():new double[0];
        double? delta=finite&&times.Length>0?(double?)Enumerable.Range(0,Math.Min(times.Length,expected.Length)).Max(i=>Math.Abs(times[i]-expected[i])):null;
        bool valid=finite&&times.Length==expected.Length&&delta.HasValue&&delta.Value<=1e-7&&steps.All(d=>d>0);
        axisTiming.Start("diagnostic_carrier_selection");// The diagnostic names the exact component used above, including bodyless exclusions.
        var alternate=new List<object>();
        if(!valid){
            axisTiming.Start("alternate_native_carrier_read");var model=userModels.Values.FirstOrDefault(m=>string.Equals(m.Path,doc.GetPathName(),StringComparison.OrdinalIgnoreCase));
            UserDrive drive;
            if(model!=null&&model.Drives.TryGetValue(study.Name,out drive)){
                var driven=ResolveUserComponent(model,doc,drive.ComponentId);
                try{var t=NativeUserTimes(study,driven);alternate.Add(new{component=driven.Name2,count=t.Length,head=t.Take(8).ToArray(),tail=t.Skip(Math.Max(0,t.Length-8)).ToArray()});}
                catch(Exception e){alternate.Add(new{component=driven.Name2,error=e.Message});}
            }
        }
        axisTiming.Start("native_settings_and_clock_readback");int configuredFps=((IMotionStudyProperties)study.GetProperties(4)).GetFrameRate();bool configurationChanged=configuredFps!=fps||Math.Abs(study.GetDuration()-duration)>1e-8;
        var diagnostic=new {expected_count=expected.Length,actual_count=times==null?0:times.Length,requested_duration_s=duration,requested_output_fps=fps,
            configured_duration_s=study.GetDuration(),configured_output_fps=configuredFps,configuration_changed_during_native_solve=configurationChanged,output_fps_ratio=(double)configuredFps/fps,
            finite=finite,strictly_increasing=steps.Length>0&&steps.All(d=>d>0),maximum_grid_error_s=delta,
            first_time_s=finite&&times.Length>0?(double?)times[0]:null,last_time_s=finite&&times.Length>0?(double?)times[times.Length-1]:null,
            minimum_step_s=steps.Length>0?(double?)steps.Min():null,maximum_step_s=steps.Length>0?(double?)steps.Max():null,
            head=finite?times.Take(8).ToArray():null,tail=finite?times.Skip(Math.Max(0,times.Length-8)).ToArray():null,
            carrier_component=carrier.Name2,carrier_selection="first_active_nonfixed_part_first_face",alternate_carriers=alternate.ToArray(),study_clock_after_calculate_s=study.GetTime(),x_axis_type=0,y_axis_type=7,verified=valid};
        axisTiming.Finish();string path=Path.Combine(directory,"time-axis.json");
        AtomicJson(path,new {diagnostic=diagnostic,native_time_s=finite?times:null,expected_time_s=expected,host_timings=axisTiming.Export(),native_read_timings=nativeReadTiming,native_read_timing_relation="child_of_native_time_axis_read_not_additive",timing_relation="child_of_verify_native_time_axis_excludes_own_artifact_write"});
        if(!valid){
            bool incomplete=finite&&(times.Length<2||times[times.Length-1]<duration-1e-7);
            throw new CadFault(incomplete?"MOTION_RESULTS_INCOMPLETE":"NATIVE_TIME_AXIS_MISMATCH",incomplete?"原生结果未覆盖请求时段；请检查驱动与配合相容性，诊断和实际时间轴已保存。":"原生结果时间轴与请求网格不一致；诊断和完整时间轴已保存。",new {time_axis=diagnostic,time_axis_file=path,requested_grid=new{duration_s=duration,output_fps=fps},next_action=configurationChanged?"native_output_settings_changed_compare_requested_and_configured_no_automatic_retry":"review_native_time_axis_and_explicit_duration_fps_no_automatic_retry",native_output_grid_admission=NativeOutputGridPolicy.Describe(duration,fps),candidate_cause=(string)null,cause_status="not_proven_time_axis_cannot_identify_dead_point_or_offending_part",review_items=new[]{configurationChanged?"configured_output_fps_differs_from_requested_fps":"requested_and_native_output_settings_match", "selected_native_motor_and_relative_body","constraints_and_allowed_motion_range","explicit_duration_s_and_output_fps_within_new_solve_budget"},automatic_switch_motor_or_oscillation=false});
        }
        return times;
    }
}
