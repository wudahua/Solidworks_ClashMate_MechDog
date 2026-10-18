public static class HistoricalUsage {
    public static object ForRun(string id){return new{schema_version=1,scope="recorded_run_inputs_offline_artifact",default_summary_requires_verified_complete_sampling_and_restoration=true,
        default_verified_summary=new{tool="get_motion_summary",arguments=new{run_id=id},requires_verified_complete_sampling_and_restoration=true},
        quarantine_artifact_query=new{tool="get_run_artifacts",arguments=new{run_id=id},requires_verified_result=false,claim="diagnostic_read_does_not_assert_motion_pass"},
        offline_export_option="allow_unverified_history_required_only_for_inconclusive_runs",artifact_query=new{tool="get_run_artifacts",arguments=new{run_id=id}},
        current_model_validity="not_checked_offline",warning="offline history does not prove current CAD validity"};}
}
