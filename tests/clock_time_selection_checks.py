"""Compile the production selector and reproduce the native endpoint roundoff."""
import json,os,subprocess,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'runs/clock-time-tests'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
source=folder/'Checks.cs'
source.write_text('''using System;using System.IO;using System.Threading;
class Checks {
 static void Check(bool ok){if(!ok)throw new Exception("time selection check failed");}
 static int Main(string[] args){try {
 Check(MotionTimeSelection.Argument(0,1)==0);
 Check(MotionTimeSelection.Argument(1,1)==1);
 Check(MotionTimeSelection.Argument(.9999999999999999,1)==1);
 Check(MotionTimeSelection.Argument(2-.0000000000000004,2)==2);
 Check(MotionTimeSelection.Argument(.5,1)>.5);
 Check(MotionTimeSelection.Argument(.5,1)<1);
 Check(MotionTimeSelection.Argument(30-.000000000000003,30)==30);
 Check(MotionTimeSelection.Argument(1-.000000005,1)<=1);
 string path=Path.Combine(args[0],"shared.json");AtomicMetadata.Write(path,"old");
 var opened=new ManualResetEvent(false);
 Exception readerError=null;var reader=new Thread(()=>{try {using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read)){opened.Set();Thread.Sleep(120);}}catch(Exception e){readerError=e;}finally {opened.Set();}});reader.Start();Check(opened.WaitOne(5000));
 AtomicMetadata.Write(path,"new");reader.Join();if(readerError!=null)throw readerError;Check(File.ReadAllText(path)=="new");
 Check(Directory.GetFiles(args[0],"*.tmp").Length==0);
 Console.WriteLine("10 checks passed");return 0;
 }catch(Exception e){Console.Error.WriteLine("CHECK_FAILED type="+e.GetType().FullName+" hresult="+e.HResult+" message="+e.Message);return 1;}
 }
}''',encoding='utf-8')
compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe';exe=folder/'Checks.exe'
subprocess.run([str(compiler),'/nologo','/out:'+str(exe),str(ROOT/'executor/MotionTimeSelection.cs'),str(ROOT/'executor/AtomicMetadata.cs'),str(source)],check=True)
result=subprocess.run([str(exe),str(folder)],capture_output=True)
if result.returncode:
    failure={'all_passed':False,'checks':10,'cad_connection_used':False,'returncode':result.returncode,'diagnostic':result.stderr.decode('utf-8',errors='replace'),'attempt':folder.name}
    (folder/'result.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
    (ROOT/'runs/clock-time-selection-checks.json').write_text(json.dumps(failure,indent=2),encoding='utf-8')
    raise RuntimeError(failure['diagnostic'])
report={'all_passed':True,'checks':10,'cad_connection_used':False,'production_selector':True,'native_endpoint_roundoff_regression':True,'windows_shared_reader_metadata_write_regression':True}
report['attempt']=folder.name
(folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(ROOT/'runs/clock-time-selection-checks.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
