// Acceptance-only instrumentation. No production changes or explicit COM release experiments.
using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Diagnostics;
using System.Text;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public object AcceptanceControl(string action,int expectedPid) {
        global::AcceptanceControl.Stage("before_pid_check",null);
        if(Sw.GetProcessID()!=expectedPid)throw new Exception("OWNED_PID_MISMATCH");
        global::AcceptanceControl.Stage("connected_identity",new{expected_pid=expectedPid,actual_pid=Sw.GetProcessID(),revision=Sw.RevisionNumber(),
            explicit_COM_release_performed=false,scope="diagnostic_observation_not_an_exit_fix"});
        if(action=="exit")global::AcceptanceControl.Stage("native_module_observation",global::AcceptanceControl.Modules(expectedPid));
        global::AcceptanceControl.Stage("before_document_inventory",null);
        var docs=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().ToArray();
        var inventory=docs.Select(d=>new{path=d.GetPathName(),title=d.GetTitle(),type=d.GetType()}).ToArray();
        global::AcceptanceControl.Stage("document_inventory",new{document_count=docs.Length,documents=inventory});
        if(action=="empty") {
            if(docs.Length!=0)throw new Exception("OWNED_INSTANCE_NOT_EMPTY");
            return new{ready=true,pid=expectedPid,document_count=0};
        }
        if(action!="exit")throw new Exception("UNKNOWN_CONTROL_ACTION");
        string prefix=Path.GetFullPath(Root).TrimEnd(Path.DirectorySeparatorChar)+Path.DirectorySeparatorChar;
        if(inventory.Any(d=>String.IsNullOrEmpty(d.path)||!Path.GetFullPath(d.path).StartsWith(prefix,StringComparison.OrdinalIgnoreCase)))
            throw new Exception("NON_OWNED_DOCUMENT_REFUSE_EXIT");
        global::AcceptanceControl.Stage("before_close_documents",new{document_count=docs.Length});
        CloseUserDocuments(inventory.Select(d=>d.path).ToArray());
        global::AcceptanceControl.Stage("after_close_documents",null);
        int remaining=(Sw.GetDocuments() as object[]??new object[0]).Length;
        global::AcceptanceControl.Stage("closed_document_inventory",new{document_count=remaining});
        if(remaining!=0)throw new Exception("DOCUMENTS_STILL_OPEN_REFUSE_EXIT");
        global::AcceptanceControl.Stage("before_ExitApp",new{pid=expectedPid,document_count=remaining});
        Sw.ExitApp();
        global::AcceptanceControl.Stage("after_ExitApp_returned",new{native_exit_code_not_observed_by_helper=true});
        return new{exit_requested=true,pid=expectedPid};
    }
}

class AcceptanceControl {
    static string eventPath;
    static readonly Stopwatch clock=Stopwatch.StartNew();
    public static void Stage(string stage,object evidence) {
        if(eventPath==null)return;
        string text=Cad.Json.Serialize(new{stage=stage,observed_at_utc=DateTime.UtcNow.ToString("o"),
            elapsed_ms=clock.Elapsed.TotalMilliseconds,helper_pid=Process.GetCurrentProcess().Id,evidence=evidence});
        File.AppendAllText(eventPath,text+System.Environment.NewLine,new UTF8Encoding(false));
    }
    public static object Modules(int pid) {
        try {
            var process=Process.GetProcessById(pid);
            var modules=process.Modules.Cast<ProcessModule>().Select(m=>new{name=m.ModuleName,path=m.FileName}).Take(4096).ToArray();
            return new{status="observed",observed_pid=pid,native_start_utc=process.StartTime.ToUniversalTime().ToString("o"),native_file_version=process.MainModule.FileVersionInfo.FileVersion,
                modules=modules,claim="loaded_binary_modules_not_COM_addin_activation_or_causal_proof"};
        }catch(Exception e){return new{status="unavailable",error=e.Message,hresult=e.HResult};}
    }
    [STAThread] static int Main(string[] a) {
        Console.OutputEncoding=new UTF8Encoding(false);
        try {
            if(a.Length!=4)throw new Exception("CONTROL_ARGUMENTS_REQUIRED");
            eventPath=Path.ChangeExtension(a[3],"stages.jsonl");
            Stage("control_begin",new{action=a[1],expected_sw_pid=Int32.Parse(a[2]),root=Path.GetFullPath(a[0])});
            using(var gate=new Mutex(false,"Local\\SolidWorksClashMate_MechDog_Executor")) {
                Stage("before_mutex_wait",new{maximum_wait_ms=10000});
                if(!gate.WaitOne(10000))throw new Exception("EXECUTOR_MUTEX_BUSY_AFTER_10S");
                try {
                    Stage("before_COM_connect",null);
                    var cad=new Cad(a[0]);
                    Stage("after_COM_connect",null);
                    var result=cad.AcceptanceControl(a[1],Int32.Parse(a[2]));
                    File.WriteAllText(a[3],Cad.Json.Serialize(new{ok=true,result=result}),new UTF8Encoding(false));
                    Stage("result_written",new{helper_return_code=0,native_exit_code_not_proven=true});
                    return 0;
                } finally {gate.ReleaseMutex();}
            }
        }catch(Exception e) {
            try{Stage("control_failed",new{error=e.ToString(),hresult=e.HResult});}catch{}
            if(a.Length==4)File.WriteAllText(a[3],Cad.Json.Serialize(new{ok=false,error=e.ToString()}),new UTF8Encoding(false));
            Console.Error.WriteLine(e.ToString());return 1;
        }
    }
}
