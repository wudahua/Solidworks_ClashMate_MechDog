using System;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;

// Exclusive monotonic phases. Nested sampling/probe measurements are not added
// to these totals. This observer never calls COM or changes a solver decision.
public sealed class SolvePerformance {
    readonly Func<double> clock;
    readonly double start;
    double boundary,end;
    string current="entry_validation";
    bool finished;
    readonly Dictionary<string,double> totals=new Dictionary<string,double>();
    readonly List<string> order=new List<string>();
    public SolvePerformance(Func<double> readClock=null){var timer=Stopwatch.StartNew();clock=readClock??(()=>timer.Elapsed.TotalMilliseconds);start=boundary=clock();}
    public void Phase(string name){if(finished)throw new InvalidOperationException("Timing already finished");double now=clock();if(now<boundary)throw new InvalidOperationException("Timing clock moved backwards");Add(current,now-boundary);boundary=now;current=name;}
    void Add(string name,double ms){if(!totals.ContainsKey(name)){totals[name]=0;order.Add(name);}totals[name]+=ms;}
    public object Finish(bool success){if(!finished){end=clock();if(end<boundary)throw new InvalidOperationException("Timing clock moved backwards");Add(current,end-boundary);finished=true;}
        double wall=end-start,measured=totals.Values.Sum();return new{schema_version=1,operation="RunUserStudy",execution_completed=success,total_elapsed_ms=wall,attributed_elapsed_ms=measured,unattributed_elapsed_ms=Math.Max(0,wall-measured),phase_totals_ms=new Dictionary<string,double>(totals),phase_order=order.ToArray(),clock="Stopwatch_monotonic",phase_relationship="exclusive_sequential_phases_do_not_add_nested_sampling_or_probe_totals",scope="native_RunUserStudy_wrapper_entry_through_core_return_or_failure_including_scope_restoration",excluded=new[]{"executor_startup","outer_request_dispatch_and_serialization","final_timing_publication"},root_cause="not_proven_by_timing_alone"};}
}
