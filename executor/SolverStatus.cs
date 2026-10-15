using System;
using System.Linq;
using System.Collections.Generic;

public static class SolverEvidence {
    public static string FailedState(string state,string code){
        if(code=="MOTION_RESULTS_INCOMPLETE")return "incomplete";
        return state=="pending"?"not_started":state=="running"?"failed":state;
    }
}

