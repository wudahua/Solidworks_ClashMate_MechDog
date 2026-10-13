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
    static object Error(Exception e,string restoration="not_required",string contextRestoration="not_required") {
        var fault=e as CadFault;string code=fault==null?e.Message.Split(':')[0].Split(' ')[0]:fault.Code;
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
        messages["CHECKPOINT_REQUIRES_INITIAL_TIME"]="当前激活算例不在初始时刻；请先使用 reset_study_time 归零，再建立检查点。";
        messages["CREATE_STUDY_REQUIRES_INITIAL_TIME"]="当前激活算例不在初始时刻；请先使用 reset_study_time 归零，再添加驱动。";
        messages["EXECUTOR_ALREADY_RUNNING"]="已有其他 MCP 执行器运行；请先停用该服务，保留 SolidWorks 打开。";
        messages["CHECKPOINT_SETTINGS_MISMATCH"]="恢复后的算例类型、帧率、时间或激活状态与检查点不一致。";
        messages["CHECKPOINT_TIME_RESTORE_FAILED"]="SolidWorks 拒绝恢复算例时间；保留检查点和日志后核对模型状态。";
        messages["STUDY_NOT_FOUND"]="登记副本中没有该运动算例；请先 list_motion_studies 核对名称。";
        messages["MODEL_PREFLIGHT_FAILED"]="模型预检存在阻塞项；请查看 diagnostics 并修正副本或重新导入。";
        messages["DRIVE_ENTITY_STALE"]="驱动参考已过期；请重新查询驱动候选。";
        messages["CANDIDATE_CURSOR_STALE"]="候选分页游标已过期；模型或配置已改变，请从第一页重新查询。";
        messages["ACTIVE_TIME_NOT_FRAME_ALIGNED"]="激活算例停在非输出帧时刻；请先显式 reset_study_time 归零，再求解或回放。";
        messages["COM_SESSION_NOT_FOUND"]="未找到指定或已启动的 SolidWorks 实例；启动软件并核对 PID 后重试连接。";
        messages["COM_SESSION_UNAVAILABLE"]="SolidWorks 实例尚未提供可用 COM 会话；确认启动完成后重试连接。";
        messages["DRIVE_ENTITY_NOT_FOUND"]="驱动引用未在当前模型中登记；请重新 list_drive_candidates 选择候选并核对 entity_id。";
        messages["NATIVE_TIME_AXIS_MISMATCH"]="原生结果时间轴与请求采样网格不一致；请查看时间轴诊断，未采集姿态或判定通过。";
        messages["MOTION_RESULTS_INCOMPLETE"]="原生求解没有提供覆盖请求时段的结果；请检查所选驱动是否与配合相容，并查看求解诊断。";
        messages["INVALID_MODEL_ID"]="model_id 格式错误；请使用 list_models 或 import_assembly 返回的完整标识（user_ 加32位小写十六进制）。";
        messages["MODEL_NOT_REGISTERED"]="该模型未在当前安装目录登记；请先 list_models 核对，或 import_assembly 创建副本。";
        string fallback="执行器拒绝请求（"+code+"）；请查看 diagnostics 中的原生诊断。";
        return new {code=code,message=messages.ContainsKey(code)?messages[code]:fault==null?fallback:fault.Message,assertion="inconclusive",restoration_status=restoration,document_context_restoration_status=contextRestoration,diagnostics=new{details=fault==null?null:fault.Diagnostics,native_message=e.Message,hresult=e.HResult}};
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
                catch(Exception e) {Cad.Log(e.ToString());Console.WriteLine(Cad.Json.Serialize(new { id=id,ok=false,error=Error(e,cad.LastOperationRestoration,cad.LastContextRestoration) }));}
                Console.Out.Flush();Application.DoEvents();
            }
            return 0;
        } catch(Exception e) { Console.Error.WriteLine(e); if(args.Length==0)Console.WriteLine(Cad.Json.Serialize(new {protocol_version=1,ready=false,error=Error(e)})); return 1; }
        finally {if(ownsGate) gate.ReleaseMutex();if(gate!=null) gate.Dispose();}
    }
}
