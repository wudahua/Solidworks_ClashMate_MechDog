using System;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.Web.Script.Serialization;

// Serializable observations only: never retain COM proxies between requests.
public sealed class GeometryPageSnapshots {
    sealed class Entry { public string Query,Guard,Payload; public DateTime Created; public int Bytes; }
    readonly Dictionary<string,Entry> entries=new Dictionary<string,Entry>();
    readonly JavaScriptSerializer json=new JavaScriptSerializer {MaxJsonLength=16777216};
    readonly Func<DateTime> now;
    public GeometryPageSnapshots(Func<DateTime> clock=null){now=clock??(()=>DateTime.UtcNow);}
    void Expire(){foreach(var key in entries.Where(p=>(now()-p.Value.Created).TotalMinutes>=10).Select(p=>p.Key).ToArray())entries.Remove(key);}
    public string Put(string query,string guard,object payload){
        Expire();string data=json.Serialize(payload);int bytes=Encoding.UTF8.GetByteCount(data);
        if(bytes>8388608)throw new InvalidOperationException("snapshot_exceeds_8MiB");
        while(entries.Count>=8||entries.Values.Sum(v=>v.Bytes)+bytes>16777216){entries.Remove(entries.OrderBy(p=>p.Value.Created).First().Key);}
        string id=Guid.NewGuid().ToString("N");entries[id]=new Entry{Query=query,Guard=guard,Payload=data,Bytes=bytes,Created=now()};return id;
    }
    public Dictionary<string,object> Get(string id,string query,string guard){
        Expire();Entry entry;
        if(!entries.TryGetValue(id,out entry))throw new InvalidOperationException("snapshot_expired_evicted_or_executor_restarted");
        if(entry.Query!=query)throw new InvalidOperationException("query_options_changed");
        if(entry.Guard!=guard)throw new InvalidOperationException("model_input_or_live_state_changed");
        return json.Deserialize<Dictionary<string,object>>(entry.Payload);
    }
}

public partial class Cad {
    readonly GeometryPageSnapshots geometryPages=new GeometryPageSnapshots();
    string GeometryPageQuery(string tool,UserModel m,string component,string kind,bool compact,int faceOffset,double budget,bool grouped,double geometryBudgetS=10){
        return Json.Serialize(new{tool=tool,model_id=m.Id,component_id=component??"",kind=kind??"",compact=compact,face_offset=faceOffset,mate_context_budget_s=budget,group_faces=grouped,geometry_scan_budget_s=geometryBudgetS});
    }
    static string GeometryPageCursor(string snapshot,int offset){return Convert.ToBase64String(Encoding.UTF8.GetBytes(Json.Serialize(new{snapshot_id=snapshot,offset=offset})));}
    object ContinueGeometryPage(UserModel m,SolidWorks.Interop.sldworks.IModelDoc2 doc,string query,string cursor,int limit,string tool,OperationTiming timing){
        string snapshot;int offset;
        try{if(cursor.Length>4096)throw new Exception();var token=Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(Convert.FromBase64String(cursor)));snapshot=(string)token["snapshot_id"];if(!(token["offset"] is int))throw new Exception();offset=(int)token["offset"];if(offset<0)throw new Exception();}
        catch{throw new CadFault(tool=="list_mate_references"?"MATE_CURSOR_STALE":"CANDIDATE_CURSOR_STALE","游标格式无效或来自旧版执行器，请从第一页查询。",new{cause="invalid_or_legacy_snapshot_cursor",required_cursor=""});}
        timing.Start("pagination_state_guard");Dictionary<string,object> frozen;
        try{frozen=geometryPages.Get(snapshot,query,GeometryQuerySignature(m,doc));}
        catch(InvalidOperationException error){throw new CadFault(tool=="list_mate_references"?"MATE_CURSOR_STALE":"CANDIDATE_CURSOR_STALE","冻结扫描已过期、查询参数或模型状态改变，请重新查询第一页；未重新扫描或拼接候选。",new{cause=error.Message,required_cursor="",model_id=m.Id});}
        var response=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(frozen["response"]));
        var entities=Json.Deserialize<List<Dictionary<string,object>>>(Json.Serialize(frozen["entities"]));
        var references=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(frozen["references"]));
        if(offset>entities.Count)throw new CadFault(tool=="list_mate_references"?"MATE_CURSOR_STALE":"CANDIDATE_CURSOR_STALE","分页位置超出冻结扫描。",new{cause="offset_out_of_range"});
        timing.Start("page_selection_and_registration");var page=entities.Skip(offset).Take(limit).ToList();
        response["scan_host_timings"]=response["host_timings"];response["host_timings_alias_scope"]="original_scan_legacy_alias_not_current_page";
        response["pagination_snapshot"]=new{id=snapshot,mode="immutable_observed_subset",expires_after_minutes=10,capacity=8,state_guard="saved_files_loaded_document_stamps_configuration_components_all_poses_and_studies",geometry_rescanned=false,scan_timings_scope="original_scan_not_current_page"};
        response["offset"]=offset;response["total_semantics"]="frozen_observed_subset_not_model_total";
        timing.Finish();response["page_host_timings"]=timing.Export();response["page_timing_scope"]="page_guard_and_selection_excludes_registration_and_disposal";
        BoundGeometryPage(response,page,offset,entities.Count,limit,next=>GeometryPageCursor(snapshot,next));
        foreach(var row in page)RegisterEntity(m,(string)row["entity_id"],references[(string)row["entity_id"]],(string)row["component_id"],(string)row["kind"]);
        SaveUserModel(m);return response;
    }
    object FreezeGeometryPage(UserModel m,string query,string guard,Dictionary<string,object> response,List<Dictionary<string,object>> entities,Dictionary<string,string> references,int limit){
        string snapshot;
        try{snapshot=geometryPages.Put(query,guard,new{response=response,entities=entities,references=references});}
        catch(InvalidOperationException error){throw new CadFault("GEOMETRY_RESPONSE_BUDGET_EXCEEDED","冻结扫描超过内存预算，请显式按组件查询。",new{cause=error.Message,automatic_retry=false});}
        response["scan_host_timings"]=response["host_timings"];response["host_timings_alias_scope"]="original_scan_legacy_alias_not_current_page";
        response["total_semantics"]="frozen_observed_subset_not_model_total";
        response["pagination_snapshot"]=new{id=snapshot,mode="immutable_observed_subset",expires_after_minutes=10,capacity=8,state_guard="saved_files_loaded_document_stamps_configuration_components_all_poses_and_studies",geometry_rescanned=true};
        var page=entities.Take(limit).ToList();response["offset"]=0;
        BoundGeometryPage(response,page,0,entities.Count,limit,next=>GeometryPageCursor(snapshot,next));
        foreach(var row in page)RegisterEntity(m,(string)row["entity_id"],references[(string)row["entity_id"]],(string)row["component_id"],(string)row["kind"]);
        SaveUserModel(m);return response;
    }
}
