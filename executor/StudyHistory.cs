using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Web.Script.Serialization;

// History lives outside model checkpoints. It describes observations, not proven compatibility.
public static class StudyHistory {
    public class Observation {
        public bool Complete=true,AnyDirty;
        public List<object> Stages=new List<object>();
        public void Record(string stage,bool complete,int opened,int dirty,object documents,int? hresult=null) {
            Complete &= complete;AnyDirty |= dirty>0;
            Stages.Add(new{stage=stage,observed_at=DateTime.UtcNow.ToString("o",CultureInfo.InvariantCulture),complete=complete,owned_open_documents=opened,dirty_document_count=dirty,dirty_documents=documents,hresult=hresult});
        }
        public object Export(){return new{complete=Complete,dirty_documents_observed=AnyDirty,stages=Stages};}
    }
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 1048576 };
    static string IndexPath(string root,string model,string study) {
        if(!Regex.IsMatch(model??"","^user_[a-f0-9]{32}$")||string.IsNullOrEmpty(study))throw new ArgumentException("Invalid history identity");
        string key;
        using(var sha=SHA256.Create())key=BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(study))).Replace("-","").ToLowerInvariant();
        return Path.Combine(root,"runs","study-history",model,key+".json");
    }
    static void SafePath(string root,string path) {
        string boundary=Path.GetFullPath(Path.Combine(root,"runs")), current=Path.GetFullPath(path);
        if(!current.StartsWith(boundary+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new IOException("History outside runs");
        while(current.Length>=boundary.Length) {
            if((File.Exists(current)||Directory.Exists(current))&&(File.GetAttributes(current)&FileAttributes.ReparsePoint)!=0)throw new IOException("History reparse point");
            current=Path.GetDirectoryName(current);if(current==null)break;
        }
    }
    static Dictionary<string,object> Read(string path) {
        if(new FileInfo(path).Length>1048576)throw new IOException("History budget exceeded");
        var data=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));
        if(data==null)throw new InvalidOperationException("Empty history object");return data;
    }
    static object Value(Dictionary<string,object> data,string key) { object value;return data.TryGetValue(key,out value)?value:null; }
    public static string ErrorCode(string message) {
        var match=Regex.Match(message??"","^[A-Z][A-Z0-9_]*");return match.Success?match.Value:null;
    }
    public static void Register(string root,string model,string study,string run) {
        if(!Regex.IsMatch(run??"","^[a-f0-9]{32}$"))throw new ArgumentException("Invalid run identity");
        string path=IndexPath(root,model,study);SafePath(root,path);Directory.CreateDirectory(Path.GetDirectoryName(path));
        string temporary=Path.Combine(Path.GetDirectoryName(path),Guid.NewGuid().ToString("N")+".tmp");
        File.WriteAllText(temporary,Json.Serialize(new{model_id=model,study=study,run_id=run}));
        if(File.Exists(path))File.Replace(temporary,path,null);else File.Move(temporary,path);
    }
    public static Dictionary<string,object> Latest(string root,string model,string study,int revision,string configuration,Dictionary<string,string> hashes,bool unsavedChanges) {
        var observation=new Observation();observation.Record("legacy_flag",true,0,unsavedChanges?1:0,new object[0]);
        return Latest(root,model,study,revision,configuration,hashes,observation,null);
    }
    public static Dictionary<string,object> Latest(string root,string model,string study,int revision,string configuration,Dictionary<string,string> hashes,Observation observation,Dictionary<string,object> settings) {
        var response=new Dictionary<string,object>{{"last_run",null},{"run_history_status","none"},{"drive_compatibility_status","not_checked"},{"history_warning",null}};
        try {
            string index=IndexPath(root,model,study);SafePath(root,index);if(!File.Exists(index))return response;
            var pointer=Read(index);string run=Value(pointer,"run_id") as string;
            if((string)Value(pointer,"model_id")!=model||(string)Value(pointer,"study")!=study||!Regex.IsMatch(run??"","^[a-f0-9]{32}$"))throw new IOException("History identity mismatch");
            string manifest=Path.Combine(root,"runs",run,"solve.json");SafePath(root,manifest);var saved=Read(manifest);
            if((string)Value(saved,"model_id")!=model||(string)Value(saved,"study")!=study||(string)Value(saved,"run_id")!=run)throw new IOException("Manifest identity mismatch");
            string applicability="unknown";
            var recorded=Value(saved,"history_input_file_hashes") as Dictionary<string,object>;
            bool? revisionMatch=Value(saved,"model_revision")==null?(bool?)null:Convert.ToInt32(saved["model_revision"])==revision;
            bool? configurationMatch=Value(saved,"configuration")==null?(bool?)null:(string)saved["configuration"]==configuration;
            bool? hashesMatch=recorded==null||hashes==null?(bool?)null:recorded.Count==hashes.Count&&hashes.All(p=>recorded.ContainsKey(p.Key)&&string.Equals((string)recorded[p.Key],p.Value,StringComparison.OrdinalIgnoreCase));
            var inputSettings=Value(saved,"history_input_study_settings") as Dictionary<string,object>;
            if(inputSettings!=null&&new[]{"type","fps","duration_s"}.Any(k=>!inputSettings.ContainsKey(k)))throw new InvalidOperationException("Incomplete history study settings");
            bool? settingsMatch=inputSettings==null||settings==null?(bool?)null:Convert.ToInt32(inputSettings["type"])==Convert.ToInt32(settings["type"])&&Convert.ToInt32(inputSettings["fps"])==Convert.ToInt32(settings["fps"])&&Math.Abs(Convert.ToDouble(inputSettings["duration_s"])-Convert.ToDouble(settings["duration_s"]))<=1e-8;
            var reasons=new List<string>();
            if(revisionMatch==false)reasons.Add("MODEL_REVISION_CHANGED");
            if(configurationMatch==false)reasons.Add("CONFIGURATION_CHANGED");
            if(hashesMatch==false)reasons.Add("INPUT_FILES_CHANGED");
            if(settingsMatch==false)reasons.Add("STUDY_SETTINGS_CHANGED");
            if(reasons.Count>0)applicability="stale";
            else {
                if(observation==null||!observation.Complete)reasons.Add("INPUT_OBSERVATION_INCOMPLETE");
                if(observation!=null&&observation.AnyDirty)reasons.Add("UNSAVED_INPUT_NOT_VERIFIED");
                if(revisionMatch==null||configurationMatch==null||hashesMatch==null||inputSettings!=null&&settings==null)reasons.Add("INPUT_COMPARISON_INCOMPLETE");
                if(reasons.Count==0){applicability="matches_recorded_input";reasons.Add("INPUT_MATCH_CONFIRMED");}
            }
            var last=new Dictionary<string,object>();
            foreach(string key in new[]{"run_id","solver_status","sampling_status","restoration_status","result_validity","error_code","started_at","finished_at","duration_s","output_fps","model_revision","configuration"})last[key]=Value(saved,key);
            last["input_match_status"]=applicability;last["compatibility_claim"]="historical_solve_observation_only";
            last["input_match_diagnostics"]=new{revision_match=revisionMatch,configuration_match=configurationMatch,file_hashes_match=hashesMatch,study_settings_match=settingsMatch,observation_complete=observation!=null&&observation.Complete,dirty_documents_observed=observation!=null&&observation.AnyDirty,reasons=reasons};
            response["last_run"]=last;response["run_history_status"]="available";
            string error=Value(saved,"error_code") as string;
            if((string)Value(saved,"restoration_status")=="restored"&&new[]{"MOTION_RESULTS_INCOMPLETE","SOLVER_FAILED","DRIVE_VALIDATION_FAILED"}.Contains(error)) {
                if(applicability=="matches_recorded_input")response["history_warning"]="PREVIOUS_SOLVE_FAILED_SAME_INPUT";
                else if(applicability=="unknown")response["history_warning"]="PREVIOUS_SOLVE_FAILED_INPUT_NOT_VERIFIED";
            }
        } catch(Exception e) {
            if(!(e is IOException||e is UnauthorizedAccessException||e is ArgumentException||e is InvalidOperationException||e is InvalidCastException||e is FormatException||e is OverflowException))throw;
            response["run_history_status"]="unavailable";response["last_run"]=null;response["history_warning"]="RUN_HISTORY_UNAVAILABLE";
        }
        return response;
    }
}
