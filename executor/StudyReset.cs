using System;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    public object ResetUserStudyTime(string id,string studyName,bool allowRecalculate=false) {
        var m=GetUserModel(id);
        if(!allowRecalculate){using(var probe=new Scope(this,m.Path,null)){var selected=(IMotionStudy)((IMotionStudyManager)probe.Doc.Extension.GetMotionStudyManager()).GetMotionStudy(studyName);if(selected==null)throw new CadFault("STUDY_NOT_FOUND","未找到所选算例。",new{study=studyName});if(Math.Abs(selected.GetTime())>1e-8&&(selected.StudyType==1||!selected.IsActive)){LastOperationRestoration="not_required";throw new CadFault("STUDY_RESET_REQUIRES_CALCULATION","非零动画或未激活算例可能缺少结果缓存；请显式允许重新计算后归零。没有激活、移动或保存该算例。",new{study=studyName,stage="preflight_nonzero_clock",time_s=selected.GetTime(),study_type=selected.StudyType,active=selected.IsActive,required_option="allow_recalculate=true",automatic_calculate=false,model_state_changed=false});}}}
        var cp=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(id)));
        string checkpoint=(string)cp["checkpoint_id"],stage="load_motion";var trace=new List<object>();LastOperationRestoration="pending";
        try {
            LoadUserMotion();using(var scope=new Scope(this,m.Path,null)) {
                var mgr=(IMotionStudyManager)scope.Doc.Extension.GetMotionStudyManager();
                var study=(IMotionStudy)mgr.GetMotionStudy(studyName);
                if(study==null)throw new CadFault("STUDY_NOT_FOUND","未找到所选算例。",new{study=studyName});
                var initial=StudyStates(scope.Doc).Single(s=>s.name==studyName);
                stage="stop";study.Stop();if(study.IsPlaying)throw new Exception("STUDY_PLAYING_STOP_REQUIRED");
                stage="activate";bool activated=study.IsActive||mgr.ActivateMotionStudy(studyName);Application.DoEvents();
                trace.Add(new{stage=stage,native_return=activated,active=study.IsActive,time_s=study.GetTime()});
                if(!activated||!study.IsActive)throw new Exception("STUDY_ACTIVATION_REJECTED");
                stage="set_time";bool selected=Math.Abs(study.GetTime())<=1e-8||study.SetTime(0);Application.DoEvents();study.Stop();
                trace.Add(new{stage=stage,native_return=selected,time_s=study.GetTime()});bool calculated=false;
                if(Math.Abs(study.GetTime())>1e-8) {
                    if(!allowRecalculate)throw new CadFault("STUDY_RESET_REQUIRES_CALCULATION","SolidWorks 拒绝设置原始算例时间；可显式允许有限预算的重新计算后归零。",new{study=studyName,stage=stage,required_option="allow_recalculate=true",automatic_calculate=false});
                    if(initial.duration_s<=0||initial.duration_s>30||initial.fps<1||initial.fps>120||initial.duration_s*initial.fps>1800)throw new CadFault("RESET_CALCULATION_BUDGET_EXCEEDED","原算例超过归零计算预算；未修改时长或帧率。",new{study=initial,maximum_duration_s=30,maximum_frames=1801});
                    stage="explicit_calculate";Progress(activeJobId,stage,0,0,null);calculated=study.Calculate();study.Stop();Application.DoEvents();study.Stop();
                    trace.Add(new{stage=stage,native_return=calculated,time_s=study.GetTime(),playing=study.IsPlaying});
                    if(!calculated)throw new Exception("SOLVER_FAILED");
                    stage="set_time_after_calculate";
                    for(int attempt=0;attempt<3;attempt++){study.Stop();selected=Math.Abs(study.GetTime())<=1e-8||study.SetTime(0);Application.DoEvents();study.Stop();trace.Add(new{stage=stage,attempt=attempt,native_return=selected,time_s=study.GetTime(),playing=study.IsPlaying});if(Math.Abs(study.GetTime())<=1e-8&&!study.IsPlaying)break;}
                }
                stage="verify";var actual=StudyStates(scope.Doc).Single(s=>s.name==studyName);
                if(Math.Abs(actual.time_s)>1e-8||!actual.active||study.IsPlaying||actual.type!=initial.type||actual.fps!=initial.fps||Math.Abs(actual.duration_s-initial.duration_s)>1e-8)throw new CadFault("STUDY_RESET_UNVERIFIED","归零后的时间、播放状态或算例设置未通过核对。",new{initial=initial,actual=actual,playing=study.IsPlaying});
                stage="save";SaveOwnedDocuments(m);Save(scope.Doc,m.Path);ObserveOwnedSave(m,"after_reset_save");m.Revision++;SaveUserModel(m);VerifyUserSources(m);LastOperationRestoration="restored";
                return new{model_id=id,study=studyName,time_s=actual.time_s,active=actual.active,previous_checkpoint_id=checkpoint,results_invalidated=true,restoration_status="restored",source_files_unchanged=true,recalculated_for_reset=calculated,study_settings_preserved=true,native_steps=trace,save_observation=SaveObservation(m)};
            }
        }catch(Exception failure) {
            var original=failure as CadFault;
            var diagnostics=new{study=studyName,stage=stage,checkpoint_id=checkpoint,native_steps=trace,original_code=HistoryErrorCode(failure),original_details=original==null?null:original.Diagnostics,native_hresult=failure is COMException?(int?)failure.HResult:null,native_message=failure.Message};
            try{RestoreUserCheckpoint(id,checkpoint);LastOperationRestoration="restored";}catch(Exception rollback){LastOperationRestoration="unknown";throw new CadFault("STUDY_RESET_ROLLBACK_FAILED","归零失败且检查点恢复未确认；保留现场并恢复检查点。",new{failure=diagnostics,rollback_error=rollback.ToString()});}
            throw new CadFault(original==null?"STUDY_TIME_RESET_FAILED":original.Code,original==null?"算例归零失败，已恢复检查点；请查看具体阶段。":original.Message,diagnostics);
        }
    }
}
