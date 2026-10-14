"""Compiled transaction evidence and nested observation scopes; no CAD connection."""
import json, os, shutil, subprocess, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'runs/qzc-evidence-tests'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
source=folder/'Checks.cs'
source.write_text(r'''using System;using System.IO;using System.Linq;using System.Reflection;using System.Collections.Generic;using System.Runtime.Serialization;using System.Text;
class QzcChecks {
 static int count;
 static void C(bool ok){if(!ok)throw new Exception("check "+count);count++;}
 static Dictionary<string,object> D(object x){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(x));}
 static object Call(Cad cad,string name,params object[] args){return typeof(Cad).GetMethod(name,BindingFlags.NonPublic|BindingFlags.Instance).Invoke(cad,args);}
 static void Main(string[] args){
  C(MateExecutionEvidence.ErrorName(5)=="swAddMateError_OverDefinedAssembly");C(MateExecutionEvidence.ErrorMessage(5).Contains("过定义"));C(MateExecutionEvidence.ErrorName(1)=="swAddMateError_NoError");C(MateExecutionEvidence.ErrorName(0)=="swAddMateError_ErrorUknown");C(MateExecutionEvidence.ErrorName(99)=="unknown_swAddMateError_value");
  var execution=new MateExecutionEvidence{Stage="native_add_mate",NativeError=5,NativeObjectReturned=true};var failure=D(execution.Export());C((bool)failure["native_object_returned"]);C(!(bool)failure["write_committed"]);C(failure["native_feature_observed"]==null);C(failure["native_rebuild_accepted"]==null);C((string)failure["failure_stage"]=="native_add_mate");
  execution.WriteCommitted=true;execution.Stage="completed";C(D(execution.Export())["failure_stage"]==null);
  var cad=(Cad)FormatterServices.GetUninitializedObject(typeof(Cad));typeof(Cad).GetField("Root").SetValue(cad,args[0]);
  var model=new Cad.UserModel{Id="user_"+new string('a',32),Directory=Path.Combine(args[0],"experiments","user_assemblies",new string('a',32)),Revision=2};Directory.CreateDirectory(model.Directory);
  var hashes=Enumerable.Range(0,300).ToDictionary(i=>Path.Combine(model.Directory,"files","long-path-part-"+i+".SLDPRT"),i=>"SENSITIVE_FULL_HASH_"+i+new string('f',64));
  File.WriteAllText(Path.Combine(model.Directory,"last-save-observation.json"),Cad.Json.Serialize(new{model_id=model.Id,stages=new[]{new{stage="legacy",file_hashes=hashes}}}));
  var observation=new{complete=true,dirty_documents_observed=false,stages=new[]{new{stage="read",dirty_document_count=0}}};string op;
  using((IDisposable)Call(cad,"BeginSaveObservationOperation","apply_mate")){
   for(int i=0;i<20;i++)Call(cad,"RecordSaveObservation",model,"phase_"+i,observation,hashes);
   var summary=D(Call(cad,"SaveObservation",model));op=(string)summary["operation_id"];C(Convert.ToInt32(summary["stage_count"])==20);C((bool)summary["stages_truncated"]);C(Encoding.UTF8.GetByteCount(Cad.Json.Serialize(summary))<=4096);C(!Cad.Json.Serialize(summary).Contains("SENSITIVE_FULL_HASH"));C((string)summary["scope"]=="current_operation");C(summary["archived_legacy_query"]!=null);C(Directory.GetFiles(Path.Combine(model.Directory,"save-observations","legacy"),"*.json").Length==1);
   using((IDisposable)Call(cad,"BeginSaveObservationOperation","create_model_checkpoint")){Call(cad,"RecordSaveObservation",model,"nested",observation,hashes);var nested=D(Call(cad,"SaveObservation",model));C((string)nested["operation_id"]==op);C((string)nested["operation_name"]=="apply_mate");C(Convert.ToInt32(nested["stage_count"])==21);}
  }
  string history=Path.Combine(model.Directory,"save-observations",op);C(Directory.GetFiles(history,"*.json").Length==22);C(Directory.GetFiles(history,"*.sha256").Length==21);
  C(File.ReadAllText(Path.Combine(history,"0000000001.json")).Contains("SENSITIVE_FULL_HASH"));
  using((IDisposable)Call(cad,"BeginSaveObservationOperation","reset_study_time")){Call(cad,"RecordSaveObservation",model,"after_reset",observation,hashes);var summary=D(Call(cad,"SaveObservation",model));C((string)summary["operation_id"]!=op);C(Convert.ToInt32(summary["stage_count"])==1);C(Directory.GetFiles(history,"*.json").Length==22);}
  // A pose mismatch or unknown restoration must never acquire an image manifest.
  var runType=typeof(Cad).GetNestedType("Run",BindingFlags.NonPublic);var run=Activator.CreateInstance(runType);bool rejected=false;
  try{Call(cad,"RecordVerifiedReplayImage",run,new string('b',32),0,"",new{within_pose_tolerance=false});}catch(TargetInvocationException error){rejected=error.InnerException is CadFault&&((CadFault)error.InnerException).Code=="IMAGE_CAPTURE_UNVERIFIED";}C(rejected);
  Console.WriteLine(count);
 }
}''',encoding='utf-8')
redist=Path(os.environ.get('SW_INSTALL_DIR',r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS'))/'api/redist'
for p in redist.glob('SolidWorks.Interop.*.dll'):shutil.copyfile(p,folder/p.name)
exe=folder/'Checks.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
args=[str(compiler),'/nologo','/platform:x64','/main:QzcChecks','/reference:System.Web.Extensions.dll','/reference:System.Windows.Forms.dll','/reference:Microsoft.CSharp.dll','/out:'+str(exe)]
args+=['/reference:'+str(redist/p) for p in ('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')]
subprocess.run(args+[str(p) for p in (ROOT/'executor').glob('*.cs')]+[str(source)],check=True)
result=subprocess.run([str(exe),str(folder)],capture_output=True,check=True)
count=int(result.stdout.decode().strip());report={'all_passed':True,'checks':count,'cad_connection_used':False,'attempt':folder.name}
(folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
