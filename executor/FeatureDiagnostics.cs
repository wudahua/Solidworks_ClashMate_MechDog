using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public partial class Cad {
    object[] NativeFeatureDiagnostics(IModelDoc2 doc) {
        var rows=new List<object>();var f=(IFeature)doc.FirstFeature();
        while(f!=null){bool warning;int error=f.GetErrorCode2(out warning);if(error!=0)rows.Add(new{name=f.Name,native_feature_id=f.GetID(),native_feature_type=f.GetTypeName2(),native_error=error,native_error_enum="swFeatureError_e",native_error_name=Enum.GetName(typeof(swFeatureError_e),error)??"unknown_swFeatureError_value",native_error_message=error==1?"Unknown feature error; native API did not identify the cause":"Native feature error; inspect named feature in CAD",native_hresult=(int?)null,hresult_status="not_applicable_no_COM_exception",warning=warning,causal_origin="not_proven"});f=(IFeature)f.GetNextFeature();}
        return rows.ToArray();
    }
    object FeatureErrorGroups(object[] rows){return rows.Select(r=>Json.Deserialize<Dictionary<string,object>>(Json.Serialize(r))).GroupBy(r=>new{type=Convert.ToString(r["native_feature_type"]),code=Convert.ToInt32(r["native_error"]),warning=Convert.ToBoolean(r["warning"])}).Select(g=>new{native_feature_type=g.Key.type,native_error=g.Key.code,native_error_enum="swFeatureError_e",native_error_name=Enum.GetName(typeof(swFeatureError_e),g.Key.code),warning=g.Key.warning,count=g.Count(),feature_names=g.Take(8).Select(r=>r["name"]).ToArray(),feature_names_truncated=g.Count()>8}).ToArray();}
    void RequireResetBranchHealth(IModelDoc2 doc){bool rebuilt=doc.EditRebuild3();var rows=NativeFeatureDiagnostics(doc);if(!rebuilt||rows.Length>0)throw new CadFault("MODEL_PREFLIGHT_FAILED","新副本存在原生重建或特征错误；没有忽略错误继续归零。",new{stage="reset_branch_rebuild_preflight",native_rebuild_succeeded=rebuilt,feature_diagnostics=rows,feature_error_summary=FeatureErrorGroups(rows),causal_origin="not_proven_source_or_import_requires_separate_baseline"});}
}
