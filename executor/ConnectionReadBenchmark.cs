using System;
using System.Linq;
using System.Collections.Generic;
using System.Diagnostics;
public partial class Cad {
    public object CompareConnectionParameterReaders(string id) {
        if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TEST_DISABLED");
        var model=GetUserModel(id);
        using(var scope=new Scope(this,model.Path,null))using(var batch=new NativeCommandBatch(()=>Sw.CommandInProgress,v=>Sw.CommandInProgress=v)) {
            var doc=scope.Doc;var before=Transforms(doc);var flags=UserComponents(doc).ToDictionary(c=>c.Name2,c=>c.IsFixed());
            var timings=new List<object>();string expected=null;
            foreach(bool includeDiscardedReferences in new[]{true,false,false,true}) {
                var clock=Stopwatch.StartNew();string value=ImportMateParameters(doc,includeDiscardedReferences);clock.Stop();
                if(expected==null)expected=value;else if(expected!=value)throw new Exception("PARAMETER_READER_AB_BYTES_DIFFER");
                timings.Add(new{include_discarded_references=includeDiscardedReferences,elapsed_ms=clock.Elapsed.TotalMilliseconds,returned_json_bytes=System.Text.Encoding.UTF8.GetByteCount(value)});
            }
            var after=Transforms(doc);
            if(before.Count!=after.Count||before.Any(v=>!after.ContainsKey(v.Key)||!PoseValidation.Matches(v.Value,after[v.Key]))||UserComponents(doc).Any(c=>c.IsFixed()!=flags[c.Name2]))throw new Exception("PARAMETER_READER_AB_STATE_CHANGED");
            RequireMatesHealthy(doc);VerifyUserSources(model);
            return new{scope="same_document_same_complete_parameter_output_abba_readonly_not_whole_task_speed_claim",timings=timings,all_returned_bytes_equal=true,poses_fixed_and_sources_unchanged=true};
        }
    }
}
