"""Exercise production history expiry and failure semantics without a CAD connection."""
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'runs/history-tests' / uuid.uuid4().hex[:8]
folder.mkdir(parents=True)
source = folder / 'Probe.cs'
source.write_text(r'''
using System;
using System.IO;
using System.Collections.Generic;
using System.Web.Script.Serialization;
class Probe {
 static int checks;
 static void Check(bool condition,string message){checks++;if(!condition)throw new Exception(message);}
 static void Main(string[] args){
  string root=args[0],model="user_"+new string('a',32),study="旋转../参考",run=new string('b',32);
  var hashes=new Dictionary<string,string>{{"owned-copy","hash1"}};
  var json=new JavaScriptSerializer();
  Func<int,bool,Dictionary<string,object>> latest=(revision,dirty)=>StudyHistory.Latest(root,model,study,revision,"默认",hashes,dirty);
  Check((string)latest(2,false)["run_history_status"]=="none","missing history");
  string directory=Path.Combine(root,"runs",run);Directory.CreateDirectory(directory);
  string manifest=Path.Combine(directory,"solve.json");
  var saved=new Dictionary<string,object>{{"run_id",run},{"model_id",model},{"study",study},{"solver_status","incomplete"},{"error_code","MOTION_RESULTS_INCOMPLETE"},{"restoration_status","restored"},{"result_validity","inconclusive"},{"model_revision",2},{"configuration","默认"},{"history_input_file_hashes",hashes},{"finished_at","2026-10-13T00:00:00Z"}};
  Action save=()=>File.WriteAllText(manifest,json.Serialize(saved));save();StudyHistory.Register(root,model,study,run);
  var current=latest(2,false);var last=(Dictionary<string,object>)current["last_run"];
  Check((string)current["history_warning"]=="PREVIOUS_SOLVE_FAILED_SAME_INPUT","failure warning");
  Check((string)current["drive_compatibility_status"]=="not_checked"&&(string)last["result_validity"]=="inconclusive","no false compatibility proof");
  Check(latest(3,false)["history_warning"]==null,"revision expiry");
  Check(latest(2,true)["history_warning"]==null,"unsaved expiry");
  hashes["owned-copy"]="hash2";Check(latest(2,false)["history_warning"]==null,"file hash expiry");hashes["owned-copy"]="hash1";
  saved["restoration_status"]="unknown";save();Check(latest(2,false)["history_warning"]==null,"unknown restoration not a compatibility verdict");
  saved.Remove("history_input_file_hashes");save();last=(Dictionary<string,object>)latest(2,false)["last_run"];Check((string)last["input_match_status"]=="unknown","legacy input unknown");
  saved["history_input_file_hashes"]=hashes;saved["solver_status"]="completed";saved["result_validity"]="verified";saved["error_code"]=null;saved["restoration_status"]="restored";save();
  Check(latest(2,false)["history_warning"]==null,"success clears failure warning");
  saved["finished_at"]=null;saved["solver_status"]="running";save();last=(Dictionary<string,object>)latest(2,false)["last_run"];Check(last["finished_at"]==null&&(string)last["solver_status"]=="running","interrupted run never gets fake completion");
  File.WriteAllText(manifest,"{");Check((string)latest(2,false)["run_history_status"]=="unavailable","corruption visible");
  saved["model_id"]="user_"+new string('c',32);save();Check(latest(2,false)["last_run"]==null,"cross-model manifest rejected");
  Check((string)StudyHistory.Latest(root,model,"other study",2,"默认",hashes,false)["run_history_status"]=="none","study isolation");
  Check(StudyHistory.ErrorCode("DRIVE_VALIDATION_FAILED details")=="DRIVE_VALIDATION_FAILED","error extraction");
  string longRoot=Path.Combine(root,new string('p',Math.Max(1,115-root.Length-1)));
  StudyHistory.Register(longRoot,model,study,run);
  Check(Directory.GetFiles(Path.Combine(longRoot,"runs","study-history",model)).Length==1,"atomic history temporary path budget");
  Console.WriteLine(checks);
 }
}
''', encoding='utf-8')
exe = folder / 'Probe.exe'
csc = Path(os.environ['WINDIR']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
subprocess.run([str(csc), '/nologo', '/platform:x64', '/r:System.Web.Extensions.dll', '/out:'+str(exe), str(ROOT/'executor/StudyHistory.cs'), str(source)], check=True)
result = subprocess.run([str(exe), str(folder)], text=True, capture_output=True, check=True)
report = {'all_passed': True, 'checks': int(result.stdout.strip()), 'cad_connection_used': False, 'production_module': 'executor/StudyHistory.cs'}
(ROOT/'runs/study-history-v04.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
