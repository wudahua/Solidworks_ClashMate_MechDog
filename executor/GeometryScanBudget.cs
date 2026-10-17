using System;
using System.Collections.Generic;
using System.Diagnostics;

// Cooperative: never cancels an in-flight native call or claims a hard deadline.
public sealed class GeometryScanBudget {
    readonly Stopwatch timer=Stopwatch.StartNew();readonly Func<long> clock;
    long? finished;public readonly long MaximumMs;public bool Exhausted;public int ReadFaces;
    public GeometryScanBudget(long maximumMs=10000,Func<long> elapsed=null){if(maximumMs<1)throw new ArgumentException("SCAN_BUDGET_INVALID");MaximumMs=maximumMs;clock=elapsed??(()=>timer.ElapsedMilliseconds);}
    public bool Continue(){if(clock()>=MaximumMs)Exhausted=true;return !Exhausted;}
    public void Finish(){finished=clock();}
    public object Export(object nextQueries,int pendingQueries){long elapsed=finished??clock();return new{cooperative_budget_ms=MaximumMs,elapsed_ms=elapsed,budget_overrun_ms=Math.Max(0,elapsed-MaximumMs),scan_budget_exhausted=Exhausted,read_faces=ReadFaces,budget_scope="candidate_geometry_only_separate_from_mate_context_and_state_validation",native_call_cannot_be_interrupted=true,next_queries=nextQueries,pending_query_count=pendingQueries,continuation_scope="native_face_offset_same_model_state_restart_after_edit",partial_is_not_absence_proof=true};}
}
