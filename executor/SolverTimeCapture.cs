using System;
using System.Collections.Generic;

// Retry only time selection. Never recalculate or repeat an assembly write.
public static class SolverTimeCapture {
    public static object Select(int frame,double requested,double argument,Func<bool> select,Func<double> clock,Func<bool> playing,Action stop,Action pump,Action activate,Dictionary<string,object> profile=null) {
        var steps=new List<object>();
        var timer=System.Diagnostics.Stopwatch.StartNew();var timings=new Dictionary<string,double>();
        Action<string,Action> measured=(name,action)=>{long before=timer.ElapsedTicks;try{action();}finally{double ms=(timer.ElapsedTicks-before)*1000.0/System.Diagnostics.Stopwatch.Frequency;timings[name]=timings.ContainsKey(name)?timings[name]+ms:ms;}};
        for(int attempt=1;attempt<=2;attempt++) {
            double before=0,actual=0;bool native=false,active=false;
            measured("activate_scope_ms",activate);measured("stop_before_ms",stop);measured("clock_before_ms",()=>before=clock());measured("set_time_ms",()=>native=select());measured("pump_after_select_ms",pump);measured("stop_after_ms",stop);measured("pump_after_stop_ms",pump);measured("clock_after_ms",()=>actual=clock());measured("playing_check_ms",()=>active=playing());
            if(profile!=null){foreach(var pair in timings)profile[pair.Key]=pair.Value;profile["total_ms"]=timer.Elapsed.TotalMilliseconds;profile["attempts"]=attempt;profile["scope"]="measured_selection_native_calls_and_message_pumps_no_per_frame_file_hash_or_save";}
            bool accepted=native&&!active&&!double.IsNaN(actual)&&!double.IsInfinity(actual)&&Math.Abs(actual-requested)<=1e-7;
            steps.Add(new{attempt=attempt,frame=frame,requested_time_s=requested,native_argument_s=argument,time_before_s=before,native_set_time_return=native,actual_time_s=actual,playing=active,accepted=accepted});
            if(accepted)return new{frame=frame,attempts=attempt,native_steps=steps.ToArray(),clock_tolerance_s=1e-7,recalculated=false};
        }
        throw new CadFault("SOLVER_TIME_SELECTION_FAILED","原生采样时间选择两次未通过返回值、时钟及停止状态核验；未自动重新求解，恢复核验成功后可显式重试。",new{stage="capture_solver_poses",frame=frame,requested_time_s=requested,native_argument_s=argument,native_steps=steps.ToArray(),maximum_attempts=2,clock_tolerance_s=1e-7,clock_offset_is_observation_not_root_cause=true,first_frame_zero_selection_attempted=frame==0&&Math.Abs(requested)<=1e-8,automatic_recalculate=false,retry_requires_confirmed_restoration=true,root_cause="not_proven"});
    }
}
