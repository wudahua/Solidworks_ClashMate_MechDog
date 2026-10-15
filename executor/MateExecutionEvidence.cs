using System;
using System.Collections.Generic;
using SolidWorks.Interop.swconst;

public sealed class MateExecutionEvidence {
    readonly System.Diagnostics.Stopwatch timer=System.Diagnostics.Stopwatch.StartNew();
    readonly List<object> timings=new List<object>();string stage="preflight";long stageStart;
    public string FailureStage;
    public string Stage {get{return stage;}set{timings.Add(new{stage=stage,elapsed_ms=timer.ElapsedMilliseconds-stageStart});stage=value;stageStart=timer.ElapsedMilliseconds;}}

    public int? NativeError;
    public bool? NativeObjectReturned,NativeFeatureObserved,RebuildAccepted,ParametersVerified;
    public bool SaveCompleted,WriteCommitted;
    public static string ErrorName(int error){return Enum.GetName(typeof(swAddMateError_e),error)??"unknown_swAddMateError_value";}
    public static string ErrorMessage(int error){switch(error){case 0:return "SolidWorks 未提供明确的配合失败原因。";case 1:return "原生添加配合调用报告成功。";case 2:return "配合类型不被原生接口接受。";case 3:return "配合方向不被原生接口接受。";case 4:return "配合参考选择不正确或不满足类型要求。";case 5:return "新增配合使装配过定义；需要复核已有配合与所选参考。";case 6:return "齿轮配合比例不正确。";default:return "未识别的原生添加配合状态；未判定创建成功。";}}
    public object Export(){return new{stage=Stage,failure_stage=WriteCommitted?null:FailureStage??Stage,total_elapsed_ms=timer.ElapsedMilliseconds,stage_timings=timings.ToArray(),current_stage_elapsed_ms=timer.ElapsedMilliseconds-stageStart,add_mate_status=NativeError.HasValue?(NativeError.Value==1?"native_call_accepted":"native_call_rejected"):"not_called",rebuild_status=RebuildAccepted.HasValue?(RebuildAccepted.Value?"accepted_health_separate":"rejected"):"not_checked",transaction_outcome=WriteCommitted?"committed":"not_committed",native_error=NativeError,native_error_enum="swAddMateError_e",native_error_name=NativeError.HasValue?ErrorName(NativeError.Value):null,native_error_message=NativeError.HasValue?ErrorMessage(NativeError.Value):null,native_object_returned=NativeObjectReturned,native_feature_observed=NativeFeatureObserved,native_rebuild_accepted=RebuildAccepted,native_parameters_verified=ParametersVerified,save_completed=SaveCompleted,write_committed=WriteCommitted,mate_created=NativeObjectReturned,mate_created_semantics="legacy_native_object_nonnull_not_feature_or_commit_success",null_means="not_checked"};}
}
