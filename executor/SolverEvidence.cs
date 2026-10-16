using System;
using System.Collections.Generic;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    void ConfigureSolveSettings(IMotionStudy study,string modelId,string name,double duration,int fps) {
        var before=HistorySettings(study);bool active=study.IsActive,playing=study.IsPlaying;
        bool? durationAccepted=null,fpsAccepted=null;string stage="settings_read";
        try {
            var props=(IMotionStudyProperties)study.GetProperties(4);
            if(Math.Abs(study.GetDuration()-duration)>1e-8){stage="set_duration";durationAccepted=study.SetDuration(duration);}
            if(props.GetFrameRate()!=fps){stage="set_frame_rate";fpsAccepted=props.SetFrameRate(fps);}
            stage="settings_readback";var after=HistorySettings(study);
            if(study.StudyType!=4||Math.Abs(Convert.ToDouble(after["duration_s"])-duration)>1e-8||Convert.ToInt32(after["fps"])!=fps)
                throw new CadFault("SOLVER_SETTINGS_UNVERIFIED","算例设置回读未与请求一致；未调用求解器。",new{model_id=modelId,study=name,stage=stage,requested=new{type=4,duration_s=duration,output_fps=fps},before=before,after=after,native_returns=new{set_duration=durationAccepted,set_frame_rate=fpsAccepted},active=active,playing=playing,root_cause="not_proven",next_action="explicitly_retry_recorded_existing_settings_if_within_operation_budget_or_select_another_study",retry_existing_settings=new{duration_s=before["duration_s"],output_fps=before["fps"],automatic_retry=false,compatibility_probe_allowed=MotionBudgets.ProbeAllows(Convert.ToDouble(before["duration_s"]),Convert.ToInt32(before["fps"])),current_settings_may_have_changed=true}});
        } catch(CadFault){throw;}
        catch(Exception error){throw new CadFault("SOLVER_SETTINGS_UNVERIFIED","设置或回读算例时发生异常；未判定设置成功。",new{model_id=modelId,study=name,stage=stage,requested=new{type=4,duration_s=duration,output_fps=fps},before=before,native_returns=new{set_duration=durationAccepted,set_frame_rate=fpsAccepted},active=active,playing=playing,failure=FailureEvidence(error)});}
    }
    void RequireFreshSolveResults(IMotionStudy study,IMotionStudyResults results,string modelId,string name,string stage){
        if(results==null)throw new CadFault("RESULTS_STALE","原生求解未返回可读取结果对象。",new{model_id=modelId,study=name,stage=stage,native_calculate_return=true,result_object_returned=false,results_out_of_date=(bool?)null,settings=HistorySettings(study),active=study.IsActive,root_cause="not_proven"});
        bool stale=results.IsOutOfDate();
        if(stale)throw new CadFault("RESULTS_STALE","原生结果标为过期；保留诊断并恢复操作前状态。",new{model_id=modelId,study=name,stage=stage,native_calculate_return=true,result_object_returned=true,results_out_of_date=stale,settings=HistorySettings(study),active=study.IsActive,root_cause="not_proven",likely_causes=new[]{"study_inputs_or_solver_state_changed","drive_and_constraint_compatibility_requires_review"}});
    }
}
