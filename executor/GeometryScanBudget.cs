using System;
using System.Collections.Generic;
using System.Diagnostics;

// Cooperative: never cancels an in-flight native call or claims a hard deadline.
public sealed class GeometryScanBudget {
    public static bool ValidSeconds(double seconds){return !double.IsNaN(seconds)&&!double.IsInfinity(seconds)&&seconds>=1&&seconds<=60;}
    readonly Stopwatch timer=Stopwatch.StartNew();readonly Func<long> clock;
    long? finished;public readonly long MaximumMs;public bool Exhausted;public int ReadFaces;
    public GeometryScanBudget(long maximumMs=10000,Func<long> elapsed=null){if(maximumMs<1)throw new ArgumentException("SCAN_BUDGET_INVALID");MaximumMs=maximumMs;clock=elapsed??(()=>timer.ElapsedMilliseconds);}
    public bool Continue(){if(clock()>=MaximumMs)Exhausted=true;return !Exhausted;}
    public void Finish(){finished=clock();}
    public object Export(object nextQueries,int pendingQueries,bool componentScoped=false){long elapsed=finished??clock();return new{cooperative_budget_ms=MaximumMs,elapsed_ms=elapsed,budget_overrun_ms=Math.Max(0,elapsed-MaximumMs),scan_budget_exhausted=Exhausted,read_faces=ReadFaces,budget_scope="candidate_geometry_only_separate_from_mate_context_and_state_validation",native_call_cannot_be_interrupted=true,scan_determinism="budget_bounded_observed_subset_may_vary_with_native_latency",geometry_scan_budget_s=MaximumMs/1000.0,geometry_budget_change_requires_new_scan=true,next_queries=nextQueries,pending_query_count=componentScoped?(int?)null:pendingQueries,scope_pending_query_count=pendingQueries,pending_query_count_scope=componentScoped?"unknown_parent_queue_not_carried_by_this_call":"this_unfiltered_scan_only",continuation_scope="native_face_offset_same_model_state_restart_after_edit",partial_is_not_absence_proof=true,client_must_continue_until_pending_query_count_zero=!componentScoped,client_must_retain_parent_pending_queue=true,component_completion_does_not_clear_siblings=true,missing_kind_is_not_absence_proof=true,next_query_limit=5,next_queries_truncated=pendingQueries>5,when_next_queries_truncated="inspect_model components and query all remaining components individually; never infer virtual components have no geometry",continuation_instructions="Keep the complete parent pending queue across calls. Read all next_cursor pages. Replace ONLY the processed component task with this call's next_queries; retain siblings. Complete only when the CLIENT queue is empty, all pages read and no unresolved scope. Scoped zero is not model zero. Restart after edits or stale state."};}
}
