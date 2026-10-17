using System;
using System.Collections.Generic;

public static class ProbeWorkerSummary {
    // Never infer the managed helper status from the CAD application's exit code.
    public static object Project(Dictionary<string,object> record,string path,string sha){
        var result=new Dictionary<string,object>();
        foreach(string key in new[]{"completed","success","managed_operation_success","cleanup_verified","owned_solidworks_pid","owned_process_exited","native_exit_code","native_exit_code_process","worker_exit_code","worker_exit_code_process","exit_code_contract","worker_host_observation_path","worker_host_observation_sha256","failure_stage","failure_hresult","automatic_reconnect_or_retry"}){
            object value;result[key]=record.TryGetValue(key,out value)?value:null;
        }
        result["full_record_path"]=path;result["full_record_sha256"]=sha;result["missing_fields_are_unknown_not_derived_from_other_exit_code"]=true;
        return result;
    }
}
