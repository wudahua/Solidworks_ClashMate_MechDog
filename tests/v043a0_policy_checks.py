"""Exclusive phase accounting and historical read contracts; no CAD/interop."""
import json,os,subprocess,uuid,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'runs/v043a0-policy'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    source=folder/'Checks.cs';source.write_text(r'''using System;using System.Linq;using System.Collections.Generic;using System.Web.Script.Serialization;
class Checks {static int n;static void Check(bool ok){n++;if(!ok)throw new Exception("check "+n);}static Dictionary<string,object> D(object x){var j=new JavaScriptSerializer();return j.Deserialize<Dictionary<string,object>>(j.Serialize(x));}
static int Main(){double now=0;var p=new SolvePerformance(()=>now);now=10;p.Phase("calculate");now=40;p.Phase("sampling");now=50;var result=D(p.Finish(true));var phases=D(result["phase_totals_ms"]);Check(Convert.ToDouble(result["total_elapsed_ms"])==50);Check(Convert.ToDouble(result["attributed_elapsed_ms"])==50);Check(Convert.ToDouble(result["unattributed_elapsed_ms"])==0);Check(Convert.ToDouble(phases["calculate"])==30);Check((bool)result["execution_completed"]);Check((string)result["root_cause"]=="not_proven_by_timing_alone");
now=0;p=new SolvePerformance(()=>now);now=2;p.Phase("native_call");try{now=8;throw new Exception("fault");}catch{result=D(p.Finish(false));}Check(!(bool)result["execution_completed"]);Check(Convert.ToDouble(result["total_elapsed_ms"])==8);bool refused=false;try{p.Phase("late");}catch(InvalidOperationException){refused=true;}Check(refused);
var history=D(HistoricalUsage.ForRun("actual-run"));Check(Convert.ToInt32(history["schema_version"])==1);Check((string)D(history["default_verified_summary"])["tool"]=="get_motion_summary");Check(!(bool)D(history["quarantine_artifact_query"])["requires_verified_result"]);Console.WriteLine(n);Console.WriteLine(new JavaScriptSerializer().Serialize(history));return 0;}}
''',encoding='utf-8',newline='\n')
    exe=folder/'Checks.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe),str(ROOT/'executor/SolvePerformance.cs'),str(ROOT/'executor/HistoricalUsage.cs'),str(source)],check=True)
    lines=subprocess.check_output([str(exe)],text=True).strip().splitlines();checks=int(lines[0])
    sys.path.insert(0,str(ROOT))
    from sw_mcp.artifacts import Artifacts
    assert json.loads(lines[1])==Artifacts.history_usage('actual-run')
    print(json.dumps({'all_passed':True,'checks':checks+1,'cad_connection_used':False,'python_native_history_schema_equal':True}))
if __name__=='__main__':main()
