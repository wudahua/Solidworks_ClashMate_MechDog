using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Globalization;
using System.Collections.Generic;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    string ReplayCurrentContext(UserModel model) {
        var doc=Sw.GetOpenDocumentByName(model.Path) as IModelDoc2;
        return Json.Serialize(new{files=model.Files.ToDictionary(p=>p,p=>File.Exists(p)?FileHash(p):null),
            active=(Sw.ActiveDoc as IModelDoc2)==null?null:((IModelDoc2)Sw.ActiveDoc).GetPathName(),
            loaded=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Where(d=>model.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)).OrderBy(d=>d.GetPathName()).Select(d=>new{path=d.GetPathName(),stamp=d.GetUpdateStamp(),dirty=d.GetSaveFlag(),configuration=d.ConfigurationManager.ActiveConfiguration.Name}).ToArray(),
            poses=doc==null?null:Transforms(doc),studies=doc==null?null:StudyStates(doc),
            components=doc==null?null:ProbeWorkingState.ComponentIdentity(doc),mates=doc==null?null:ProbeWorkingState.MateIdentity(doc)});
    }
    public object ReplayFrozenSnapshot(string runId,int frame) {
        if(!System.Text.RegularExpressions.Regex.IsMatch(runId??"","^[a-f0-9]{32}$")||frame<0)throw new Exception("INVALID_REPLAY_OPTIONS");
        string directory=Path.Combine(Root,"runs",runId);ProbeOwnedPath(directory,Path.Combine(Root,"runs"));
        string solve=ProbeOwnedPath(Path.Combine(directory,"solve.json"),directory),csv=ProbeOwnedPath(Path.Combine(directory,"component-poses.csv"),directory);
        var saved=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(solve));
        if((string)saved["run_id"]!=runId||(string)saved["result_validity"]!="verified"||FileHash(csv)!=(string)saved["poses_sha256"])throw new CadFault("REPLAY_HISTORY_NOT_VERIFIED","历史结果或采样哈希未通过核验，未启动回放。");
        if(!saved.ContainsKey("replay_input_snapshot"))throw new CadFault("REPLAY_INPUT_SNAPSHOT_UNAVAILABLE","此旧任务没有与求解绑定的冻结输入描述。可离线读取已有截图或CSV；重新运行一次以建立可独立回放的快照。没有放宽当前输入哈希门禁。",new{run_id=runId,current_model_modified=false,legacy_snapshot_guessing=false});
        var link=(Dictionary<string,object>)saved["replay_input_snapshot"];string descriptor=ProbeOwnedPath((string)link["path"],Path.Combine(Root,"runs","state-snapshots"));
        if(FileHash(descriptor)!=(string)link["sha256"])throw new Exception("REPLAY_SNAPSHOT_INTEGRITY_FAILED");
        var state=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(descriptor));var model=Json.Deserialize<UserModel>(Json.Serialize(state["model"]));
        if(model.Id!=(string)saved["model_id"]||model.Configuration!=(string)saved["configuration"]||(string)state["model_id"]!=model.Id||!UserId(model.Id)||!model.Files.Contains(model.Path))throw new Exception("REPLAY_SNAPSHOT_IDENTITY_MISMATCH");
        foreach(string path in model.Files)OwnedPath(path,"user_assemblies");
        var hashes=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(state["files"]));var historyHashes=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(saved["history_input_file_hashes"]));
        if(hashes.Count!=model.Files.Length||historyHashes.Count!=hashes.Count||!hashes.All(p=>historyHashes.ContainsKey(p.Key)&&historyHashes[p.Key]==p.Value)||model.Files.Select(Path.GetFileName).Distinct(StringComparer.OrdinalIgnoreCase).Count()!=model.Files.Length)throw new Exception("REPLAY_SNAPSHOT_INPUT_SET_MISMATCH");
        var snapshots=model.Files.ToDictionary(p=>p,p=>ProbeOwnedPath(Path.Combine(Path.GetDirectoryName(descriptor),Path.GetFileName(p)),Path.GetDirectoryName(descriptor)));
        if(snapshots.Any(p=>!hashes.ContainsKey(p.Key)||FileHash(p.Value)!=hashes[p.Key]))throw new Exception("REPLAY_SNAPSHOT_INTEGRITY_FAILED");
        int count=Convert.ToInt32(saved["frames"]),componentCount=Convert.ToInt32(saved["components"]);double duration=Convert.ToDouble(saved["duration_s"]);int fps=Convert.ToInt32(saved["output_fps"]);
        if(!ReplayCsv.Allows(count,componentCount,frame,duration,fps)||new FileInfo(csv).Length>100000000)throw new Exception("REPLAY_HISTORY_BUDGET_INVALID");
        var names=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(saved["component_instances"]));if(names.Count!=componentCount||names.Values.Distinct().Count()!=componentCount)throw new Exception("REPLAY_COMPONENT_SET_INVALID");
        if(File.ReadLines(csv).First()!="frame,time_s,component_id,instance,x_m,y_m,z_m,r00,r01,r02,r10,r11,r12,r20,r21,r22")throw new Exception("REPLAY_CSV_HEADER_INVALID");
        var times=Enumerable.Repeat(double.NaN,count).ToArray();var seen=new HashSet<string>();var expected=new Dictionary<string,double[]>();int rows=0;
        foreach(string line in File.ReadLines(csv).Skip(1)){if(++rows>100000)throw new Exception("REPLAY_CSV_BUDGET_EXCEEDED");var values=ReplayCsv.Parse(line);if(values.Length!=16)throw new Exception("REPLAY_CSV_INVALID_ROW");int index=int.Parse(values[0],CultureInfo.InvariantCulture);string instance;if(index<0||index>=count||!names.TryGetValue(values[2],out instance)||instance!=values[3]||!seen.Add(index+":"+values[2]))throw new Exception("REPLAY_CSV_IDENTITY_INVALID");double time=double.Parse(values[1],CultureInfo.InvariantCulture);if(double.IsNaN(time)||double.IsInfinity(time)||Math.Abs(time-(double)index/fps)>1e-7||!double.IsNaN(times[index])&&Math.Abs(times[index]-time)>1e-9)throw new Exception("REPLAY_CSV_TIME_INVALID");times[index]=time;var numbers=values.Skip(4).Select(v=>double.Parse(v,CultureInfo.InvariantCulture)).ToArray();if(numbers.Any(v=>double.IsNaN(v)||double.IsInfinity(v)))throw new Exception("REPLAY_CSV_NONFINITE");if(index==frame)expected[instance]=numbers.Skip(3).Concat(numbers.Take(3)).Concat(new[]{1.0,0,0,0}).ToArray();}
        if(rows!=count*componentCount||expected.Count!=componentCount||times.Any(double.IsNaN)||Math.Abs(times.Last()-duration)>1e-7)throw new Exception("REPLAY_CSV_INCOMPLETE");
        string before=ReplayCurrentContext(model),folder=Path.Combine(Root,"runs","probes","replay_"+Guid.NewGuid().ToString("N").Substring(0,8));Directory.CreateDirectory(folder);Dictionary<string,string> renames;
        var isolated=CopyProbeInputs(model,snapshots,folder,out renames);Dictionary<string,object> worker=null;Exception failure=null;
        try{LastOperationRestoration="pending";worker=RunIsolatedProbe(folder,new Dictionary<string,object>{{"kind","replay_snapshot"},{"model",isolated},{"renames",renames},{"study",saved["study"]},{"duration_s",duration},{"output_fps",fps},{"times",times},{"expected",expected},{"frame",frame},{"run_id",runId}});}catch(Exception error){failure=error;}
        bool unchanged=false;try{unchanged=before==ReplayCurrentContext(model)&&FileHash(descriptor)==(string)link["sha256"]&&FileHash(csv)==(string)saved["poses_sha256"]&&snapshots.All(p=>FileHash(p.Value)==hashes[p.Key]);}catch{}
        if(!unchanged){LastOperationRestoration="unknown";throw new CadFault("SNAPSHOT_REPLAY_CONTEXT_CHANGED","回放后当前副本或冻结输入未通过前后核验；保留证据，不覆盖可能的并发编辑。",new{evidence_directory=folder});}
        if(failure!=null){LastOperationRestoration=HistoryErrorCode(failure)=="ISOLATED_PROBE_RECOVERY_REQUIRED"?"unknown":"restored";throw failure;}
        LastOperationRestoration="restored";var result=(Dictionary<string,object>)worker["result"];var validation=(Dictionary<string,object>)result["pose_validation"];
        string workerImage=ProbeOwnedPath((string)result["image_path"],folder);if(FileHash(workerImage)!=(string)result["image_sha256"])throw new Exception("REPLAY_IMAGE_INTEGRITY_FAILED");
        string attempt=Guid.NewGuid().ToString("N"),image=Path.Combine(directory,"motion-frame-"+frame+"-"+attempt+".bmp");File.Copy(workerImage,image);var run=new Run{Id=runId,Directory=directory,Assembly=model.Id,Times=times};
        var evidence=RecordVerifiedReplayImage(run,attempt,frame,image,validation,"independent_frozen_input_snapshot_frame_pose_match_not_current_model");
        return new{run_id=runId,frame=frame,image_path=image,saved_image_artifact=evidence,pose_validation=validation,replay_input_scope="frozen_pre_solve_input_not_current_model",current_model_validity="not_checked_by_snapshot_replay",current_context_unchanged=true,independent_owned_worker=true,worker_evidence_path=worker["evidence_path"],restoration_status="restored",physical_validation_claim=false};
    }
    object ReplaySnapshotWorker(UserModel model,Dictionary<string,object> request) {
        string folder=Path.Combine(Root,"runs",(string)request["run_id"]);Directory.CreateDirectory(folder);int frame=Convert.ToInt32(request["frame"]);
        var times=Json.Deserialize<double[]>(Json.Serialize(request["times"]));var original=Json.Deserialize<Dictionary<string,double[]>>(Json.Serialize(request["expected"]));var renames=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(request["renames"]));object validation=null;string image=Path.Combine(folder,"frame.bmp"),stage="open_scope";
        try{using(var scope=new Scope(this,model.Path,(string)request["study"])) {
            stage="inspect_components";InspectUserCore(model,scope.Doc);SaveUserModel(model);stage="prepare_clock";scope.RefreshStudy();scope.Study.Stop();scope.Study.SetTime(0);stage="preflight";RequireUserReady(model,scope.Doc,(string)request["study"]);scope.RefreshStudy();
            double duration=Convert.ToDouble(request["duration_s"]);int fps=Convert.ToInt32(request["output_fps"]);ConfigureSolveSettings(scope.Study,model.Id,(string)request["study"],duration,fps);
            stage="rebuild";if(!scope.Doc.EditRebuild3())throw new Exception("REBUILD_FAILED");scope.RefreshStudy();ConfigureSolveSettings(scope.Study,model.Id,(string)request["study"],duration,fps);stage="calculate";if(!scope.Study.Calculate())throw new Exception("SOLVER_FAILED");stage="refresh_and_stop_after_calculate";scope.RefreshStudy();scope.Study.Stop();stage="native_result_validation";RequireFreshSolveResults(scope.Study,(IMotionStudyResults)scope.Study.GetResults(4),model.Id,(string)request["study"],"snapshot_replay_after_calculate");VerifiedUserTimes(scope.Study,scope.Doc,duration,fps,folder,times);
            stage="select_replay_frame";SolverTimeCapture.Select(frame,times[frame],Argument(times[frame],duration),()=>scope.Study.SetTime(Argument(times[frame],duration)),()=>scope.Study.GetTime(),()=>scope.Study.IsPlaying,()=>scope.Study.Stop(),()=>Application.DoEvents(),()=>scope.EnsureActive());
            stage="validate_frame_poses";var actual=Transforms(scope.Doc);var expected=new Dictionary<string,double[]>();foreach(string name in actual.Keys){string old=name;foreach(var rename in renames)old=old.Replace(rename.Key,rename.Value);if(!original.ContainsKey(old))throw new Exception("REPLAY_COMPONENT_SET_MISMATCH");expected[name]=original[old];}
            if(expected.Count!=original.Count)throw new Exception("REPLAY_COMPONENT_SET_MISMATCH");bool matched=actual.All(p=>PoseValidation.Matches(expected[p.Key],p.Value));
            validation=new{frame=frame,time_s=times[frame],checked_component_count=actual.Count,within_pose_tolerance=matched,maximum_translation_difference_m=actual.Max(p=>PoseValidation.TranslationDistance(expected[p.Key],p.Value)),maximum_rotation_difference_rad=actual.Max(p=>PoseValidation.RotationDistance(expected[p.Key],p.Value)),translation_tolerance_m=PoseValidation.TranslationToleranceM,rotation_tolerance_rad=PoseValidation.RotationToleranceRad};
            if(!matched)throw new CadFault("POSE_MISMATCH","冻结输入重算的帧姿态与历史采样不符，未导出通过截图。",validation);stage="export_image";scope.Doc.GraphicsRedraw2();if(!scope.Doc.SaveBMP(image,1200,900))throw new Exception("FRAME_IMAGE_EXPORT_FAILED");stage="restore_worker_snapshot";
        }
        }catch(System.Runtime.InteropServices.COMException failure){throw new CadFault("COM_CALL_FAILED","冻结输入回放的原生调用失败；没有自动重算，查看具体阶段和退出记录。",new{stage=stage,native_hresult=failure.HResult,native_message=failure.Message,exception_chain=failure.ToString(),automatic_recalculate=false});}
        return new{image_path=image,image_sha256=FileHash(image),pose_validation=validation,restoration_status="restored"};
    }
}
