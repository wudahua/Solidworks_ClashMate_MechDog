using System;
using System.Collections.Generic;

// A component continuation cannot prove completion of its parent's other tasks.
// Stateless queries deliberately leave the model-level conclusion unknown.
public static class GeometryQueryScope {
    public static void Apply(Dictionary<string,object> response,string component,int modelComponents,int scopedComponents,bool scopeComplete,int pending) {
        bool filtered=!string.IsNullOrEmpty(component);
        response["query_scope"]=filtered?"single_component_from_face_offset":"all_top_level_components";
        response["scope_geometry_complete"]=scopeComplete;
        response["geometry_complete"]=!filtered&&scopeComplete;
        response["geometry_complete_scope"]="legacy_true_only_for_unfiltered_complete_scan_not_component_continuations";
        response["model_geometry_complete"]=filtered?(object)null:scopeComplete;
        response["model_scan_state"]=filtered?"unknown_client_must_retain_parent_pending_queue":scopeComplete?"complete_supported_scope":"incomplete_or_unresolved";
        response["model_total_components"]=modelComponents;
        response["scoped_component_count"]=scopedComponents;
        response["filtered_out_component_count"]=modelComponents-scopedComponents;
        response["total_scope"]=filtered?"scoped_component_observed_subset":scopeComplete?"observed_full_supported_scan":"observed_subset_not_full_model";
        response["query_completion_status"]=filtered?(scopeComplete?"component_scope_complete_model_unknown":"component_scope_partial_model_unknown"):(scopeComplete?"complete_supported_geometry":"partial_pending_or_unresolved");
        response["client_next_action"]=filtered?"merge_component_continuations_into_retained_parent_queue_never_clear_siblings":pending>0?"read_pages_then_continue_components_never_infer_missing_geometry":"read_pages_and_review_unresolved_scope";
        response["client_queue_contract"]=new{state_owner="client",service_model_pending_ledger=false,retain_parent_pending_queries=true,replace_only_processed_component_task=true,completion_requires="all_parent_tasks_and_their_continuations_and_cursor_pages_completed_and_no_unresolved_scopes",component_result_cannot_complete_parent=true,queue_binding="same_model_revision_configuration_and_query_filters_restart_after_edit_or_stale_cursor"};
        response["absence_of_kind_proven"]=false;
    }
}
