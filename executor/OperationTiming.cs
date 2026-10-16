using System;
using System.Collections.Generic;
using System.Diagnostics;

// Monotonic, sequential phases. Nested worker durations must not be summed with these.
public sealed class OperationTiming {
    readonly Stopwatch timer=Stopwatch.StartNew();readonly List<object> rows=new List<object>();string stage;long start;
    public void Start(string name){Finish();stage=name;start=timer.ElapsedMilliseconds;}
    public void Finish(){if(stage==null)return;rows.Add(new{stage=stage,elapsed_ms=timer.ElapsedMilliseconds-start});stage=null;}
    public object Export(){return new{phases=rows.ToArray(),total_elapsed_ms=timer.ElapsedMilliseconds,current_stage=stage,current_stage_elapsed_ms=stage==null?0:timer.ElapsedMilliseconds-start,clock="monotonic_stopwatch",claim="timing_only_not_native_completion_proof"};}
}
