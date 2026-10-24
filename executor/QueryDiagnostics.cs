using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    internal long GeometryQueryTestBudgetMs=0;
    internal Action<object> GeometryQueryTestObserver=null;
    GeometryScanBudget NewGeometryBudget(double seconds=10){if(GeometryQueryTestBudgetMs>0&&System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new CadFault("FAULT_TESTS_DISABLED","几何预算注入仅允许显式测试环境。");return new GeometryScanBudget(GeometryQueryTestBudgetMs>0?GeometryQueryTestBudgetMs:(long)Math.Round(seconds*1000));}
    object[] NativeMateHealth(IModelDoc2 doc) {
        return BasicMateFeatures(doc).GroupBy(f=>f.GetID()).Select(g=>g.First()).Select(f=>{
            bool warning;int error=f.GetErrorCode2(out warning);
            return (object)new{name=f.Name,native_feature_id=f.GetID(),error=error,warning=warning,error_enum="swFeatureError_e",error_name=Enum.GetName(typeof(SolidWorks.Interop.swconst.swFeatureError_e),error)};
        }).ToArray();
    }
    object InspectUserComponents(string id) {
        var timing=new OperationTiming();timing.Start("model_manifest");var m=GetUserModel(id);
        timing.Start("open_scope");using(var scope=new Scope(this,m.Path,null)) {
            timing.Start("input_fingerprint");Fingerprint(scope.Doc,scope.DocumentPath);
            timing.Start("component_inventory");var components=InspectUserCore(m,scope.Doc);
            timing.Start("save_registration");SaveUserModel(m);timing.Finish();
            return new{model_id=id,detail_level="components",configuration=scope.Doc.ConfigurationManager.ActiveConfiguration.Name,
                components=components,mates=(object)null,mate_geometry_inspected=false,component_count=components.Length,
                fixed_state_source="IComponent2.IsFixed",host_timings=timing.Export(),
                timing_scope="method_body_before_scope_disposal_not_full_client_latency",
                next_step="use_component_id_to_filter_list_mate_references_or_list_drive_candidates",
                degrees_of_freedom_status="unknown"};
        }
    }
    // Pagination guard only. Not a replacement for a mate plan or checkpoint proof.
    object GeometryQueryObservation(UserModel m,IModelDoc2 doc) {
        var loaded=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>()
            .Where(d=>m.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase))
            .OrderBy(d=>d.GetPathName(),StringComparer.OrdinalIgnoreCase)
            .Select(d=>new{path=d.GetPathName(),stamp=d.GetUpdateStamp(),dirty=d.GetSaveFlag(),configuration=d.ConfigurationManager.ActiveConfiguration.Name}).ToArray();
        var observed=new{revision=m.Revision,configuration=doc.ConfigurationManager.ActiveConfiguration.Name,
            files=m.Files.OrderBy(p=>p,StringComparer.OrdinalIgnoreCase).ToDictionary(p=>p,p=>FileHash(p)),documents=loaded,
            components=ProbeWorkingState.ComponentIdentity(doc),poses=Transforms(doc).OrderBy(p=>p.Key,StringComparer.Ordinal).ToDictionary(p=>p.Key,p=>p.Value),studies=StudyStates(doc).OrderBy(s=>s.name,StringComparer.Ordinal).ToArray()};
        if(GeometryQueryTestObserver!=null){if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new CadFault("FAULT_TESTS_DISABLED","查询观测仅用于显式测试。");GeometryQueryTestObserver(observed);}
        return observed;
    }
    string GeometryQuerySignature(UserModel m,IModelDoc2 doc) {return StableId("query_",Json.Serialize(GeometryQueryObservation(m,doc)));}
    Dictionary<string,object> CircularQueryState(UserModel m,IModelDoc2 doc) {
        var observed=GeometryQueryObservation(m,doc);
        string data=Json.Serialize(observed),signature=StableId("query_",data);
        string path=Path.Combine(Root,"runs","circular-query-states",signature+".json");
        if(!File.Exists(path))AtomicMetadata.Write(path,data);
        else if(File.ReadAllText(path)!=data)throw new CadFault("CIRCULAR_STATE_EVIDENCE_COLLISION","状态证据标识冲突，停止推荐，不覆盖已有记录。");
        return new Dictionary<string,object>{{"model_revision",m.Revision},{"signature",signature},{"state_evidence",new{path="runs/circular-query-states/"+signature+".json",sha256=FileHash(path)}}};
    }
    object CheckpointProbeWithTiming(UserModel model,string planId,string checkpointId) {
        var timing=new OperationTiming();Dictionary<string,object> result=null;Exception failure=null;Scope scope=null;
        try {
            timing.Start("write_stage");WriteStage("checkpoint_probe",model.Id,planId,checkpointId);
            timing.Start("open_scope");scope=new Scope(this,model.Path,null);
            timing.Start("probe_core");result=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CheckAnimationCheckpoint(model,checkpointId)));
        }catch(Exception error){failure=error;var fault=error as CadFault;if(fault!=null&&fault.Diagnostics!=null)result=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(fault.Diagnostics));}
        finally {timing.Start("dispose_scope");try{if(scope!=null)scope.Dispose();}catch(Exception error){failure=error;LastOperationRestoration="unknown";}timing.Finish();}
        result=result??new Dictionary<string,object>();result["wrapper_timings"]=timing.Export();
        result["timing_scope"]="elapsed_ms_and_host_timings_are_probe_core_only_wrapper_timings_include_open_and_dispose";
        if(failure!=null)throw new CadFault(HistoryErrorCode(failure),failure.Message,result);
        return result;
    }
}
