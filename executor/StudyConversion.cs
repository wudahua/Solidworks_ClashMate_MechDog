using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    public object ConvertUserStudy(string id,string studyName) {using(var saveObservationScope=BeginSaveObservationOperation("convert_motion_study")){
        var m=GetUserModel(id);var cp=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(id)));LoadUserMotion();
        try{using(var s=new Scope(this,m.Path,null)) {
            var study=(IMotionStudy)((IMotionStudyManager)s.Doc.Extension.GetMotionStudyManager()).GetMotionStudy(studyName);
            if(study==null)throw new CadFault("STUDY_NOT_FOUND","未找到需要转换的算例。",new{model_id=id,study=studyName,required_tool="list_motion_studies"});var before=HistorySettings(study);int previous=study.StudyType;
            study.StudyType=4;if(study.StudyType!=4)throw new Exception("MOTION_LICENSE_UNAVAILABLE");var automatic=HistorySettings(study);
            bool fpsRequest=true,durationRequest=true;var props=(IMotionStudyProperties)study.GetProperties(4);
            if(props.GetFrameRate()!=Convert.ToInt32(before["fps"]))fpsRequest=props.SetFrameRate(Convert.ToInt32(before["fps"]));
            if(Math.Abs(study.GetDuration()-Convert.ToDouble(before["duration_s"]))>1e-8)durationRequest=study.SetDuration(Convert.ToDouble(before["duration_s"]));
            var after=HistorySettings(study);bool preserved=Convert.ToInt32(after["fps"])==Convert.ToInt32(before["fps"])&&Math.Abs(Convert.ToDouble(after["duration_s"])-Convert.ToDouble(before["duration_s"]))<=1e-8;
            WriteStage("conversion_save");Save(s.Doc,m.Path);ObserveOwnedSave(m,"after_conversion_save");m.Revision++;SaveUserModel(m);return new{model_id=id,study=studyName,previous_type=previous,current_type=4,checkpoint_id=cp["checkpoint_id"],settings_before=before,native_settings_after_type_change=automatic,settings_after=after,requested_fps_preservation_accepted=fpsRequest,requested_duration_preservation_accepted=durationRequest,output_settings_preserved=preserved,warnings=preserved?new string[0]:new[]{"NATIVE_CONVERSION_CHANGED_OUTPUT_SETTINGS"},results_invalidated=true,save_observation=SaveObservation(m)};
        }}catch{RestoreUserCheckpoint(id,(string)cp["checkpoint_id"]);throw;}
    }}
}
