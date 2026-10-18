using System;
using System.Collections.Generic;
using System.Diagnostics;

// Monotonic, sequential phases. Nested worker durations must not be summed with these.
public sealed class OperationTiming {
    readonly string scope;
    public OperationTiming(string scope="instrumented_query_body_sequential_phases"){this.scope=scope;}
    readonly Stopwatch timer=Stopwatch.StartNew();readonly List<object> rows=new List<object>();string stage;long start,finished,accounted;
    public void Start(string name){Finish();stage=name;start=timer.ElapsedMilliseconds;}
    public void Finish(){if(stage==null)return;finished=timer.ElapsedMilliseconds;long duration=finished-start;accounted+=duration;rows.Add(new{stage=stage,elapsed_ms=duration});stage=null;}
    public object Export(){long total=stage==null?finished:timer.ElapsedMilliseconds;return new{schema_version=1,scope=scope,excluded=new[]{"executor_startup","phases_after_last_finish","outer_serialization_and_transport","client_rendering"},phases=rows.ToArray(),total_elapsed_ms=total,current_stage=stage,current_stage_elapsed_ms=stage==null?0:total-start,unattributed_elapsed_ms=Math.Max(0,total-accounted-(stage==null?0:total-start)),clock="monotonic_stopwatch",total_scope=stage==null?"through_last_finished_phase_frozen":"current_observation",claim="timing_only_not_native_completion_proof"};}
}
