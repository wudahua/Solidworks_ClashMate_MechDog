using System;
using System.IO;
using System.Collections.Generic;

public partial class Cad {
    string ReplayStoragePath(Run run,string relative){
        string boundary=Path.GetFullPath(Path.Combine(Root,"runs",run.Id)),path=Path.GetFullPath(Path.Combine(boundary,relative));
        if(!string.Equals(Path.GetFullPath(run.Directory),boundary,StringComparison.OrdinalIgnoreCase)||!path.StartsWith(boundary+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("IMAGE_PATH_OUTSIDE_RUN");
        string current=path;while(current!=null&&current.Length>=Root.Length){if((File.Exists(current)||Directory.Exists(current))&&(File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0)throw new IOException("IMAGE_REPARSE_POINT");current=Path.GetDirectoryName(current);}return path;
    }
    object RecordVerifiedReplayImage(Run run,string attempt,int frame,string image,object validation,string captureScope="recalculated_frame_component_pose_match_and_owned_state_restoration"){
        var checkedPose=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(validation));
        if(checkedPose==null||!Convert.ToBoolean(checkedPose["within_pose_tolerance"])||LastOperationRestoration!="restored")throw new CadFault("IMAGE_CAPTURE_UNVERIFIED","未核验姿态及完整恢复，未登记历史截图。");
        string csv=Path.Combine(run.Directory,"component-poses.csv"),solve=Path.Combine(run.Directory,"solve.json");var result=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(solve));
        if(FileHash(csv)!=(string)result["poses_sha256"])throw new CadFault("RESULT_ARTIFACT_CHANGED","保存截图清单时采样数据已改变；未登记截图。");
        if(!string.Equals(image,ReplayStoragePath(run,Path.GetFileName(image)),StringComparison.OrdinalIgnoreCase))throw new IOException("IMAGE_PATH_OUTSIDE_RUN");string folder=ReplayStoragePath(run,"screenshots");Directory.CreateDirectory(folder);
        var metadata=new{schema_version=1,run_id=run.Id,model_id=run.Assembly,attempt_id=attempt,frame=frame,time_s=run.Times[frame],image_file=Path.GetFileName(image),image_sha256=FileHash(image).Replace("-","").ToLowerInvariant(),poses_sha256=FileHash(csv).Replace("-","").ToLowerInvariant(),captured_at_utc=File.GetLastWriteTimeUtc(image).ToString("o"),recorded_at_utc=DateTime.UtcNow.ToString("o"),pose_validation=checkedPose,pose_assertion="pass",restoration_status="restored",capture_scope=captureScope,camera_validation="not_independently_checked",physical_validation_claim=false};
        string path=Path.Combine(folder,attempt+".json");if(File.Exists(path))throw new IOException("IMAGE_ATTEMPT_ALREADY_RECORDED");AtomicJson(path,metadata);return new{metadata_path=path,image_path=image,frame=frame,image_sha256=metadata.image_sha256,poses_sha256=metadata.poses_sha256,pose_assertion="pass",restoration_status="restored"};
    }
}
