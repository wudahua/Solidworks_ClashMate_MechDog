"""Fault-injected native command flag lifecycle tests, without CAD."""
import json
import os
import subprocess
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'runs/v042a8-policy'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    source=folder/'Checks.cs';source.write_text(r'''using System;
class Checks {
 static int count;static void Check(bool value){count++;if(!value)throw new Exception("check "+count);}
 static int Main(){try{
 foreach(bool initial in new[]{false,true}){bool value=initial;int writes=0;using(var scope=new NativeCommandBatch(()=>value,v=>{writes++;value=v;})){Check(value);Check(scope.Previous==initial);}Check(value==initial);Check(writes==(initial?0:2));}
 bool state=false;try{using(var scope=new NativeCommandBatch(()=>state,v=>state=v)){throw new Exception("frame failure");}}catch(Exception e){Check(e.Message=="frame failure");}Check(!state);
 int n=0;state=false;try{using(var scope=new NativeCommandBatch(()=>state,v=>{if(++n==2)throw new Exception("restore rpc lost");state=v;})){}throw new Exception("not blocked");}catch(NativeCommandStateException){Check(true);}Check(state);
 state=false;n=0;try{using(var scope=new NativeCommandBatch(()=>state,v=>{state=v;n++;if(v)throw new Exception("set reported failure after applying");})){}throw new Exception("not blocked");}catch(Exception e){Check(e.Message=="set reported failure after applying");}Check(!state&&n==2);
 Console.WriteLine(count);return 0;}catch(Exception e){Console.Error.WriteLine(e);return 1;}}
}''',encoding='utf-8',newline='\n')
    exe=folder/'Checks.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/out:'+str(exe),str(ROOT/'executor/NativeCommandBatch.cs'),str(source)],check=True)
    count=int(subprocess.check_output([str(exe)],text=True).strip())
    report={'all_passed':True,'checks':count,'cad_connection_used':False};(folder/'result.json').write_text(json.dumps(report),encoding='utf-8');print(json.dumps(report))
if __name__=='__main__':main()
