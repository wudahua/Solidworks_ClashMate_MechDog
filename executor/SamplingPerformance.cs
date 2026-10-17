using System;
using System.Linq;
using System.Collections.Generic;

// Reduce existing measurements after sampling; no COM and no frame skipping.
public static class SamplingPerformance {
    public static object Summary(IEnumerable<Dictionary<string,object>> selection,IEnumerable<Dictionary<string,object>> pose,double wall,int frames){
        var totals=new Dictionary<string,double>();
        Action<string,IEnumerable<Dictionary<string,object>>> collect=(prefix,rows)=>{foreach(var row in rows)foreach(var pair in row){if(!pair.Key.EndsWith("_ms")||pair.Key=="total_ms")continue;string key=prefix+pair.Key;double value=Convert.ToDouble(pair.Value);totals[key]=totals.ContainsKey(key)?totals[key]+value:value;}};
        collect("selection.",selection);collect("pose_read.",pose);
        string dominant=totals.Count==0?null:totals.OrderByDescending(p=>p.Value).First().Key;
        return new{frames=frames,sampling_elapsed_ms=wall,mean_frame_ms=frames>0?wall/frames:0,stage_totals_ms=totals,dominant_measured_stage=dominant,dominant_stage_fraction_of_sampling=dominant==null||wall<=0?0:totals[dominant]/wall,unattributed_elapsed_ms=Math.Max(0,wall-totals.Values.Sum()),scope="selection_and_all_component_reads_plus_remaining_scope_checks_progress_and_managed_work",root_cause="not_proven_by_timing_alone",complete_component_checks_preserved=true,per_frame_hash_or_native_file_save=false};
    }
}
