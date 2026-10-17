"""Repeat with --executor-source pointing at an archived release for matched comparisons."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix
matrix.CS=matrix.CS[:matrix.CS.index('class ProbeAcceptance')]+r"""
class ProbeAcceptance {
 static Dictionary<string,object> D(object x){return Cad.Json.Deserialize<Dictionary<string,object>>(Cad.Json.Serialize(x));}
 [STAThread]static int Main(string[] a){if(a.Length==2&&a[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(a[1]);var r=new Dictionary<string,object>{{"completed",false}};Cad cad=null;int pid=int.Parse(a[2]);Action save=()=>File.WriteAllText(Path.Combine(a[0],"native.json"),Cad.Json.Serialize(r));using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{cad=new Cad(a[0]);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");var imported=D(cad.ImportUserAssembly(a[1],""));string id=(string)imported["model_id"];r["environment"]=cad.UserEnvironment();r["import"]=imported;foreach(var st in Cad.Json.Deserialize<Cad.StudyState[]>(Cad.Json.Serialize(cad.ProbeTestStates(id))))if(Math.Abs(st.time_s)>1e-8)cad.ResetUserStudyTime(id,st.name,true);save();
 var timer=System.Diagnostics.Stopwatch.StartNew();r["references"]=cad.ListMateReferences(id,"","cylindrical_axis",20,null,true);r["reference_query_ms"]=timer.ElapsedMilliseconds;save();timer.Restart();r["drives"]=cad.UserDriveCandidates(id,"","cylindrical_axis",20,null,true,true);r["drive_query_ms"]=timer.ElapsedMilliseconds;save();timer.Restart();r["checkpoint"]=cad.ProbeTestOnly(id);r["checkpoint_total_ms"]=timer.ElapsedMilliseconds;save();var components=Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(D(cad.InspectUserModel(id,"components"))["components"]));var component=components.Single(e=>!(bool)e["fixed_component"]&&((string)e["instance"]).IndexOf("Part6",StringComparison.OrdinalIgnoreCase)>=0);string cid=(string)component["component_id"];var references=Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(D(cad.ListMateReferences(id,cid,"cylindrical_axis",20,null,true))["entities"]));var drive=references.First(e=>Math.Abs(((System.Collections.IEnumerable)e["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last())>.99);string eid=(string)drive["entity_id"];r["created"]=cad.CreateUserStudy(id,"MatchedPerformance",cid,eid,"rotary",30,false,"",4,30);save();timer.Restart();r["run"]=cad.RunUserStudy(id,"MatchedPerformance",4,30,Guid.NewGuid().ToString("N"));r["run_ms"]=timer.ElapsedMilliseconds;save();timer.Restart();r["verify"]=cad.VerifyRequestedMotion(id,"MatchedPerformance",cid,eid,"rotary",720,4,30,Guid.NewGuid().ToString("N"),"");r["verify_ms"]=timer.ElapsedMilliseconds;if((string)D(r["verify"])["assertion"]!="pass")throw new Exception("MATCHED_VERIFY_FAILED");r["completed"]=true;save();return 0;
 }catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
"""
if __name__=='__main__':
 if '--with-apply' in sys.argv:
  sys.argv.remove('--with-apply')
  target='var component=components.Single'
  extra=r'''Func<string,Dictionary<string,object>> plane=name=>{var c=components.Single(e=>((string)e["instance"]).IndexOf(name,StringComparison.OrdinalIgnoreCase)>=0);var rows=Cad.Json.Deserialize<Dictionary<string,object>[]>(Cad.Json.Serialize(D(cad.ListMateReferences(id,(string)c["component_id"],"planar_normal",50,null,true))["entities"]));return rows.First(e=>Math.Abs(((System.Collections.IEnumerable)e["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last())>.99);};var pa=plane("Part10");var pb=plane("Part5");double za=((System.Collections.IEnumerable)pa["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last(),zb=((System.Collections.IEnumerable)pb["axis_global"]).Cast<object>().Select(Convert.ToDouble).Last();var plan=D(cad.PreviewBasicMate(id,(string)pa["entity_id"],(string)pb["entity_id"],"parallel",za*zb>0?"aligned":"anti_aligned",0,false,""));timer.Restart();r["apply"]=cad.ApplyBasicMate((string)plan["plan_id"],true);r["apply_ms"]=timer.ElapsedMilliseconds;save();'''
  matrix.CS=matrix.CS.replace(target,extra+target)
 if '--executor-source' in sys.argv:
  import subprocess,hashlib,json
  index=sys.argv.index('--executor-source');source=Path(sys.argv[index+1]).resolve();del sys.argv[index:index+2]
  files=list(source.glob('*.cs'));assert files and (source/'Runtime.cs').is_file()
  original=matrix.subprocess.run
  def compile_source(command,*args,**kwargs):
   if isinstance(command,list) and command and str(command[0]).lower().endswith('csc.exe'):
    command=[v for v in command if not (str(v).lower().endswith('.cs') and Path(v).parent==matrix.ROOT/'executor')]+[str(p) for p in files]
   return original(command,*args,**kwargs)
  matrix.subprocess.run=compile_source
 matrix.main()
