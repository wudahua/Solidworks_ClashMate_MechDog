import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix
matrix.CS=matrix.CS[:matrix.CS.index('class ProbeAcceptance')]+r"""
public partial class Cad {
 public object ArchivedProbe(string directory){var d=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(directory,"checkpoint.json")));var m=Json.Deserialize<UserModel>(Json.Serialize(d["model"]));var inputHashes=Directory.GetFiles(directory).ToDictionary(p=>p,p=>FileHash(p));var copies=m.Files.ToDictionary(p=>p,p=>Path.Combine(directory,Path.GetFileName(p)));string folder=Path.Combine(Root,"runs","probes",Guid.NewGuid().ToString("N").Substring(0,8));Directory.CreateDirectory(folder);Dictionary<string,string> renames;var isolated=CopyProbeInputs(m,copies,folder,out renames);var proof=RunIsolatedProbe(folder,new Dictionary<string,object>{{"kind","checkpoint"},{"model",isolated},{"studies",d["studies"]},{"poses",d["poses"]},{"renames",renames}});if(inputHashes.Any(p=>FileHash(p.Key)!=p.Value))throw new Exception("ARCHIVED_INPUT_MODIFIED");return new{proof=proof,archived_input_files_unchanged=true,archived_file_count=inputHashes.Count};}
}
class ProbeAcceptance {
 [STAThread]static int Main(string[] a){if(a.Length==2&&a[0]=="--isolated-probe")return Cad.IsolatedProbeWorker(a[1]);Cad cad=null;int pid=int.Parse(a[2]);var r=new Dictionary<string,object>{{"completed",false}};Action save=()=>File.WriteAllText(Path.Combine(a[0],"native.json"),Cad.Json.Serialize(r));using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")){if(!gate.WaitOne(0))return 4;try{cad=new Cad(a[0]);if(cad.Sw.GetProcessID()!=pid||(cad.Sw.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");var path=System.Environment.GetEnvironmentVariable("ARCHIVED_CP");for(int i=0;i<2;i++){r["probe_"+i]=cad.ArchivedProbe(path);save();}r["completed"]=true;save();return 0;}catch(Exception e){r["error"]=e.ToString();r["details"]=e is CadFault?((CadFault)e).Diagnostics:null;save();return 1;}finally{if(cad!=null)try{cad.ProbeTestExit(pid);}catch(Exception e){r["cleanup_error"]=e.ToString();}save();gate.ReleaseMutex();}}}
}
"""
if __name__=='__main__':
    # Explicit private path, never a hardcoded user model in the release.
    if '--checkpoint' not in sys.argv:raise SystemExit('--checkpoint DIRECTORY is required')
    import os
    index=sys.argv.index('--checkpoint');os.environ['ARCHIVED_CP']=str(Path(sys.argv[index+1]).resolve());del sys.argv[index:index+2]
    matrix.main()
