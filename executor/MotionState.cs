using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swmotionstudy;

public partial class Cad {
    public class StudyState {
        public string name;
        public int type,fps;
        public double time_s,duration_s;
        public bool active;
    }
    void SaveOwnedDocuments(UserModel model){foreach(var d in (Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Where(d=>model.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)).OrderBy(d=>d.GetType()))if(d.GetSaveFlag()){string path=d.GetPathName(),before=FileHash(path);Save(d,path);Log("OWNED_INPUT_PERSISTED "+Json.Serialize(new{model_id=model.Id,operation_job_id=activeJobId,path=path,hash_before=before,hash_after=FileHash(path),dirty_after_save=d.GetSaveFlag(),model_revision=model.Revision}));}}
    static StudyState[] StudyStates(IModelDoc2 doc) {
        var manager=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();
        return Names(manager).Select(n=>{var s=(IMotionStudy)manager.GetMotionStudy(n);return new StudyState{name=n,type=s.StudyType,time_s=s.GetTime(),duration_s=s.GetDuration(),fps=((IMotionStudyProperties)s.GetProperties(s.StudyType)).GetFrameRate(),active=s.IsActive};}).ToArray();
    }
    static object PoseDifference(Dictionary<string,double[]> before,Dictionary<string,double[]> after) {
        if(!before.Keys.OrderBy(n=>n).SequenceEqual(after.Keys.OrderBy(n=>n)))throw new Exception("CHECKPOINT_COMPONENT_SET_MISMATCH");
        return new{translation_m=before.Count==0?0:before.Max(p=>Math.Sqrt(Enumerable.Range(9,3).Sum(i=>Math.Pow(p.Value[i]-after[p.Key][i],2)))),rotation_coefficient_delta=before.Count==0?0:before.Max(p=>Enumerable.Range(0,9).Max(i=>Math.Abs(p.Value[i]-after[p.Key][i]))),maximum_transform_delta=before.Count==0?0:before.Max(p=>p.Value.Zip(after[p.Key],(a,b)=>Math.Abs(a-b)).Max())};
    }
    static void VerifyStudyStates(IModelDoc2 doc,StudyState[] expected) {
        var actual=StudyStates(doc);
        if(actual.Length!=expected.Length)throw new Exception("CHECKPOINT_STUDY_SET_MISMATCH");
        foreach(var state in expected){var s=actual.SingleOrDefault(v=>v.name==state.name);if(s==null||s.type!=state.type||s.fps!=state.fps||Math.Abs(s.duration_s-state.duration_s)>1e-8||Math.Abs(s.time_s-state.time_s)>1e-8||s.active!=state.active)throw new Exception("CHECKPOINT_SETTINGS_MISMATCH "+Json.Serialize(new{expected=state,actual=s}));}
    }
    static void ApplyStudyStates(IModelDoc2 doc,StudyState[] states,Dictionary<string,double[]> expectedPoses=null) {
        var mgr=(IMotionStudyManager)doc.Extension.GetMotionStudyManager();
        if(expectedPoses!=null)Log("RESTORE_BEFORE_APPLY_STATES "+Json.Serialize(new{pose_change=PoseChange(expectedPoses,Transforms(doc)),studies=StudyStates(doc)}));
        // An inactive study's clock is independent of the selected tab. Never activate every study.
        foreach(var state in states){var s=(IMotionStudy)mgr.GetMotionStudy(state.name);if(s==null)throw new Exception("CHECKPOINT_STUDY_MISSING");if(s.StudyType!=state.type)s.StudyType=state.type;if(Math.Abs(s.GetDuration()-state.duration_s)>1e-8&&!s.SetDuration(state.duration_s))throw new Exception("CHECKPOINT_SETTINGS_MISMATCH");var props=(IMotionStudyProperties)s.GetProperties(s.StudyType);if(props.GetFrameRate()!=state.fps)props.SetFrameRate(state.fps);if(!state.active&&Math.Abs(s.GetTime()-state.time_s)>1e-8 ){bool selected=s.SetTime(state.time_s);Application.DoEvents();s.Stop();if(Math.Abs(s.GetTime()-state.time_s)>1e-8||s.IsPlaying)throw new CadFault("CHECKPOINT_TIME_RESTORE_FAILED","未激活算例时间回读不符。",new{study=state.name,set_time_return=selected,actual_time_s=s.GetTime(),expected_time_s=state.time_s,playing=s.IsPlaying});}}
        foreach(var state in states.Where(v=>v.active)){var s=(IMotionStudy)mgr.GetMotionStudy(state.name);if(!s.IsActive&&!s.Activate())throw new CadFault("CHECKPOINT_TIME_RESTORE_FAILED","算例激活失败。",new{stage="activate",study=state.name});s.Stop();
            // Animation can report zero while displaying another tab's cached pose.
            // A new Motion Analysis at zero may instead contain the authored assembly
            // pose, which must not be replaced with a newly solved frame-zero pose.
            var loadedPoses=Transforms(doc);bool poseAlreadyMatches=expectedPoses!=null&&expectedPoses.Count==loadedPoses.Count&&expectedPoses.All(p=>loadedPoses.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,loadedPoses[p.Key]));
            Log("RESTORE_ACTIVE_BEFORE_TIME_SELECTION "+Json.Serialize(new{study=state.name,time_s=s.GetTime(),pose_already_matches=poseAlreadyMatches}));
            if((Math.Abs(s.GetTime()-state.time_s)>1e-8||(state.type==1&&!poseAlreadyMatches))&&!s.SetTime(state.time_s)) {
                // Saved animation clocks can reopen without their calculated cache. Reconstruct
                // only the recorded active study, with its exact original settings and a budget.
                if(!StudyCacheBudget.Allows(state.duration_s,state.fps))throw new CadFault("CHECKPOINT_TIME_RESTORE_FAILED","恢复时间需要重建结果缓存，但原设置超过预算。",new{stage="rehydrate_budget",study=state});
                Log("RESTORE_REHYDRATE_ACTIVE_STUDY "+Json.Serialize(state));bool calculated=s.Calculate();s.Stop();Application.DoEvents();s.Stop();
                bool selected=s.SetTime(state.time_s);Application.DoEvents();s.Stop();if(!calculated||Math.Abs(s.GetTime()-state.time_s)>1e-8||s.IsPlaying)throw new CadFault("CHECKPOINT_TIME_RESTORE_FAILED","重建缓存后仍无法恢复算例时间。",new{stage="set_time_after_rehydrate",study=state.name,calculate_return=calculated,expected_time_s=state.time_s,actual_time_s=s.GetTime()});
            }
            Application.DoEvents();s.Stop();}
        VerifyStudyStates(doc,states);
        if(expectedPoses!=null) {
            var difference=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(PoseDifference(expectedPoses,Transforms(doc))));
            if(Convert.ToDouble(difference["maximum_transform_delta"])>1e-7) {
                var active=states.SingleOrDefault(v=>v.active);
                if(active==null||active.type!=1||!StudyCacheBudget.Allows(active.duration_s,active.fps))throw new CadFault("CHECKPOINT_POSE_RESTORE_FAILED","时间回读相符但姿态不符；不能用新求解覆盖记录的装配初始姿态。",difference);
                var s=(IMotionStudy)mgr.GetMotionStudy(active.name);Log("RESTORE_REHYDRATE_POSE_MISMATCH "+Json.Serialize(difference));bool calculated=s.Calculate();s.Stop();Application.DoEvents();s.Stop();bool selected=s.SetTime(active.time_s);Application.DoEvents();s.Stop();
                var after=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(PoseDifference(expectedPoses,Transforms(doc))));
                if(!calculated||Math.Abs(s.GetTime()-active.time_s)>1e-8||s.IsPlaying||Convert.ToDouble(after["maximum_transform_delta"])>1e-7)throw new CadFault("CHECKPOINT_POSE_RESTORE_FAILED","重建缓存后姿态仍与检查点不符。",new{study=active.name,calculate_return=calculated,set_time_return=selected,expected_time_s=active.time_s,actual_time_s=s.GetTime(),playing=s.IsPlaying,before=difference,after=after,pose_change=PoseChange(expectedPoses,Transforms(doc))});
                VerifyStudyStates(doc,states);
            }
        }
    }
    class OwnedMotionSnapshot {
        Cad cad;UserModel model;string directory;StudyState[] states;Dictionary<string,double[]> poses;Dictionary<string,string> hashes;
        public object Diagnostics;
        public StudyState[] InputStudies {get{return states;}}
        public OwnedMotionSnapshot(Cad owner,UserModel m,IModelDoc2 doc) {
            cad=owner;model=m;
            var initial=StudyStates(doc);var unsupported=initial.FirstOrDefault(v=>v.active&&Math.Abs(v.time_s*v.fps-Math.Round(v.time_s*v.fps))>1e-5);
            if(unsupported!=null)throw new CadFault("ACTIVE_TIME_NOT_FRAME_ALIGNED","当前激活算例停在非输出帧时刻；请先显式 reset_study_time 归零，再求解或回放。",new{study=unsupported.name,time_s=unsupported.time_s,output_fps=unsupported.fps,required_tool="reset_study_time",reason="native_sampling_stall_reproduced_on_revision_34_0_0"});
            // Only registered copies are saved. Persist the pre-operation model page and study clocks.
            owner.SaveOwnedDocuments(m);
            states=StudyStates(doc);if(states.Any(v=>v.active&&((IMotionStudy)((IMotionStudyManager)doc.Extension.GetMotionStudyManager()).GetMotionStudy(v.name)).IsPlaying))throw new Exception("STUDY_PLAYING_STOP_REQUIRED");poses=Transforms(doc);hashes=m.Files.ToDictionary(p=>p,p=>FileHash(p));
            directory=Path.Combine(owner.Root,"runs","state-snapshots",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(directory);
            foreach(string p in m.Files)File.Copy(p,Path.Combine(directory,Path.GetFileName(p)));
            AtomicJson(Path.Combine(directory,"state.json"),new{model_id=m.Id,configuration=m.Configuration,studies=states,poses=poses,files=hashes});
        }
        public IModelDoc2 Restore(StudyHistory.Observation observation=null) {
            // Closing and restoring the exact file snapshot discards transient results.
            // Selecting zero here is unnecessary and can fault on a stale native cache.
            foreach(var d in (cad.Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Where(d=>d.GetPathName().Equals(model.Path,StringComparison.OrdinalIgnoreCase))){var mgr=(IMotionStudyManager)d.Extension.GetMotionStudyManager();foreach(string n in Names(mgr)){var study=(IMotionStudy)mgr.GetMotionStudy(n);if(study.IsActive){study.Stop();Application.DoEvents();if(study.IsPlaying)throw new CadFault("RESTORATION_STOP_FAILED","恢复前仍在播放，未关闭文档或覆盖快照。",new{study=n});}}}
            cad.CloseUserDocuments(model.Files);
            if((cad.Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().Any(d=>model.Files.Contains(d.GetPathName(),StringComparer.OrdinalIgnoreCase)))throw new Exception("CHECKPOINT_DOCUMENT_STILL_OPEN");
            foreach(string p in model.Files)File.Copy(Path.Combine(directory,Path.GetFileName(p)),p,true);
            int e=0,w=0;var doc=(IModelDoc2)cad.Sw.OpenDoc6(model.Path,2,1,"",ref e,ref w);if(doc==null||e!=0)throw new Exception("ASSEMBLY_OPEN_FAILED "+e);
            var active=cad.Sw.ActiveDoc as IModelDoc2;if(active==null||!string.Equals(active.GetPathName(),model.Path,StringComparison.OrdinalIgnoreCase))cad.Sw.ActivateDoc3(doc.GetTitle(),false,0,ref e);if(e!=0)throw new Exception("ASSEMBLY_OPEN_FAILED "+e);
            if(doc.ConfigurationManager.ActiveConfiguration.Name!=model.Configuration&&!doc.ShowConfiguration2(model.Configuration))throw new Exception("CHECKPOINT_CONFIGURATION_MISMATCH");
            ApplyStudyStates(doc,states,poses);Diagnostics=PoseDifference(poses,Transforms(doc));
            if(observation!=null)cad.ObserveHistory(model,observation,"after_restore_apply_states");
            var delta=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(Diagnostics));
            if(Convert.ToDouble(delta["maximum_transform_delta"])>1e-7||hashes.Any(p=>FileHash(p.Key)!=p.Value))throw new Exception("RESTORATION_FAILED "+Json.Serialize(new{difference=Diagnostics,snapshot=directory}));
            return doc;
        }
    }
    object TestSetUserStudyTime(string id,string name,double time){var m=GetUserModel(id);LoadUserMotion();using(var scope=new Scope(this,m.Path,null)){var s=(IMotionStudy)((IMotionStudyManager)scope.Doc.Extension.GetMotionStudyManager()).GetMotionStudy(name);if(s==null||double.IsNaN(time)||time<0||time>s.GetDuration())throw new Exception("INVALID_TEST_TIME");if(!s.IsActive)s.Activate();if(!s.Calculate()||!s.SetTime(time))throw new Exception("TEST_TIME_SETUP_FAILED");Application.DoEvents();Save(scope.Doc,m.Path);m.Revision++;SaveUserModel(m);return new{time_s=s.GetTime(),active=s.IsActive,model_revision=m.Revision};}}
}
