using System;
using System.IO;
using System.Text;
using System.Windows.Forms;
using System.Threading;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
class Program {
    static object Error(Exception e,string restoration="not_required") {
        string code=e.Message.Split(':')[0].Split(' ')[0];
        if(e is COMException) code="COM_CALL_FAILED";
        else if(e is IOException) code="FILE_ACCESS_FAILED";
        else if(e is InvalidCastException) code="API_TYPE_MISMATCH";
        else if(!Regex.IsMatch(code,"^[A-Z][A-Z0-9_]+$")) code="EXECUTOR_ERROR";
        var messages=new Dictionary<string,string> {
            {"RESULTS_STALE","运动结果已过期，请重新运行算例。"},
            {"MODEL_REVISION_CHANGED","模型文件或配置已改变，请重新求解。"},
            {"SOLVER_FAILED","Motion 求解失败，请检查驱动、配合与插件状态。"},
            {"RESTORATION_FAILED","无法确认初始状态已恢复，请检查 SolidWorks 当前姿态。"},
            {"POSE_MISMATCH","回放姿态与已校验轨迹不一致，检查无法给出通过结论。"},
            {"COM_CALL_FAILED","SolidWorks COM 调用失败，请检查软件忙碌状态和弹窗；没有自动重试写操作。"},
            {"FILE_ACCESS_FAILED","无法读取或保存测试文件，请检查占用状态与路径权限。"},
            {"API_TYPE_MISMATCH","SolidWorks 返回的数据类型未被当前执行器正确支持。"}
        };
        return new {code=code,message=messages.ContainsKey(code)?messages[code]:e.Message,assertion="inconclusive",restoration_status=restoration};
    }
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding=new UTF8Encoding(false);
        Console.InputEncoding=new UTF8Encoding(false);
        Mutex gate=null; bool ownsGate=false;
        try {
            gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor");
            try {ownsGate=gate.WaitOne(0);} catch(AbandonedMutexException) {ownsGate=true;throw new Exception("PREVIOUS_EXECUTOR_CRASH: inspect SolidWorks state before restarting");}
            if(!ownsGate) throw new Exception("EXECUTOR_ALREADY_RUNNING: use one MCP server at a time");
            string root=Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"..",".."));
            var cad=new Cad(root);
            if(args.Length>0 && args[0]=="build-motion-examples") {Console.WriteLine(Cad.Json.Serialize(cad.BuildMotionExamples()));return 0;}
            if(args.Length>0 && args[0]=="build-fixture") { Console.WriteLine(Cad.Json.Serialize(cad.BuildFixture())); return 0; }
            if(args.Length>0 && args[0]=="build-gear-pump") { Console.WriteLine(Cad.Json.Serialize(cad.BuildGearPump())); return 0; }
            if(args.Length>0 && args[0]=="recover-pump") { Console.WriteLine(Cad.Json.Serialize(cad.RecoverPump())); return 0; }
            if(args.Length>0 && args[0]=="advanced-probe") { cad.ProbeAdvanced();Console.WriteLine("ADVANCED_PROBE_SAVED");return 0; }
            if(args.Length>0 && args[0]=="diagnose-session") {Console.WriteLine(Cad.Json.Serialize(cad.SessionDiagnosis()));return 0;}
            if(args.Length>0 && args[0]=="phase-diagnosis") { cad.DiagnosePhase();Console.WriteLine("PHASE_DIAGNOSIS_SAVED");return 0; }
            if(args.Length>0 && args[0]=="fast-validation") {string run=Guid.NewGuid().ToString("N");cad.Solve("gear_pump","齿轮泵_30rpm",2,30,run);Console.WriteLine(Cad.Json.Serialize(cad.FastCheck(run,1,.001,null)));return 0;}
            if(args.Length>0 && args[0]=="validate-fixture") { Console.WriteLine(Cad.Json.Serialize(cad.Solve("clear","MVP_60rpm",1,60,"fixture-validation"))); return 0; }
            Console.WriteLine(Cad.Json.Serialize(new { protocol_version=1, ready=true, revision=cad.Sw.RevisionNumber(),process_id=cad.Sw.GetProcessID() }));
            var queue=new BlockingCollection<string>();
            var reader=new Thread(()=>{ string line; while((line=Console.ReadLine())!=null) queue.Add(line);queue.CompleteAdding(); }); reader.IsBackground=true;reader.Start();
            while(!queue.IsCompleted) {
                string line; if(!queue.TryTake(out line,20)) {Application.DoEvents();continue;}
                string id=null;
                try {var req=Cad.Json.Deserialize<Dictionary<string,object>>(line);id=(string)req["id"];var result=cad.Dispatch(req);Console.WriteLine(Cad.Json.Serialize(new {id=id,ok=true,result=result}));}
                catch(Exception e) {Cad.Log(e.ToString());Console.WriteLine(Cad.Json.Serialize(new { id=id,ok=false,error=Error(e,cad.LastOperationRestoration) }));}
                Console.Out.Flush();Application.DoEvents();
            }
            return 0;
        } catch(Exception e) { Console.Error.WriteLine(e); if(args.Length==0)Console.WriteLine(Cad.Json.Serialize(new {protocol_version=1,ready=false,error=Error(e)})); return 1; }
        finally {if(ownsGate) gate.ReleaseMutex();if(gate!=null) gate.Dispose();}
    }
}
