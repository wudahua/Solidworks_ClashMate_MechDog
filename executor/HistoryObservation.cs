using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    void ObserveHistory(UserModel model,StudyHistory.Observation observation,string stage) {
        var dirty=new List<object>();int opened=0,count=0;bool complete=true;int? hresult=null;
        try {
            foreach(var doc in (Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>()) {
                string path=doc.GetPathName();if(!model.Files.Contains(path,StringComparer.OrdinalIgnoreCase))continue;
                opened++;if(doc.GetSaveFlag()){count++;if(dirty.Count<8)dirty.Add(new{path=path,save_flag=true});}
            }
        } catch(COMException e){complete=false;hresult=e.HResult;}catch(InvalidCastException){complete=false;}
        observation.Record(stage,complete,opened,count,dirty.ToArray(),hresult);
    }
    Dictionary<string,string> HistoryCurrentHashes(UserModel model) {
        try{return model.Files.ToDictionary(p=>p,p=>FileHash(p));}catch(IOException){return null;}catch(UnauthorizedAccessException){return null;}
    }
    static Dictionary<string,object> HistorySettings(IMotionStudy study) {
        return new Dictionary<string,object>{{"type",study.StudyType},{"fps",((IMotionStudyProperties)study.GetProperties(study.StudyType)).GetFrameRate()},{"duration_s",study.GetDuration()}};
    }
    object TestHistoryState(string id,string name,string mode,int fps) {
        if(System.Environment.GetEnvironmentVariable("SW_MCP_FAULT_TESTS")!="1")throw new Exception("FAULT_TESTS_DISABLED");
        var model=GetUserModel(id);var doc=(IModelDoc2)Sw.GetOpenDocumentByName(model.Path);
        if(doc==null||!string.Equals(doc.GetPathName(),model.Path,StringComparison.OrdinalIgnoreCase))throw new Exception("OWNED_TEST_DOCUMENT_NOT_OPEN");
        OwnedPath(model.Path,"user_assemblies");
        var study=(IMotionStudy)((IMotionStudyManager)doc.Extension.GetMotionStudyManager()).GetMotionStudy(name);if(study==null)throw new Exception("STUDY_NOT_FOUND");
        int before=((IMotionStudyProperties)study.GetProperties(study.StudyType)).GetFrameRate();
        if(mode=="mark_dirty")doc.SetSaveFlag();
        else if(mode=="unsaved_fps") {
            if(fps<5||fps>120||fps==before)throw new Exception("INVALID_TEST_FPS");
            if(!((IMotionStudyProperties)study.GetProperties(study.StudyType)).SetFrameRate(fps))throw new Exception("TEST_FPS_SETUP_FAILED");
            doc.SetSaveFlag();
        } else if(mode=="activate_study") {if(!study.Activate()||!study.IsActive)throw new Exception("TEST_ACTIVATION_FAILED");}
        else throw new Exception("INVALID_TEST_MODE");
        return new{model_id=id,path=model.Path,mode=mode,fps_before=before,fps_after=((IMotionStudyProperties)study.GetProperties(study.StudyType)).GetFrameRate(),save_flag=doc.GetSaveFlag(),active=study.IsActive,saved=false};
    }
}
