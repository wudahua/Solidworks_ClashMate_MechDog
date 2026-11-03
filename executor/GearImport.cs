using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public partial class Cad {
    // Shared copy isolation policy; this does not infer gear roles or intent.
    public object ImportGearAssembly(string source,bool materializeVirtual,string copyId=null) {
        return ImportNamedOwnedAssembly(source,materializeVirtual,copyId,false);
    }
    public object ImportConstraintAssembly(string source,bool materializeVirtual,string copyId=null) {
        return ImportNamedOwnedAssembly(source,materializeVirtual,copyId,true);
    }
    object ImportNamedOwnedAssembly(string source,bool materializeVirtual,string copyId,bool constraintScope) {
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)
            throw new CadFault("MODEL_PREFLIGHT_FAILED","保名导入要求本次专用空实例，未关闭或替换任何已有文档。");
        if(materializeVirtual)throw new CadFault(constraintScope?"CONNECTION_SCOPE_UNSUPPORTED":"EXTERNAL_GEAR_SCOPE_UNSUPPORTED","保名导入目前要求外部零件，不静默外部化虚拟组件。");
        int option=(int)swUserPreferenceToggle_e.swUseFolderAsDefaultSearchLocation;
        bool original=Sw.GetUserPreferenceToggle(option);
        try {
            Sw.SetUserPreferenceToggle(option,false);
            if(Sw.GetUserPreferenceToggle(option))throw new CadFault("MODEL_PREFLIGHT_FAILED","无法暂时停用本实例的 Toolbox 自动替换，未打开模型。");
            return ImportUserAssembly(source,null,null,null,copyId,false,true);
        }finally {
            Sw.SetUserPreferenceToggle(option,original);
            if(Sw.GetUserPreferenceToggle(option)!=original)
                throw new CadFault("MODEL_PREFLIGHT_FAILED","Toolbox 搜索选项恢复未通过，保留诊断。",new{stage="gear_import_preference_restore",expected=original});
        }
    }
    void PrepareGearCopyMetadata(UserModel model) {
        var changes=new List<object>();
        int completed=0;foreach(string path in model.Files.Where(p=>p.EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase))) {
            Progress(activeJobId,"prepare_gear_copy_metadata",completed++,model.Files.Length,null);int error=0,warning=0;var doc=Sw.OpenDoc6(path,1,1,"",ref error,ref warning) as IModelDoc2;
            if(doc==null||!String.Equals(doc.GetPathName(),path,StringComparison.OrdinalIgnoreCase))
                throw new CadFault("MODEL_PREFLIGHT_FAILED","副本零件预加载身份不符，未保存其他路径。",new{requested_path=path,actual_path=doc==null?null:doc.GetPathName(),native_error=error,native_warning=warning});
            if((Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Any(d=>!model.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)))
                throw new CadFault("MODEL_PREFLIGHT_FAILED","副本预加载带入外部文档，停止写入。",new{stage="gear_copy_metadata_isolation"});
            int before=doc.Extension.ToolboxPartType;
            if(before==0)continue;
            doc.Extension.ToolboxPartType=0;
            if(doc.Extension.ToolboxPartType!=0)throw new CadFault("MODEL_PREFLIGHT_FAILED","副本 Toolbox 标记清理未生效。");
            Save(doc,path);changes.Add(new{path=path,before=before,after=0,scope="copy_only_toolbox_metadata_not_geometry_or_original_library"});
        }
        // Metadata preparation can load the assembly through in-context references.
        // Discard that cache; the actual import must reopen the prepared disk copies.
        Progress(activeJobId,"reload_after_gear_copy_metadata",0,0,null);CloseUserDocuments(model.Files);
        if((Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new CadFault("MODEL_PREFLIGHT_FAILED","副本元数据准备后仍有文档加载，未混用旧缓存。",new{stage="gear_copy_cache_close"});
        VerifyUserSources(model);
        AtomicJson(Path.Combine(model.Directory,"gear-copy-preparation.json"),new{naming="original_basename_in_unique_owned_directory",toolbox_copy_metadata_changes=changes,
            source_and_global_library_written=false,reason="preserve_component_pattern_names_and_prevent_library_substitution_on_reopen"});
    }
    string ImportMateParameters(IModelDoc2 doc,bool includeReferenceCalculation=false) {
        return ProbeWorkingState.MateParameters(doc,includeReferenceCalculation);
    }
}
