using System;
using System.Collections.Generic;

// Retry only time selection. Never recalculate or repeat an assembly write.
public static class SolverTimeCapture {
    public static object Select(int frame,double requested,double argument,Func<bool> select,Func<double> clock,Func<bool> playing,Action stop,Action pump,Action activate) {
        var steps=new List<object>();
        for(int attempt=1;attempt<=2;attempt++) {
            activate();stop();double before=clock();bool native=select();pump();stop();pump();double actual=clock();bool active=playing();
            bool accepted=native&&!active&&!double.IsNaN(actual)&&!double.IsInfinity(actual)&&Math.Abs(actual-requested)<=1e-7;
            steps.Add(new{attempt=attempt,frame=frame,requested_time_s=requested,native_argument_s=argument,time_before_s=before,native_set_time_return=native,actual_time_s=actual,playing=active,accepted=accepted});
            if(accepted)return new{frame=frame,attempts=attempt,native_steps=steps.ToArray(),clock_tolerance_s=1e-7,recalculated=false};
        }
        throw new CadFault("SOLVER_TIME_SELECTION_FAILED","原生采样时间选择两次未通过返回值、时钟及停止状态核验；未自动重新求解，恢复核验成功后可显式重试。",new{stage="capture_solver_poses",frame=frame,requested_time_s=requested,native_argument_s=argument,native_steps=steps.ToArray(),maximum_attempts=2,clock_tolerance_s=1e-7,automatic_recalculate=false,retry_requires_confirmed_restoration=true,root_cause="not_proven"});
    }
}
