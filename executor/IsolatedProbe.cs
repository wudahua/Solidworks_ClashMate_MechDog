using System;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Threading;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    static string ProbeOwnedPath(string path,string boundary) {
        string root=Path.GetFullPath(boundary),full=Path.GetFullPath(path);
        if(!full.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new Exception("PROBE_PATH_OUTSIDE_BOUNDARY");
        string cursor=full;while(cursor!=null&&cursor.Length>=root.Length){if((File.Exists(cursor)||Directory.Exists(cursor))&&(File.GetAttributes(cursor)&FileAttributes.ReparsePoint)!=0)throw new Exception("PROBE_REPARSE_POINT_REJECTED");cursor=Path.GetDirectoryName(cursor);}return full;
    }
    // Probe documents are opened only in an application process created by this worker.
    // The worker never takes the interactive executor lease or connects by auto PID.
    public static int IsolatedProbeWorker(string requestPath) {
        Process owned=null;Cad cad=null;string resultPath=Path.Combine(Path.GetDirectoryName(requestPath),"worker-result.json");
        var elapsed=Stopwatch.StartNew();var phases=new List<object>();long previous=0;string previousStage="worker_initialization";
        Action<string> phase=stage=>{try{long now=elapsed.ElapsedMilliseconds;phases.Add(new{stage=stage,elapsed_ms=now,previous_stage=previousStage,previous_phase_elapsed_ms=now-previous,observed_at_utc=DateTime.UtcNow.ToString("o")});previous=now;previousStage=stage;AtomicJson(Path.Combine(Path.GetDirectoryName(resultPath),"worker-phase.json"),new{stage=stage,elapsed_ms=now,phases=phases.Take(32).ToArray(),phase_only_not_cad_completion_proof=true,completion_evidence="worker-result.json"});}catch{}};
        object result=null;Exception failure=null,cleanup=null;int? nativeExit=null;bool ownedConnected=false;UserModel probeModel=null;
        try {
            var request=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(requestPath));
            string root=Path.GetDirectoryName(Path.GetFullPath(requestPath));
            string executable=(string)request["solidworks_executable"];
            phase("starting_owned_solidworks");owned=Process.Start(new ProcessStartInfo(executable){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden});
            AtomicJson(Path.Combine(root,"worker-owner.json"),new{worker_pid=Process.GetCurrentProcess().Id,owned_solidworks_pid=owned.Id,parent_solidworks_pid=request["parent_solidworks_pid"]});
            if(owned.Id==Convert.ToInt32(request["parent_solidworks_pid"]))throw new Exception("PROBE_INSTANCE_NOT_ISOLATED");
            System.Environment.SetEnvironmentVariable("SW_MCP_PROCESS_ID",owned.Id.ToString());
            phase("connecting_owned_solidworks");var timer=Stopwatch.StartNew();Exception connection=null;
            while(timer.Elapsed.TotalSeconds<180&&!owned.HasExited){try{cad=new Cad(root);break;}catch(Exception error){connection=error;Thread.Sleep(500);}}
            if(cad==null)throw new CadFault("PROBE_INSTANCE_UNAVAILABLE","临时SolidWorks实例未连接；未使用原实例。",new{owned_pid=owned.Id,cause=connection==null?null:connection.Message});
            if(cad.Sw.GetProcessID()!=owned.Id)throw new Exception("PROBE_INSTANCE_NOT_ISOLATED");
            ownedConnected=true;var model=Json.Deserialize<UserModel>(Json.Serialize(request["model"]));probeModel=model;
            string fileBoundary=root;
            if((string)request["kind"]=="reset_branch") {
                fileBoundary=ResetBranchBoundary.Validate(root,model.Id,model.Directory,model.Path,model.Files,model.Purpose,model.ImportState);
                ProbeOwnedPath(fileBoundary,Directory.GetParent(root).Parent.Parent.FullName);
            }
            foreach(string file in model.Files)ProbeOwnedPath(file,fileBoundary);
            cad.SaveUserModel(model);phase("loading_motion_addin");cad.LoadUserMotion();phase("motion_addin_loaded");
            if((string)request["kind"]=="checkpoint") {
                phase("opening_checkpoint_copy");using(var scope=new Scope(cad,model.Path,null)) {
                    phase("checkpoint_copy_opened");
                    if(scope.Doc.ConfigurationManager.ActiveConfiguration.Name!=model.Configuration&&!scope.Doc.ShowConfiguration2(model.Configuration))throw new Exception("CHECKPOINT_CONFIGURATION_MISMATCH");
                    var states=Json.Deserialize<StudyState[]>(Json.Serialize(request["studies"]));
                    var original=Json.Deserialize<Dictionary<string,double[]>>(Json.Serialize(request["poses"]));
                    var renames=Json.Deserialize<Dictionary<string,string>>(Json.Serialize(request["renames"]));
                    var expected=new Dictionary<string,double[]>();
                    foreach(string name in Transforms(scope.Doc).Keys){string old=name;foreach(var rename in renames)old=old.Replace(rename.Key,rename.Value);if(!original.ContainsKey(old))throw new Exception("CHECKPOINT_PROBE_COMPONENT_SET_MISMATCH");expected[name]=original[old];}
                    if(expected.Count!=original.Count)throw new Exception("CHECKPOINT_PROBE_COMPONENT_SET_MISMATCH");
                    phase("restoring_checkpoint_state");ApplyStudyStates(scope.Doc,states,expected);VerifyStudyStates(scope.Doc,states);phase("checkpoint_state_verified");
                    result=new{status="verified",pose_change=PoseChange(expected,Transforms(scope.Doc)),restoration_status="restored"};
                }
            } else if((string)request["kind"]=="reset_branch") {
                phase("resetting_new_registered_copy");result=cad.ResetBranchWorker(model,request);
            } else if((string)request["kind"]=="replay_snapshot") {
                result=cad.ReplaySnapshotWorker(model,request);
            } else if((string)request["kind"]=="compatibility") {
                using(var scope=new Scope(cad,model.Path,null)){cad.InspectUserCore(model,scope.Doc);cad.SaveUserModel(model);}
                phase("running_snapshot_study");result=cad.RunUserStudy(model.Id,(string)request["study"],Convert.ToDouble(request["duration_s"]),Convert.ToInt32(request["output_fps"]),(string)request["run_id"]);
            } else throw new Exception("INVALID_PROBE_WORKER_KIND");
        }catch(Exception error){failure=error;}
        finally {
            phase("cleanup_owned_instance");if(cad!=null&&ownedConnected)try{var docs=(cad.Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().ToArray();
                var titles=docs.Where(d=>probeModel!=null&&probeModel.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)).Select(d=>d.GetTitle()).ToArray();foreach(string title in titles)try{cad.Sw.CloseDoc(title);}catch(System.Runtime.InteropServices.COMException){}
                if((cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("PROBE_UNEXPECTED_DOCUMENTS_EXIT_REFUSED");phase("exiting_owned_solidworks");cad.Sw.ExitApp();
            }catch(Exception error){cleanup=error;}
            if(owned!=null){phase("waiting_owned_process_exit");if(owned.WaitForExit(30000))nativeExit=owned.ExitCode;else cleanup=new Exception("PROBE_INSTANCE_EXIT_NOT_CONFIRMED");}
            phase("completed");AtomicJson(resultPath,new{completed=true,phase_timings=phases.Take(32).ToArray(),elapsed_ms=elapsed.ElapsedMilliseconds,success=failure==null&&cleanup==null,result=result,failure=failure==null?null:FailureEvidence(failure),cleanup_failure=cleanup==null?null:FailureEvidence(cleanup),owned_solidworks_pid=owned==null?(int?)null:owned.Id,owned_process_exited=nativeExit.HasValue,native_exit_code=nativeExit,native_exit_code_interpretation=nativeExit==0?"zero_exit":"nonzero_observed_cause_not_proven",managed_completion_is_separate_from_native_exit=true});
        }
        return failure==null&&cleanup==null?0:1;
    }
    Dictionary<string,object> RunIsolatedProbe(string folder,Dictionary<string,object> request) {
        var hostTiming=new OperationTiming();hostTiming.Start("prepare_worker_request");ProbeOwnedPath(folder,Path.Combine(Root,"runs"));
        string sw=Sw.GetExecutablePath();if(Directory.Exists(sw))sw=Path.Combine(sw,"SLDWORKS.exe");
        request["solidworks_executable"]=sw;request["parent_solidworks_pid"]=Sw.GetProcessID();
        string input=Path.Combine(folder,"worker-request.json");AtomicJson(input,request);
        var start=new ProcessStartInfo(System.Reflection.Assembly.GetExecutingAssembly().Location,"--isolated-probe \""+input+"\""){UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,RedirectStandardError=true,RedirectStandardOutput=true};
        hostTiming.Start("start_and_wait_worker");using(var worker=Process.Start(start)) {
            var stdout=worker.StandardOutput.ReadToEndAsync();var stderr=worker.StandardError.ReadToEndAsync();
            // Like a native COM call, this is not forcibly cancelled at the client's wait deadline.
            worker.WaitForExit();File.WriteAllText(Path.Combine(folder,"worker-stdout.log"),stdout.Result);File.WriteAllText(Path.Combine(folder,"worker-stderr.log"),stderr.Result);
            hostTiming.Start("read_worker_completion");string result=Path.Combine(folder,"worker-result.json");if(!File.Exists(result))throw new CadFault("PROBE_WORKER_RESULT_MISSING","独立探测未留下完成证据；未添加配合。",new{worker_pid=worker.Id,worker_exit=worker.ExitCode,evidence_directory=folder});
            var evidence=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(result));hostTiming.Finish();evidence["host_round_trip_timings"]=hostTiming.Export();evidence["evidence_path"]=result;evidence["evidence_sha256"]=FileHash(result).Replace("-","").ToLowerInvariant();
            if(!Convert.ToBoolean(evidence["owned_process_exited"])||evidence["cleanup_failure"]!=null)throw new CadFault("ISOLATED_PROBE_RECOVERY_REQUIRED","临时实例退出或清理未确认；保留所有进程与证据。",new{worker=evidence,evidence_path=result});
            if(worker.ExitCode!=0||!Convert.ToBoolean(evidence["success"])) {
                var failed=evidence["failure"] as Dictionary<string,object>;object code;
                if((string)request["kind"]=="checkpoint"&&failed!=null&&failed.TryGetValue("code",out code)&&new[]{"CHECKPOINT_POSE_RESTORE_FAILED","CHECKPOINT_TIME_RESTORE_FAILED"}.Contains(Convert.ToString(code)))throw new CadFault(Convert.ToString(code),"独立副本未恢复检查点姿态或时钟；未添加配合。",new{worker=evidence,evidence_path=result});
                throw new CadFault("ISOLATED_PROBE_FAILED","独立探测未通过；原实例未打开探测副本。",new{worker=evidence,evidence_path=result});
            }
            evidence["evidence_path"]=result;evidence["evidence_sha256"]=FileHash(result).Replace("-","").ToLowerInvariant();return evidence;
        }
    }
    UserModel CopyProbeInputs(UserModel source,Dictionary<string,string> snapshots,string folder,out Dictionary<string,string> renames) {
        ProbeOwnedPath(folder,Path.Combine(Root,"runs"));
        string uid=Guid.NewGuid().ToString("N"),directory=Path.Combine(folder,"experiments","user_assemblies",uid),files=Path.Combine(directory,"files");Directory.CreateDirectory(files);
        var mapping=source.Files.Select((p,i)=>new{path=p,copy=Path.Combine(files,"probe_"+uid.Substring(0,8)+"_"+i.ToString("D4")+Path.GetExtension(p))}).ToDictionary(p=>p.path,p=>p.copy,StringComparer.OrdinalIgnoreCase);
        foreach(var entry in mapping){File.Copy(snapshots[entry.Key],entry.Value);File.SetAttributes(entry.Value,FileAttributes.Normal);}
        foreach(var entry in mapping)foreach(string reference in DiskDependencies(snapshots[entry.Key],false))if(!mapping.ContainsKey(reference)||!Sw.ReplaceReferencedDocument(entry.Value,reference,mapping[reference]))throw new Exception("CHECKPOINT_PROBE_REDIRECT_FAILED");
        foreach(string file in mapping.Values)if(DiskDependencies(file,true).Any(p=>!mapping.Values.Contains(p,StringComparer.OrdinalIgnoreCase)))throw new Exception("CHECKPOINT_PROBE_NOT_ISOLATED");
        renames=mapping.ToDictionary(p=>Path.GetFileNameWithoutExtension(p.Value),p=>Path.GetFileNameWithoutExtension(p.Key));
        var model=Json.Deserialize<UserModel>(Json.Serialize(source));model.Id="user_"+uid;model.Directory=directory;model.Path=mapping[source.Path];model.Files=source.Files.Select(p=>mapping[p]).ToArray();model.SourceHashes=snapshots.Values.Distinct().ToDictionary(p=>p,p=>FileHash(p));model.Purpose="compatibility_probe";model.ParentModelId=source.Id;return model;
    }
}
