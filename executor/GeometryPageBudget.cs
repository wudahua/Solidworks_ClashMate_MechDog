using System;
using System.Text;
using System.Collections.Generic;

// Pure pagination policy. Geometry completeness is independent of page end.
public static class GeometryPageBudget {
    public static void Apply(Dictionary<string,object> response,List<Dictionary<string,object>> page,int offset,int total,int requested,Func<int,string> cursor,Func<object,string> serialize,int budget=16000){
        if(offset<0||offset>total||page.Count>total-offset)throw new InvalidOperationException("page_range_invalid");
        response["entities"]=page;response["requested_limit"]=requested;response["payload_budget_bytes"]=budget;
        response["page_reduction_reason"]=null;
        while(true){
            int next=checked(offset+page.Count);bool more=next<total;
            if(more&&page.Count==0)throw new InvalidOperationException("empty_page_cannot_advance");
            string token=more?cursor(next):null;
            if(more&&(string.IsNullOrEmpty(token)||token==cursor(offset)))throw new InvalidOperationException("cursor_did_not_advance");
            response["returned"]=page.Count;response["next_offset"]=more?(object)next:null;
            response["next_offset_delta"]=more?page.Count:0;response["next_cursor"]=token;
            response["frozen_pages_complete"]=!more;
            if(Encoding.UTF8.GetByteCount(serialize(response))<=budget)return;
            if(page.Count<=1)throw new InvalidOperationException("metadata_and_single_entity_exceed_budget");
            page.RemoveAt(page.Count-1);response["page_reduction_reason"]="payload_byte_budget";
        }
    }
}
